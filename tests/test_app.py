from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from textual.widgets import DataTable, Tree

from lyre.app import HelpScreen, LyreApp
from lyre.models import Conversation, Provider


class StaticStore:
    def __init__(self, conversations: list[Conversation]) -> None:
        self.conversations = conversations

    def scan(self) -> list[Conversation]:
        return self.conversations


def test_app_populates_panels_and_supports_vim_navigation(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.touch()
    conversation = Conversation(
        session_id="33333333-3333-3333-3333-333333333333",
        title="Test the browser",
        cwd=tmp_path,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        transcript_path=transcript,
        first_prompt="Please test the browser.",
        message_count=4,
        git_branch="main",
    )

    async def exercise() -> None:
        app = LyreApp(StaticStore([conversation]))  # type: ignore[arg-type]
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            assert app.current_conversation == conversation
            tree = app.query_one("#conversation-tree", Tree)
            assert tree.has_focus
            assert tree.root.is_expanded
            assert tree.root.children
            assert all(not node.is_expanded for node in tree.root.children)
            assert app.query_one("#recents", DataTable).row_count == 1

            await pilot.press("k")
            await pilot.press("j")
            await pilot.press("tab")
            assert app.query_one("#recents", DataTable).has_focus

            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            assert app.screen is not None

    asyncio.run(exercise())


def test_directory_order_defaults_to_recent_and_toggles_to_name(
    tmp_path: Path,
) -> None:
    older = Conversation(
        session_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        title="Older conversation",
        cwd=Path.home() / "a-older-project",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        transcript_path=tmp_path / "older.jsonl",
    )
    newer = Conversation(
        session_id="zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
        title="Newer conversation",
        cwd=Path.home() / "z-newer-project",
        created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        transcript_path=tmp_path / "newer.jsonl",
    )

    async def exercise() -> None:
        app = LyreApp(StaticStore([newer, older]))  # type: ignore[arg-type]
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            tree = app.query_one("#conversation-tree", Tree)

            assert [node.data.path.name for node in tree.root.children] == [
                "z-newer-project",
                "a-older-project",
            ]
            assert all(not node.is_expanded for node in tree.root.children)
            assert "recent" in tree.root.label.plain

            tree.root.children[0].expand()
            await pilot.press("s")
            await pilot.pause()

            assert [node.data.path.name for node in tree.root.children] == [
                "a-older-project",
                "z-newer-project",
            ]
            assert not tree.root.children[0].is_expanded
            assert tree.root.children[1].is_expanded
            assert "name" in tree.root.label.plain

    asyncio.run(exercise())


def test_tree_renders_provider_specific_conversation_icons(tmp_path: Path) -> None:
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    claude = Conversation(
        session_id="claude-session",
        title="Claude conversation",
        cwd=tmp_path,
        created_at=now,
        updated_at=now,
        transcript_path=tmp_path / "claude.jsonl",
        source=Provider.CLAUDE,
    )
    codex = Conversation(
        session_id="codex-session",
        title="Codex conversation",
        cwd=tmp_path,
        created_at=now,
        updated_at=now,
        transcript_path=tmp_path / "codex.jsonl",
        source=Provider.CODEX,
    )

    async def exercise() -> None:
        app = LyreApp(StaticStore([claude, codex]))
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            tree = app.query_one("#conversation-tree", Tree)
            pending = [tree.root]
            labels: dict[Provider, str] = {}
            while pending:
                node = pending.pop()
                if isinstance(node.data, Conversation):
                    labels[node.data.source] = node.label.plain
                pending.extend(node.children)

            assert labels[Provider.CLAUDE].startswith("🦀")
            assert labels[Provider.CODEX].startswith("🤖")

    asyncio.run(exercise())
