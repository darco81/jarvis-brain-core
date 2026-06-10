"""Shared publisher utilities.

The slug function is the single source of truth for turning a graph node id
into a filesystem-safe, URL-safe identifier used by:
  * the wiki publisher (production-only) - to place per-node pages under
    `/node/<slug>/`
  * graph.html click handler - to navigate to the same `/node/<slug>/` URL
    when a user clicks a node

The JS port in `NODE_ID_TO_SLUG_JS` MUST remain byte-identical in behaviour
to `node_id_to_slug`. Tests lock them together on a fixture that stresses
truncation + hashing.
"""
from __future__ import annotations

import hashlib
import re

# Keep the full budget short enough to survive on all filesystems and to
# leave headroom for "/index.html" suffix. 200 is plenty.
_MAX_SLUG_LEN = 200
# When we need a hash suffix, we reserve 1 (underscore) + 8 (hex digits).
_HASH_SUFFIX_LEN = 9
# Non-hash prefix budget (keeps the readable part under this length).
_PREFIX_BUDGET = _MAX_SLUG_LEN - _HASH_SUFFIX_LEN  # 191

_SLUG_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def node_id_to_slug(node_id: str) -> str:
    """Turn a brain node id (e.g. `example-group/example-core:LoginButton`) into a
    slug (`example-group_example-core_LoginButton`) that is filesystem-safe.

    Deterministic: same input always yields same output.
    Collision-safe for long inputs: truncation appends 8 hex chars of md5.
    """
    if not node_id:
        return "unnamed"
    sanitized = _SLUG_SAFE_RE.sub("_", node_id).strip("_")
    if not sanitized:
        return "unnamed"
    if len(sanitized) <= _MAX_SLUG_LEN and len(node_id) <= _MAX_SLUG_LEN:
        return sanitized
    # Long input: keep readable prefix + md5 slice of the FULL original id
    # so different long inputs never collide.
    suffix = hashlib.md5(node_id.encode("utf-8")).hexdigest()[:8]  # noqa: S324
    prefix = sanitized[:_PREFIX_BUDGET].rstrip("_")
    return f"{prefix}_{suffix}"


