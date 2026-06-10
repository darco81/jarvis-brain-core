"""Thin facade over graphifyy. Only file in brain that imports the upstream lib."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

import networkx as nx
from graphify import analyze as gfy_analyze
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import generate_html

from brain.core.graph_schema import Graph
from brain.publishers.common import NODE_ID_TO_SLUG_JS
from brain.viz.schema_adapter import to_graphifyy_extraction


class InsightsOutput(TypedDict):
    graph_html_path: Path
    insights_json_path: Path
    obsidian_dir: Path | None
    communities: dict[int, list[str]]


_PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>brain-core :: graph too large</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 3rem auto;
            padding: 0 1rem; color: #222; line-height: 1.45; }}
    h1 {{ font-size: 1.2rem; }}
    code {{ background: #f3f3f3; padding: 0.1rem 0.3rem; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>graph too large for vis-network</h1>
  <p>Master graph: <strong>{node_count}</strong> nodes (visualization limit: <strong>{limit}</strong>).</p>
  <p>vis-network chokes above ~4500 nodes. Render per-repo graphs instead and use
     <code>brain_path</code> / <code>brain_query</code> via MCP for navigation.</p>
</body>
</html>
"""

# In production the rendered graph.html gets a navigation bar injected pointing
# to wiki / dashboard / login. The educational version skips that chrome - the
# raw graphifyy-generated HTML is enough to demonstrate the pattern.
_VIS_PERF_AND_NAV_JS = """
<script>
// vis-network performance optimization - disable physics after stabilization,
// hide edges on drag/zoom. Cuts render lag dramatically on 2000+ node graphs.
(function optimizeVisNetwork(){
  function tryOptimize(){
    if(typeof network === 'undefined' || !network) return false;
    try {
      network.setOptions({
        physics: {
          stabilization: { iterations: 80, updateInterval: 25, fit: true },
          barnesHut: { gravitationalConstant: -8000, springConstant: 0.04, damping: 0.5 },
        },
        interaction: { hideEdgesOnDrag: true, hideEdgesOnZoom: true, tooltipDelay: 300 },
        edges: { smooth: false },
      });
      network.once('stabilizationIterationsDone', function(){
        network.setOptions({ physics: false });
      });
      return true;
    } catch(e){ console.warn('vis opt failed:', e); return false; }
  }
  // vis-network is loaded async - poll for it
  var attempts = 0;
  var timer = setInterval(function(){
    if(tryOptimize() || ++attempts > 20) clearInterval(timer);
  }, 200);
})();
</script>
"""

_CLICK_HANDLER_JS = """
<script>
%s

(function attachBrainClickHandler(){
    // graphifyy renders nodes as SVG circles with `data-node-id` that maps
    // to the graphifyy-sanitized id. We resolve the brain id via a lookup
    // table embedded as JSON in a <script type=application/json> tag
    // injected alongside this handler (see _build_brain_id_map_script).
    var mapTag = document.getElementById('brain-id-map');
    if(!mapTag){ console.warn('brain: no id-map element'); return; }
    var idMap;
    try { idMap = JSON.parse(mapTag.textContent || '{}'); }
    catch(e){ console.warn('brain: id-map parse failed', e); return; }

    function onClick(ev){
        var t = ev.target;
        while(t && t !== document){
            var gid = t.getAttribute && t.getAttribute('data-node-id');
            if(gid){
                var brainId = idMap[gid];
                if(!brainId){
                    console.warn('brain: no brain_id for', gid);
                    return;
                }
                var group = brainId.split('/')[0];
                var slug = nodeIdToSlug(brainId);
                window.location.href = '/vault/' + group + '/_master/node/' + slug + '/';
                ev.preventDefault();
                ev.stopPropagation();
                return;
            }
            t = t.parentNode;
        }
    }
    document.addEventListener('click', onClick, true);
})();
</script>
"""


def _build_brain_id_map_script(extraction: dict[str, Any]) -> str:
    """Emit `<script type='application/json' id='brain-id-map'>{gid:brain_id}</script>`
    so the click handler can resolve a clicked SVG node's gid to a brain id."""
    mapping: dict[str, str] = {}
    for n in extraction.get("nodes", []):
        gid = n.get("id")
        brain_id = (n.get("metadata") or {}).get("_brain_id")
        if gid and brain_id:
            mapping[gid] = brain_id
    return (
        '<script type="application/json" id="brain-id-map">'
        + json.dumps(mapping)
        + "</script>"
    )


