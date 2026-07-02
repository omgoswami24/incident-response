from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str
    date: datetime
    files_changed: list[str]


class GitHubAdapter(Protocol):
    def list_recent_commits(self, limit: int = 20) -> list[CommitInfo]: ...

    def get_diff(self, sha: str) -> str: ...

    def get_commit(self, sha: str) -> CommitInfo: ...
