from pathlib import Path

from git import Repo

from app.adapters.github.base import CommitInfo


class LocalGitAdapter:
    """Mock GitHubAdapter: reads real commit history from a local git repo
    (the toy e-commerce app's own repo) instead of hitting api.github.com.
    Same interface as RealGitHubAdapter so swapping is a config change."""

    def __init__(self, repo_path: Path):
        self.repo = Repo(repo_path)

    def list_recent_commits(self, limit: int = 20) -> list[CommitInfo]:
        commits = list(self.repo.iter_commits(self.repo.active_branch, max_count=limit))
        return [self._to_commit_info(c) for c in commits]

    def get_diff(self, sha: str) -> str:
        commit = self.repo.commit(sha)
        parents = commit.parents
        if not parents:
            return self.repo.git.show(sha)
        return self.repo.git.diff(parents[0].hexsha, commit.hexsha)

    def get_commit(self, sha: str) -> CommitInfo:
        return self._to_commit_info(self.repo.commit(sha))

    @staticmethod
    def _to_commit_info(commit) -> CommitInfo:
        return CommitInfo(
            sha=commit.hexsha,
            message=commit.message.strip(),
            author=commit.author.name,
            date=commit.committed_datetime,
            files_changed=list(commit.stats.files.keys()),
        )
