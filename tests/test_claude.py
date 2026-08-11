from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lyre.claude import ClaudeStore, _message_text, _title_from_prompt


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def test_scans_unindexed_transcript_and_prefers_ai_title(tmp_path: Path) -> None:
    working_directory = tmp_path / "worktrees" / "feature-a"
    working_directory.mkdir(parents=True)
    project = tmp_path / ".claude" / "projects" / "-tmp-worktrees-feature-a"
    project.mkdir(parents=True)
    transcript = project / "11111111-1111-1111-1111-111111111111.jsonl"
    write_jsonl(
        transcript,
        [
            {
                "type": "attachment",
                "cwd": str(working_directory),
                "timestamp": "2026-08-01T10:00:00Z",
                "gitBranch": "feature/a",
                "isSidechain": False,
            },
            {
                "type": "user",
                "message": {"role": "user", "content": "Build the first screen."},
                "cwd": str(working_directory),
                "timestamp": "2026-08-01T10:01:00Z",
                "isSidechain": False,
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I will build it."}],
                },
                "timestamp": "2026-08-01T10:02:00Z",
            },
            {
                "type": "ai-title",
                "aiTitle": "Build conversation browser",
            },
        ],
    )
    modified = datetime(2026, 8, 2, 12, tzinfo=timezone.utc).timestamp()
    os.utime(transcript, (modified, modified))

    conversations = ClaudeStore(tmp_path / ".claude").scan()

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.title == "Build conversation browser"
    assert conversation.cwd == working_directory
    assert conversation.first_prompt == "Build the first screen."
    assert conversation.git_branch == "feature/a"
    assert conversation.message_count == 2
    assert conversation.created_at == datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    assert conversation.updated_at == datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


def test_uses_index_metadata_and_ignores_internal_prompt(tmp_path: Path) -> None:
    working_directory = tmp_path / "repo"
    working_directory.mkdir()
    project = tmp_path / ".claude" / "projects" / "-tmp-repo"
    project.mkdir(parents=True)
    session_id = "22222222-2222-2222-2222-222222222222"
    transcript = project / f"{session_id}.jsonl"
    write_jsonl(
        transcript,
        [
            {"type": "ai-title", "aiTitle": "Indexed conversation"},
            {
                "type": "user",
                "cwd": str(working_directory),
                "timestamp": "2026-07-30T09:01:00Z",
                "message": {"role": "user", "content": "Explain this index."},
            },
        ],
    )
    (project / "sessions-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "sessionId": session_id,
                        "fullPath": str(transcript),
                        "firstPrompt": "<local-command-stdout>hidden output",
                        "messageCount": 14,
                        "created": "2026-07-30T09:00:00Z",
                        "modified": "2026-07-30T11:30:00Z",
                        "gitBranch": "main",
                        "projectPath": str(working_directory),
                        "isSidechain": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    conversation = ClaudeStore(tmp_path / ".claude").scan()[0]

    assert conversation.title == "Indexed conversation"
    assert conversation.first_prompt == "Explain this index."
    assert conversation.message_count == 14
    assert conversation.updated_at == datetime(
        2026, 7, 30, 11, 30, tzinfo=timezone.utc
    )


def test_skips_sidechains_and_records_without_a_working_directory(
    tmp_path: Path,
) -> None:
    project = tmp_path / ".claude" / "projects" / "-tmp-project"
    project.mkdir(parents=True)
    write_jsonl(
        project / "sidechain.jsonl",
        [
            {
                "type": "user",
                "cwd": "/tmp/project",
                "isSidechain": True,
                "timestamp": "2026-08-01T00:00:00Z",
                "message": {"role": "user", "content": "Subtask"},
            }
        ],
    )
    write_jsonl(
        project / "incomplete.jsonl",
        [{"type": "last-prompt", "sessionId": "incomplete"}],
    )

    assert ClaudeStore(tmp_path / ".claude").scan() == []


def test_extracts_only_text_blocks_from_structured_user_message() -> None:
    message = {
        "content": [
            {"type": "tool_result", "content": "private tool output"},
            {"type": "text", "text": "  Please\nreview  this. "},
        ]
    }

    assert _message_text(message) == "Please review this."


def test_prompt_title_is_short_and_human_readable() -> None:
    prompt = "A" * 90

    title = _title_from_prompt(prompt)

    assert len(title) == 72
    assert title.endswith("…")


def test_cleaned_prompt_drops_terminal_control_characters(tmp_path: Path) -> None:
    working_directory = tmp_path / "repo"
    working_directory.mkdir()
    project = tmp_path / ".claude" / "projects" / "-tmp-repo"
    project.mkdir(parents=True)
    write_jsonl(
        project / "controls.jsonl",
        [
            {
                "type": "user",
                "cwd": str(working_directory),
                "timestamp": "2026-08-01T00:00:00Z",
                "message": {"role": "user", "content": "hello\x1b[31m world"},
            }
        ],
    )

    conversation = ClaudeStore(tmp_path / ".claude").scan()[0]

    assert "\x1b" not in conversation.first_prompt
    assert conversation.first_prompt == "hello world"
