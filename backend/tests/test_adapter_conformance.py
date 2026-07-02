"""Runs the same behavioral assertions against every GitHubAdapter/SlackAdapter
implementation, proving the mock <-> real swap is safe. Real adapters are
skipped unless credentials are present in the environment."""

import os
from pathlib import Path

import pytest
from git import Actor, Repo

from app.adapters.github.local_git_adapter import LocalGitAdapter
from app.adapters.slack.mock_slack_adapter import MockSlackAdapter


def assert_github_adapter_conforms(adapter) -> None:
    commits = adapter.list_recent_commits(limit=5)
    assert len(commits) > 0
    first = commits[0]
    assert first.sha
    assert first.message

    diff = adapter.get_diff(first.sha)
    assert isinstance(diff, str)

    fetched = adapter.get_commit(first.sha)
    assert fetched.sha == first.sha


def assert_slack_adapter_conforms(adapter) -> None:
    result = adapter.post_message(
        "#test-channel",
        [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}],
        "hello",
    )
    assert result.ok
    assert result.channel == "#test-channel"
    assert result.ts


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = Repo.init(tmp_path)
    actor = Actor("Test", "test@example.com")
    (tmp_path / "a.txt").write_text("v1")
    repo.index.add(["a.txt"])
    repo.index.commit("init", author=actor, committer=actor)
    (tmp_path / "a.txt").write_text("v2")
    repo.index.add(["a.txt"])
    repo.index.commit("update a", author=actor, committer=actor)
    return tmp_path


def test_local_git_adapter_conforms(tiny_repo):
    assert_github_adapter_conforms(LocalGitAdapter(tiny_repo))


def test_mock_slack_adapter_conforms():
    assert_slack_adapter_conforms(MockSlackAdapter())


@pytest.mark.skipif(
    not all(os.environ.get(k) for k in ("GITHUB_OWNER", "GITHUB_REPO", "GITHUB_TOKEN")),
    reason="GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN not set",
)
def test_real_github_adapter_conforms():
    from app.adapters.github.real_github_adapter import RealGitHubAdapter

    adapter = RealGitHubAdapter(
        owner=os.environ["GITHUB_OWNER"],
        repo=os.environ["GITHUB_REPO"],
        token=os.environ["GITHUB_TOKEN"],
    )
    assert_github_adapter_conforms(adapter)


@pytest.mark.skipif(
    not os.environ.get("SLACK_BOT_TOKEN"), reason="SLACK_BOT_TOKEN not set"
)
def test_real_slack_adapter_conforms():
    from app.adapters.slack.real_slack_adapter import RealSlackAdapter

    adapter = RealSlackAdapter(bot_token=os.environ["SLACK_BOT_TOKEN"])
    assert_slack_adapter_conforms(adapter)