def _inject_click_handler(html_path: Path, extraction: dict[str, Any]) -> None:
    """Append the brain-id map + click handler JS before the final </body>.

    No-op if the HTML is our "too large" placeholder (no nodes to click).
    """
    try:
        html = html_path.read_text()
    except OSError:
        return
    # Detect placeholder HTML - no vis-network instance, no nodes to click.
    # Title is stable across theme changes; body text may be restyled.
    if "brain-core :: graph too large" in html:
        return
    if "</body>" not in html:
        return  # malformed - don't touch
    map_tag = _build_brain_id_map_script(extraction)
    handler = _CLICK_HANDLER_JS % NODE_ID_TO_SLUG_JS
    # _VIS_PERF_AND_NAV_JS adds vis-network perf opts
    injection = _VIS_PERF_AND_NAV_JS + map_tag + handler
    # Inject before LAST </body> to be safe with nested templates
    idx = html.rfind("</body>")
    new_html = html[:idx] + injection + html[idx:]
    html_path.write_text(new_html)


def _build_nx(graph: Graph) -> tuple[nx.Graph, dict[str, Any]]:
    extraction = to_graphifyy_extraction(graph)
    return build_from_json(extraction), extraction


def _write_insights_json(
    out_dir: Path,
    nx_graph: nx.Graph,
    communities: dict[int, list[str]],
    cohesion: dict[int, float],
    graph: Graph,
) -> Path:
    # god_nodes returns list[dict] with keys: id, label, degree
    gods: list[dict[str, Any]] = gfy_analyze.god_nodes(nx_graph)
    # surprising_connections returns list[dict] with keys: source, target, ...
    surprises: list[dict[str, Any]] = gfy_analyze.surprising_connections(nx_graph, communities)
    payload = {
        "communities": [
            {
                "id": cid,
                "size": len(nodes),
                "cohesion": cohesion.get(cid, 0.0),
            }
            for cid, nodes in sorted(communities.items())
        ],
        "god_nodes": [
            {"id": item["id"], "degree": item["degree"]}
            for item in gods[:20]
        ],
        "surprising_connections": [
            {"source": item["source"], "target": item["target"]}
            for item in surprises[:20]
        ],
        "stats": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "communities": len(communities),
        },
    }
    out = out_dir / "insights.json"
    out.write_text(json.dumps(payload, indent=2))
    return out


def render_master(
    graph: Graph,
    out_dir: Path,
    *,
    community_labels: dict[int, str] | None = None,
    max_nodes_viz: int = 4500,
) -> InsightsOutput:
    """Render master graph artifacts.

    max_nodes_viz default is 4500 (graphifyy 0.4.23 hard-fails generate_html
    above 5000 nodes; 4500 leaves headroom). Above this threshold a small
    placeholder HTML is emitted instead.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    nx_graph, extraction = _build_nx(graph)
    communities: dict[int, list[str]] = cluster(nx_graph)
    cohesion: dict[int, float] = score_all(nx_graph, communities)

    html_path = out_dir / "graph.html"
    if len(graph.nodes) > max_nodes_viz:
        html_path.write_text(
            _PLACEHOLDER_HTML.format(node_count=len(graph.nodes), limit=max_nodes_viz)
        )
    else:
        labels = community_labels or {cid: f"Community {cid}" for cid in communities}
        try:
            generate_html(nx_graph, communities, str(html_path), community_labels=labels)
            _inject_click_handler(html_path, extraction)
        except RuntimeError:
            # graphifyy has its own internal hard-limit (~5000 nodes). Fall back
            # to placeholder so the chain doesn't fail on viz alone.
            html_path.write_text(
                _PLACEHOLDER_HTML.format(node_count=len(graph.nodes), limit=max_nodes_viz)
            )

    insights_path = _write_insights_json(out_dir, nx_graph, communities, cohesion, graph)

    return InsightsOutput(
        graph_html_path=html_path,
        insights_json_path=insights_path,
        obsidian_dir=None,
        communities=communities,
    )


def render_repo(
    graph: Graph,
    out_dir: Path,
    *,
    community_labels: dict[int, str] | None = None,
) -> InsightsOutput:
    """Per-repo variant - no size threshold (per-repo graphs are small)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nx_graph, extraction = _build_nx(graph)
    communities: dict[int, list[str]] = cluster(nx_graph)
    cohesion: dict[int, float] = score_all(nx_graph, communities)

    html_path = out_dir / "graph.html"
    labels = community_labels or {cid: f"Community {cid}" for cid in communities}
    generate_html(nx_graph, communities, str(html_path), community_labels=labels)
    _inject_click_handler(html_path, extraction)

    insights_path = _write_insights_json(out_dir, nx_graph, communities, cohesion, graph)

    return InsightsOutput(
        graph_html_path=html_path,
        insights_json_path=insights_path,
        obsidian_dir=None,
        communities=communities,
    )
