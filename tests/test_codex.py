from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lyre.codex import CodexStore
from lyre.models import Provider


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def make_rollout(
    codex_home: Path,
    session_id: str,
    cwd: Path,
    *,
    source: object = "cli",
    prompt: str = "Build Codex support.",
) -> Path:
    rollout = (
        codex_home
        / "sessions"
        / "2026"
        / "08"
        / "09"
        / f"rollout-2026-08-09T12-00-00-{session_id}.jsonl"
    )
    write_jsonl(
        rollout,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-08-09T12:00:00Z",
                    "cwd": str(cwd),
                    "source": source,
                    "originator": "codex-tui",
                    "git": {"branch": "feature/codex"},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Internal context"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done"}],
                },
            },
        ],
    )
    return rollout


def create_thread_index(codex_home: Path, session_id: str) -> None:
    created_at_ms = int(
        datetime(2026, 8, 9, 12, tzinfo=timezone.utc).timestamp() * 1_000
    )
    updated_at_ms = int(
        datetime(2026, 8, 9, 13, tzinfo=timezone.utc).timestamp() * 1_000
    )
    database = sqlite3.connect(codex_home / "state_5.sqlite")
    database.execute(
        """CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            name TEXT,
            first_user_message TEXT NOT NULL,
            git_branch TEXT,
            created_at_ms INTEGER,
            updated_at_ms INTEGER,
            archived INTEGER,
            thread_source TEXT,
            source TEXT
        )"""
    )
    database.execute(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            "Generated title",
            "Named Codex thread",
            "Build Codex support from the index.",
            "indexed-branch",
            created_at_ms,
            updated_at_ms,
            0,
            "user",
            "cli",
        ),
    )
    database.commit()
    database.close()


def test_scans_current_codex_rollout_and_thread_index(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    session_id = "019fe73f-bad6-7a71-bafb-13497a899375"
    rollout = make_rollout(codex_home, session_id, cwd)
    create_thread_index(codex_home, session_id)
    file_time = datetime(2026, 8, 9, 12, 30, tzinfo=timezone.utc).timestamp()
    os.utime(rollout, (file_time, file_time))

    conversations = CodexStore(codex_home).scan()

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.session_id == session_id
    assert conversation.title == "Named Codex thread"
    assert conversation.first_prompt == "Build Codex support from the index."
    assert conversation.cwd == cwd
    assert conversation.message_count == 2
    assert conversation.git_branch == "indexed-branch"
    assert conversation.source == Provider.CODEX
    assert conversation.icon == "🤖"
    assert conversation.resume_command == ("codex", "resume", session_id)
    assert conversation.created_at == datetime(
        2026, 8, 9, 12, tzinfo=timezone.utc
    )
    assert conversation.updated_at == datetime(
        2026, 8, 9, 13, tzinfo=timezone.utc
    )


def test_falls_back_to_rollout_prompt_and_excludes_subagents(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    root_id = "11111111-1111-1111-1111-111111111111"
    make_rollout(
        codex_home,
        root_id,
        cwd,
        prompt="Investigate the failing integration. Then fix it.",
    )
    make_rollout(
        codex_home,
        "22222222-2222-2222-2222-222222222222",
        cwd,
        source={"subagent": {"thread_spawn": {"parent_thread_id": root_id}}},
        prompt="Subtask that should not be listed",
    )

    conversations = CodexStore(codex_home).scan()

    assert len(conversations) == 1
    assert conversations[0].session_id == root_id
    assert conversations[0].title == "Investigate the failing integration."
    assert conversations[0].first_prompt == (
        "Investigate the failing integration. Then fix it."
    )


def test_skips_legacy_rollout_without_working_directory(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    rollout = codex_home / "sessions" / "2025" / "10" / "03" / "legacy.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "timestamp": "2025-10-03T07:48:15Z",
                "instructions": "Legacy format has no cwd.",
            }
        ],
    )

    assert CodexStore(codex_home).scan() == []
