import httpx

from app.adapters.github.base import CommitInfo


class RealGitHubAdapter:
    """Live GitHubAdapter against api.github.com. Same interface as
    LocalGitAdapter — proves the mock/real swap is a config change, not a
    rewrite. Not wired by default; set GITHUB_ADAPTER=real and provide a
    token to use it."""

    BASE_URL = "https://api.github.com"

    def __init__(self, owner: str, repo: str, token: str):
        self.owner = owner
        self.repo = repo
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10.0,
        )

    def list_recent_commits(self, limit: int = 20) -> list[CommitInfo]:
        resp = self._client.get(
            f"/repos/{self.owner}/{self.repo}/commits", params={"per_page": limit}
        )
        resp.raise_for_status()
        return [self._to_commit_info(c) for c in resp.json()]

    def get_diff(self, sha: str) -> str:
        resp = self._client.get(
            f"/repos/{self.owner}/{self.repo}/commits/{sha}",
            headers={"Accept": "application/vnd.github.diff"},
        )
        resp.raise_for_status()
        return resp.text

    def get_commit(self, sha: str) -> CommitInfo:
        resp = self._client.get(f"/repos/{self.owner}/{self.repo}/commits/{sha}")
        resp.raise_for_status()
        return self._to_commit_info(resp.json())

    @staticmethod
    def _to_commit_info(data: dict) -> CommitInfo:
        return CommitInfo(
            sha=data["sha"],
            message=data["commit"]["message"],
            author=data["commit"]["author"]["name"],
            date=data["commit"]["author"]["date"],
            files_changed=[f["filename"] for f in data.get("files", [])],
        )
