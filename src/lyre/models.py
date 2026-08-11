from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class Provider(StrEnum):
    CLAUDE = "Claude Code"
    CODEX = "Codex"


@dataclass(frozen=True, slots=True)
class Conversation:
    """Provider-neutral metadata for one resumable conversation."""

    session_id: str
    title: str
    cwd: Path
    created_at: datetime
    updated_at: datetime
    transcript_path: Path
    first_prompt: str = ""
    message_count: int = 0
    git_branch: str = ""
    source: Provider = Provider.CLAUDE
    is_archived: bool = False

    @property
    def is_available(self) -> bool:
        return self.cwd.is_dir()

    @property
    def icon(self) -> str:
        return "🤖" if self.source == Provider.CODEX else "🦀"

    @property
    def resume_command(self) -> tuple[str, ...]:
        if self.source == Provider.CODEX:
            return "codex", "resume", self.session_id
        return "claude", "--resume", self.session_id

    @property
    def catalog_key(self) -> tuple[Provider, str]:
        return self.source, self.session_id

