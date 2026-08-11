from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lyre.catalog import CompositeStore
from lyre.models import Conversation, Provider


class StaticStore:
    def __init__(self, conversations: list[Conversation]) -> None:
        self.conversations = conversations

    def scan(self) -> list[Conversation]:
        return self.conversations


def test_composite_store_merges_providers_by_recency() -> None:
    claude = Conversation(
        session_id="shared-id",
        title="Claude",
        cwd=Path("/claude"),
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        transcript_path=Path("/claude.jsonl"),
        source=Provider.CLAUDE,
    )
    codex = Conversation(
        session_id="shared-id",
        title="Codex",
        cwd=Path("/codex"),
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        transcript_path=Path("/codex.jsonl"),
        source=Provider.CODEX,
    )

    conversations = CompositeStore((StaticStore([claude]), StaticStore([codex]))).scan()

    assert conversations == [codex, claude]

