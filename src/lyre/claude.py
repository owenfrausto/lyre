from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyre.models import Conversation, Provider
from lyre.text import clean_text as _clean_text
from lyre.text import title_from_prompt as _title_from_prompt

_ASSISTANT_ROLE = re.compile(rb'"role"\s*:\s*"assistant"')
_USER_TYPE = re.compile(rb'"type"\s*:\s*"user"')
_INTERNAL_PROMPT_PREFIXES = ("<command-", "<local-command-", "<system-reminder>")


def default_claude_home() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


class ClaudeStore:
    """Read conversation metadata from Claude Code's local project store."""

    def __init__(self, claude_home: Path | None = None) -> None:
        self.claude_home = (claude_home or default_claude_home()).expanduser()
        self.projects_dir = self.claude_home / "projects"

    def scan(self) -> list[Conversation]:
        if not self.projects_dir.is_dir():
            return []

        conversations: list[Conversation] = []
        for project_dir in sorted(self.projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            indexed = self._read_index(project_dir / "sessions-index.json")
            for transcript in project_dir.glob("*.jsonl"):
                try:
                    conversation = self._read_transcript(
                        transcript, indexed.get(transcript.stem)
                    )
                except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                    # A partially written transcript should not make the browser unusable.
                    continue
                if conversation is not None:
                    conversations.append(conversation)

        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    @staticmethod
    def _read_index(path: Path) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        return {
            str(entry["sessionId"]): entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("sessionId")
        }

    def _read_transcript(
        self, transcript: Path, indexed: dict[str, Any] | None
    ) -> Conversation | None:
        if indexed and indexed.get("isSidechain"):
            return None

        stat = transcript.stat()
        session_id = transcript.stem
        cwd = _path(indexed.get("projectPath")) if indexed else None
        created_at = _timestamp(indexed.get("created")) if indexed else None
        updated_at = _timestamp(indexed.get("modified")) if indexed else None
        first_prompt = _clean_text(indexed.get("firstPrompt")) if indexed else ""
        if _is_internal_prompt(first_prompt):
            first_prompt = ""
        git_branch = str(indexed.get("gitBranch") or "") if indexed else ""
        indexed_count = indexed.get("messageCount") if indexed else None
        message_count = indexed_count if isinstance(indexed_count, int) else 0
        ai_title = ""
        is_sidechain = False

        # Indexes are not present for every Claude version. The fast path below
        # only decodes records that can add metadata, while still counting message
        # lines. That keeps startup reasonable even for very large transcripts.
        needs_record_metadata = not all((cwd, created_at, first_prompt))
        with transcript.open("rb") as lines:
            for raw_line in lines:
                if indexed_count is None:
                    if _ASSISTANT_ROLE.search(raw_line) or _USER_TYPE.search(raw_line):
                        message_count += 1

                is_title_record = b'"type":"ai-title"' in raw_line
                might_supply_metadata = needs_record_metadata and (
                    b'"cwd"' in raw_line or b'"type":"user"' in raw_line
                )
                if not is_title_record and not might_supply_metadata:
                    continue

                try:
                    record = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue

                if record.get("isSidechain") is True:
                    is_sidechain = True
                if cwd is None:
                    cwd = _path(record.get("cwd"))
                if created_at is None:
                    created_at = _timestamp(record.get("timestamp"))
                if not git_branch and isinstance(record.get("gitBranch"), str):
                    git_branch = record["gitBranch"]
                if record.get("type") == "ai-title":
                    ai_title = _clean_text(record.get("aiTitle"))
                elif record.get("type") == "user" and not first_prompt:
                    candidate = _message_text(record.get("message"))
                    if candidate and not _is_internal_prompt(candidate):
                        first_prompt = candidate

                needs_record_metadata = not all((cwd, created_at, first_prompt))

        if is_sidechain or cwd is None:
            return None

        filesystem_updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        created_at = created_at or datetime.fromtimestamp(stat.st_ctime, timezone.utc)
        updated_at = updated_at or filesystem_updated
        title = ai_title or _title_from_prompt(first_prompt) or f"Untitled {session_id[:8]}"
        return Conversation(
            session_id=session_id,
            title=title,
            cwd=cwd,
            created_at=created_at,
            updated_at=updated_at,
            transcript_path=transcript,
            first_prompt=first_prompt,
            message_count=message_count,
            git_branch=git_branch,
            source=Provider.CLAUDE,
        )


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return _clean_text(content)
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return _clean_text(" ".join(text_parts))


def _is_internal_prompt(prompt: str) -> bool:
    return prompt.startswith(_INTERNAL_PROMPT_PREFIXES)


def _path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def group_by_path(
    conversations: Iterable[Conversation],
) -> dict[Path, list[Conversation]]:
    grouped: dict[Path, list[Conversation]] = {}
    for conversation in conversations:
        grouped.setdefault(conversation.cwd, []).append(conversation)
    for items in grouped.values():
        items.sort(key=lambda item: item.updated_at, reverse=True)
    return grouped
