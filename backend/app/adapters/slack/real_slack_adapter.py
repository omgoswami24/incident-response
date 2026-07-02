import httpx

from app.adapters.slack.base import SlackPostResult


class RealSlackAdapter:
    """Live SlackAdapter against slack.com/api/chat.postMessage. Same
    interface as MockSlackAdapter — proves the mock/real swap is a config
    change. Not wired by default; set SLACK_ADAPTER=real and provide a bot
    token to use it."""

    def __init__(self, bot_token: str):
        self._client = httpx.Client(
            base_url="https://slack.com/api",
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=10.0,
        )

    def post_message(
        self, channel: str, blocks: list[dict], text_fallback: str
    ) -> SlackPostResult:
        resp = self._client.post(
            "/chat.postMessage",
            json={"channel": channel, "blocks": blocks, "text": text_fallback},
        )
        resp.raise_for_status()
        data = resp.json()
        return SlackPostResult(
            ok=data.get("ok", False),
            channel=data.get("channel", channel),
            ts=data.get("ts", ""),
            blocks=blocks,
        )
