"""Filesystem layout helper - enforces spec section 3.1 directory tree."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path

    def repo_dir(self, group: str, repo: str) -> Path:
        return self.root / "repos" / group / repo

    def repo_mirror(self, group: str, repo: str) -> Path:
        return self.repo_dir(group, repo) / "mirror.git"

    def repo_worktree(self, group: str, repo: str) -> Path:
        return self.repo_dir(group, repo) / "worktree"

    def repo_graph(self, group: str, repo: str) -> Path:
        return self.root / "graphs" / group / repo / "graph.json"

    def group_master_graph(self, group: str) -> Path:
        return self.root / "graphs" / group / "_master" / "graph.json"

    def super_master_graph(self) -> Path:
        return self.root / "graphs" / "_super" / "graph.json"

    def vault_group(self, group: str) -> Path:
        return self.root / "vaults" / group

    def vault_obsidian(self, group: str) -> Path:
        return self.vault_group(group) / "obsidian"

    def vault_web(self, group: str) -> Path:
        return self.vault_group(group) / "web"

    def vault_web_wiki(self, group: str) -> Path:
        return self.vault_group(group) / "web-wiki"

    def poll_state_file(self) -> Path:
        return self.root / "poll_state.json"

    def vault_index(self, group: str) -> Path:
        return self.vault_group(group) / "index"

    def super_index(self) -> Path:
        """Path to the cross-group super index directory."""
        return self.root / "vaults" / "_super" / "index"

    def graph_history(self, group: str, repo: str) -> Path:
        return self.root / "graphs_history" / group / repo

    def backups(self) -> Path:
        return self.root / "backups"

    def ensure(self, group: str, repo: str | None = None) -> None:
        dirs = [
            self.vault_obsidian(group),
            self.vault_web(group),
            self.vault_index(group),
            self.group_master_graph(group).parent,
            self.backups(),
        ]
        if repo:
            dirs += [
                self.repo_dir(group, repo),
                self.repo_graph(group, repo).parent,
                self.graph_history(group, repo),
            ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
