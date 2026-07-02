from typing import Protocol

from pydantic import BaseModel


class SlackPostResult(BaseModel):
    ok: bool
    channel: str
    ts: str
    blocks: list[dict]


class SlackAdapter(Protocol):
    def post_message(
        self, channel: str, blocks: list[dict], text_fallback: str
    ) -> SlackPostResult: ...
