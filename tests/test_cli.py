from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lyre.cli import handoff
from lyre.models import Conversation, Provider


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (Provider.CLAUDE, ["/resolved/claude", "--resume", "session-id"]),
        (Provider.CODEX, ["/resolved/codex", "resume", "session-id"]),
    ],
)
def test_handoff_changes_directory_and_replaces_lyre(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: Provider,
    expected: list[str],
) -> None:
    conversation = Conversation(
        session_id="session-id",
        title="Selected conversation",
        cwd=tmp_path,
        created_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        transcript_path=tmp_path / "session.jsonl",
        source=provider,
    )
    changed_to: list[Path] = []
    executed: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        "lyre.cli.shutil.which", lambda program: f"/resolved/{program}"
    )
    monkeypatch.setattr("lyre.cli.os.chdir", changed_to.append)
    monkeypatch.setattr(
        "lyre.cli.os.execv", lambda executable, args: executed.append((executable, args))
    )

    handoff(conversation)

    assert changed_to == [tmp_path]
    assert executed == [(expected[0], expected)]

