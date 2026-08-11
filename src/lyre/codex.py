from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyre.models import Conversation, Provider
from lyre.text import clean_text, title_from_prompt

_USER_ROLE = re.compile(rb'"role"\s*:\s*"user"')
_ASSISTANT_ROLE = re.compile(rb'"role"\s*:\s*"assistant"')
_RESPONSE_ITEM = re.compile(rb'"type"\s*:\s*"response_item"')
_SESSION_ID = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_INTERNAL_USER_PREFIXES = ("<environment_context>", "<permissions instructions>")


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


@dataclass(frozen=True, slots=True)
class _ThreadMetadata:
    title: str = ""
    name: str = ""
    first_prompt: str = ""
    git_branch: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False
    is_subagent: bool = False


class CodexStore:
    """Read top-level Codex conversations without modifying Codex state."""

    def __init__(self, codex_home: Path | None = None) -> None:
        self.codex_home = (codex_home or default_codex_home()).expanduser()
        self.sessions_dir = self.codex_home / "sessions"
        self.state_path = self.codex_home / "state_5.sqlite"

    def scan(self) -> list[Conversation]:
        if not self.sessions_dir.is_dir():
            return []

        thread_index = self._read_thread_index()
        conversations: list[Conversation] = []
        for transcript in self.sessions_dir.rglob("*.jsonl"):
            try:
                conversation = self._read_rollout(
                    transcript, thread_index.get(_session_id_from_filename(transcript))
                )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                # Active rollouts can end with a partially written JSON line.
                continue
            if conversation is not None:
                conversations.append(conversation)
        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    def _read_rollout(
        self, transcript: Path, indexed: _ThreadMetadata | None
    ) -> Conversation | None:
        stat = transcript.stat()
        with transcript.open("rb") as lines:
            first_line = lines.readline()
            if not first_line:
                return None
            first_record = json.loads(first_line)
            if not isinstance(first_record, dict) or first_record.get("type") != "session_meta":
                # Legacy Codex rollouts do not record a cwd, so Lyre cannot place them.
                return None
            payload = first_record.get("payload")
            if not isinstance(payload, dict):
                return None

            session_id = str(payload.get("id") or _session_id_from_filename(transcript))
            source = payload.get("source")
            if _is_subagent_source(source) or (indexed and indexed.is_subagent):
                return None
            cwd_value = payload.get("cwd")
            if not isinstance(cwd_value, str) or not cwd_value:
                return None

            first_prompt = indexed.first_prompt if indexed else ""
            message_count = 0
            for raw_line in lines:
                if not _RESPONSE_ITEM.search(raw_line):
                    continue
                is_user = _USER_ROLE.search(raw_line) is not None
                is_assistant = _ASSISTANT_ROLE.search(raw_line) is not None
                if not is_user and not is_assistant:
                    continue
                try:
                    record = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError):
                    continue
                message = record.get("payload") if isinstance(record, dict) else None
                if not isinstance(message, dict) or message.get("type") != "message":
                    continue
                role = message.get("role")
                if role not in ("user", "assistant"):
                    continue
                message_count += 1
                if role == "user" and not first_prompt:
                    candidate = _message_text(message)
                    if candidate and not candidate.startswith(_INTERNAL_USER_PREFIXES):
                        first_prompt = candidate

        created_at = _timestamp(payload.get("timestamp"))
        filesystem_updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if indexed and indexed.created_at:
            created_at = indexed.created_at
        updated_at = filesystem_updated
        if indexed and indexed.updated_at and indexed.updated_at > updated_at:
            updated_at = indexed.updated_at

        first_prompt = clean_text(first_prompt)
        indexed_title = (indexed.name or indexed.title) if indexed else ""
        title = title_from_prompt(clean_text(indexed_title, limit=500))
        title = title or title_from_prompt(first_prompt) or f"Untitled {session_id[:8]}"
        git = payload.get("git")
        payload_branch = git.get("branch") if isinstance(git, dict) else ""
        git_branch = indexed.git_branch if indexed and indexed.git_branch else payload_branch

        return Conversation(
            session_id=session_id,
            title=title,
            cwd=Path(cwd_value).expanduser(),
            created_at=created_at
            or datetime.fromtimestamp(stat.st_ctime, timezone.utc),
            updated_at=updated_at,
            transcript_path=transcript,
            first_prompt=first_prompt,
            message_count=message_count,
            git_branch=clean_text(git_branch, limit=200),
            source=Provider.CODEX,
            is_archived=indexed.archived if indexed else False,
        )

    def _read_thread_index(self) -> dict[str, _ThreadMetadata]:
        if not self.state_path.is_file():
            return {}
        try:
            connection = sqlite3.connect(
                f"{self.state_path.resolve().as_uri()}?mode=ro", uri=True
            )
        except sqlite3.Error:
            return {}
        connection.row_factory = sqlite3.Row
        try:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(threads)").fetchall()
            }
            if not {"id", "title"}.issubset(columns):
                return {}
            select = ", ".join(
                _select_column(columns, name, default)
                for name, default in (
                    ("id", "''"),
                    ("title", "''"),
                    ("name", "''"),
                    ("first_user_message", "''"),
                    ("git_branch", "''"),
                    ("created_at_ms", "NULL"),
                    ("created_at", "NULL"),
                    ("updated_at_ms", "NULL"),
                    ("updated_at", "NULL"),
                    ("archived", "0"),
                    ("thread_source", "''"),
                    ("source", "''"),
                )
            )
            rows = connection.execute(f"SELECT {select} FROM threads").fetchall()
        except sqlite3.Error:
            return {}
        finally:
            connection.close()

        index: dict[str, _ThreadMetadata] = {}
        for row in rows:
            session_id = str(row["id"] or "")
            if not session_id:
                continue
            index[session_id] = _ThreadMetadata(
                title=clean_text(row["title"], limit=500),
                name=clean_text(row["name"], limit=500),
                first_prompt=clean_text(row["first_user_message"]),
                git_branch=clean_text(row["git_branch"], limit=200),
                created_at=_epoch(row["created_at_ms"] or row["created_at"]),
                updated_at=_epoch(row["updated_at_ms"] or row["updated_at"]),
                archived=bool(row["archived"]),
                is_subagent=(
                    row["thread_source"] == "subagent"
                    or "subagent" in str(row["source"])
                ),
            )
        return index


def _select_column(columns: set[str], name: str, default: str) -> str:
    return name if name in columns else f"{default} AS {name}"


def _session_id_from_filename(path: Path) -> str:
    match = _SESSION_ID.search(path.stem)
    return match.group(1) if match else path.stem


def _is_subagent_source(source: Any) -> bool:
    return isinstance(source, dict) and "subagent" in source


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "input_text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            text_parts.append(text)
    return clean_text(" ".join(text_parts))


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _epoch(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    seconds = value / 1000 if value > 10_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
