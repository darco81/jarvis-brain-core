from pathlib import Path

from brain.core.paths import DataPaths


def test_paths_layout(tmp_path: Path) -> None:
    p = DataPaths(root=tmp_path)
    assert p.repo_worktree("example-group", "example-front-a") == tmp_path / "repos/example-group/example-front-a/worktree"
    assert p.repo_mirror("example-group", "example-front-a") == tmp_path / "repos/example-group/example-front-a/mirror.git"
    assert p.repo_graph("example-group", "example-front-a") == tmp_path / "graphs/example-group/example-front-a/graph.json"
    assert p.group_master_graph("example-group") == tmp_path / "graphs/example-group/_master/graph.json"
    assert p.super_master_graph() == tmp_path / "graphs/_super/graph.json"
    assert p.vault_obsidian("example-group") == tmp_path / "vaults/example-group/obsidian"
    assert p.vault_web("example-group") == tmp_path / "vaults/example-group/web"
    assert p.vault_index("example-group") == tmp_path / "vaults/example-group/index"
    assert p.repo_dir("example-group", "example-front-a") == tmp_path / "repos/example-group/example-front-a"
    assert p.vault_group("example-group") == tmp_path / "vaults/example-group"
    assert p.graph_history("example-group", "example-front-a") == tmp_path / "graphs_history/example-group/example-front-a"
    assert p.backups() == tmp_path / "backups"


def test_paths_ensure_creates(tmp_path: Path) -> None:
    p = DataPaths(root=tmp_path)
    p.ensure("example-group", "example-front-a")
    assert p.repo_worktree("example-group", "example-front-a").parent.exists()
    assert p.repo_graph("example-group", "example-front-a").parent.exists()
    assert p.vault_obsidian("example-group").exists()


def test_paths_ensure_group_only_skips_repo_dirs(tmp_path: Path) -> None:
    p = DataPaths(root=tmp_path)
    p.ensure("example-group")  # no repo
    # Group-level vaults exist
    assert p.vault_obsidian("example-group").exists()
    assert p.vault_web("example-group").exists()
    assert p.vault_index("example-group").exists()
    assert p.backups().exists()
    # Repo-level dirs NOT created
    assert not p.repo_dir("example-group", "example-front-a").exists()
    assert not p.repo_graph("example-group", "example-front-a").parent.exists()
    assert not p.graph_history("example-group", "example-front-a").exists()


def test_data_paths_vault_web_wiki(tmp_path: Path) -> None:
    paths = DataPaths(root=tmp_path)
    expected = tmp_path / "vaults" / "example-group" / "web-wiki"
    assert paths.vault_web_wiki("example-group") == expected


def test_data_paths_poll_state_file(tmp_path: Path) -> None:
    from brain.core.paths import DataPaths

    paths = DataPaths(root=tmp_path)
    assert paths.poll_state_file() == tmp_path / "poll_state.json"
