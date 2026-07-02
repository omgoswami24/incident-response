from functools import lru_cache

from app.adapters.github.base import GitHubAdapter
from app.adapters.github.local_git_adapter import LocalGitAdapter
from app.adapters.slack.base import SlackAdapter
from app.adapters.slack.mock_slack_adapter import MockSlackAdapter
from app.config import settings


@lru_cache
def get_github_adapter() -> GitHubAdapter:
    if settings.github_adapter == "real":
        from app.adapters.github.real_github_adapter import RealGitHubAdapter
        import os

        return RealGitHubAdapter(
            owner=os.environ["GITHUB_OWNER"],
            repo=os.environ["GITHUB_REPO"],
            token=os.environ["GITHUB_TOKEN"],
        )
    return LocalGitAdapter(settings.ecommerce_repo_path)


@lru_cache
def get_slack_adapter() -> SlackAdapter:
    if settings.slack_adapter == "real":
        from app.adapters.slack.real_slack_adapter import RealSlackAdapter
        import os

        return RealSlackAdapter(bot_token=os.environ["SLACK_BOT_TOKEN"])
    return MockSlackAdapter()
