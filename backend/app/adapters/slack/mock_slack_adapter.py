import time

from app.adapters.slack.base import SlackPostResult


class MockSlackAdapter:
    """Mock SlackAdapter: no network call, just returns the Block Kit
    payload as if it had been posted, for the frontend to render as a fake
    Slack message card."""

    def post_message(
        self, channel: str, blocks: list[dict], text_fallback: str
    ) -> SlackPostResult:
        return SlackPostResult(ok=True, channel=channel, ts=f"{time.time():.6f}", blocks=blocks)