# JS port - included verbatim in graph.html via insights_wrapper.py post-process.
# Uses a tiny pure-JS MD5 (hand-rolled) so there is zero CDN dependency.
# Function semantics MUST match Python node_id_to_slug exactly.
# ruff: noqa: E501
NODE_ID_TO_SLUG_JS = r"""
// --- MD5 (public-domain port, Paul Johnston) ---------------------------------
function brainMd5(str){function R(n,c){return(n<<c)|(n>>>(32-c))}
function T(a,b,c,d,x,s,t){return(((a+((b&c)|((~b)&d))+x+t)|0)<<s|((a+((b&c)|((~b)&d))+x+t)|0)>>>(32-s))+b|0}
function U(a,b,c,d,x,s,t){return(((a+((b&d)|(c&(~d)))+x+t)|0)<<s|((a+((b&d)|(c&(~d)))+x+t)|0)>>>(32-s))+b|0}
function V(a,b,c,d,x,s,t){return(((a+(b^c^d)+x+t)|0)<<s|((a+(b^c^d)+x+t)|0)>>>(32-s))+b|0}
function W(a,b,c,d,x,s,t){return(((a+(c^(b|(~d)))+x+t)|0)<<s|((a+(c^(b|(~d)))+x+t)|0)>>>(32-s))+b|0}
var bytes=[];for(var i=0;i<str.length;i++){var c=str.charCodeAt(i);
if(c<128)bytes.push(c);else if(c<2048){bytes.push(192|(c>>6));bytes.push(128|(c&63));}
else{bytes.push(224|(c>>12));bytes.push(128|((c>>6)&63));bytes.push(128|(c&63));}}
var bitlen=bytes.length*8;bytes.push(0x80);while((bytes.length%64)!==56)bytes.push(0);
for(var k=0;k<8;k++)bytes.push((bitlen>>>(k*8))&0xff);
var a=0x67452301,b=0xefcdab89,c=0x98badcfe,d=0x10325476;
for(var off=0;off<bytes.length;off+=64){var M=[];for(var j=0;j<16;j++){
M.push(bytes[off+j*4]|(bytes[off+j*4+1]<<8)|(bytes[off+j*4+2]<<16)|(bytes[off+j*4+3]<<24));}
var AA=a,BB=b,CC=c,DD=d;
a=T(a,b,c,d,M[0],7,-680876936);d=T(d,a,b,c,M[1],12,-389564586);c=T(c,d,a,b,M[2],17,606105819);b=T(b,c,d,a,M[3],22,-1044525330);
a=T(a,b,c,d,M[4],7,-176418897);d=T(d,a,b,c,M[5],12,1200080426);c=T(c,d,a,b,M[6],17,-1473231341);b=T(b,c,d,a,M[7],22,-45705983);
a=T(a,b,c,d,M[8],7,1770035416);d=T(d,a,b,c,M[9],12,-1958414417);c=T(c,d,a,b,M[10],17,-42063);b=T(b,c,d,a,M[11],22,-1990404162);
a=T(a,b,c,d,M[12],7,1804603682);d=T(d,a,b,c,M[13],12,-40341101);c=T(c,d,a,b,M[14],17,-1502002290);b=T(b,c,d,a,M[15],22,1236535329);
a=U(a,b,c,d,M[1],5,-165796510);d=U(d,a,b,c,M[6],9,-1069501632);c=U(c,d,a,b,M[11],14,643717713);b=U(b,c,d,a,M[0],20,-373897302);
a=U(a,b,c,d,M[5],5,-701558691);d=U(d,a,b,c,M[10],9,38016083);c=U(c,d,a,b,M[15],14,-660478335);b=U(b,c,d,a,M[4],20,-405537848);
a=U(a,b,c,d,M[9],5,568446438);d=U(d,a,b,c,M[14],9,-1019803690);c=U(c,d,a,b,M[3],14,-187363961);b=U(b,c,d,a,M[8],20,1163531501);
a=U(a,b,c,d,M[13],5,-1444681467);d=U(d,a,b,c,M[2],9,-51403784);c=U(c,d,a,b,M[7],14,1735328473);b=U(b,c,d,a,M[12],20,-1926607734);
a=V(a,b,c,d,M[5],4,-378558);d=V(d,a,b,c,M[8],11,-2022574463);c=V(c,d,a,b,M[11],16,1839030562);b=V(b,c,d,a,M[14],23,-35309556);
a=V(a,b,c,d,M[1],4,-1530992060);d=V(d,a,b,c,M[4],11,1272893353);c=V(c,d,a,b,M[7],16,-155497632);b=V(b,c,d,a,M[10],23,-1094730640);
a=V(a,b,c,d,M[13],4,681279174);d=V(d,a,b,c,M[0],11,-358537222);c=V(c,d,a,b,M[3],16,-722521979);b=V(b,c,d,a,M[6],23,76029189);
a=V(a,b,c,d,M[9],4,-640364487);d=V(d,a,b,c,M[12],11,-421815835);c=V(c,d,a,b,M[15],16,530742520);b=V(b,c,d,a,M[2],23,-995338651);
a=W(a,b,c,d,M[0],6,-198630844);d=W(d,a,b,c,M[7],10,1126891415);c=W(c,d,a,b,M[14],15,-1416354905);b=W(b,c,d,a,M[5],21,-57434055);
a=W(a,b,c,d,M[12],6,1700485571);d=W(d,a,b,c,M[3],10,-1894986606);c=W(c,d,a,b,M[10],15,-1051523);b=W(b,c,d,a,M[1],21,-2054922799);
a=W(a,b,c,d,M[8],6,1873313359);d=W(d,a,b,c,M[15],10,-30611744);c=W(c,d,a,b,M[6],15,-1560198380);b=W(b,c,d,a,M[13],21,1309151649);
a=W(a,b,c,d,M[4],6,-145523070);d=W(d,a,b,c,M[11],10,-1120210379);c=W(c,d,a,b,M[2],15,718787259);b=W(b,c,d,a,M[9],21,-343485551);
a=(a+AA)|0;b=(b+BB)|0;c=(c+CC)|0;d=(d+DD)|0;}
function hx(n){var s="";for(var i=0;i<4;i++){var v=(n>>(i*8))&0xff;s+=((v<16?"0":"")+v.toString(16));}return s;}
return hx(a)+hx(b)+hx(c)+hx(d);}

// --- Slug function (MUST match brain/publishers/common.py node_id_to_slug) ---
function nodeIdToSlug(nodeId){
    if(!nodeId) return "unnamed";
    var sanitized = String(nodeId).replace(/[^a-zA-Z0-9._-]+/g, "_");
    sanitized = sanitized.replace(/^_+|_+$/g, "");
    if(!sanitized) return "unnamed";
    if(sanitized.length <= 200 && String(nodeId).length <= 200) return sanitized;
    var suffix = brainMd5(String(nodeId)).substring(0, 8);
    var prefix = sanitized.substring(0, 191).replace(/_+$/, "");
    return prefix + "_" + suffix;
}
"""
