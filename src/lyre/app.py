from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static, Tree

from lyre.catalog import ConversationStore
from lyre.claude import group_by_path
from lyre.models import Conversation


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    path: Path


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("?", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
        background: #02080ddd;
    }

    #help-dialog {
        width: 64;
        height: 29;
        border: solid #3f8fe8;
        background: #08141f;
        color: #c8d0da;
        padding: 1 3;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            """[bold #62a8ff]LYRE KEYBOARD MAP[/]\n
[bold #38d6c4]Navigation[/]\n
  [bold]j / k[/]       move down / up\n
  [bold]h / l[/]       collapse / expand directory\n
  [bold]g / G[/]       first / last item\n
  [bold]Tab[/]         switch tree / recent conversations\n
  [bold #38d6c4]Actions[/]\n
  [bold]Enter / o[/]   resume selected conversation\n
  [bold]s[/]           toggle directory order: recent / name\n
  [bold]r[/]           rescan provider conversation stores\n
  [bold]?[/]           show this help\n
  [bold]q[/]           quit Lyre\n
[dim]Opening exits Lyre and hands the terminal to the provider in the
conversation's original working directory.[/]""",
            id="help-dialog",
            markup=True,
        )

    def action_dismiss(self) -> None:
        self.dismiss()


class LyreApp(App[Conversation | None]):
    """Browse agentic conversations by their working directory."""

    TITLE = "Lyre"
    SUB_TITLE = ""

    CSS = """
    Screen {
        background: #030c14;
        color: #c8d0da;
        padding: 0 1;
    }

    #masthead {
        height: 3;
        border: solid #4d5660;
        background: #06111b;
        content-align: center middle;
        color: #d6dbe1;
    }

    #top {
        height: 1fr;
        min-height: 14;
        margin-top: 1;
    }

    #conversation-tree {
        width: 3fr;
        height: 100%;
        margin-right: 1;
        border: solid #4d5660;
        background: #06111b;
        padding: 0 1;
    }

    #side {
        width: 2fr;
        height: 100%;
    }

    #details, #actions, #preview {
        border: solid #4d5660;
        background: #06111b;
        padding: 0 2;
    }

    #details {
        height: 3fr;
        min-height: 9;
        margin-bottom: 1;
    }

    #actions {
        height: 2fr;
        min-height: 8;
    }

    #recents {
        height: 12;
        margin-top: 1;
        border: solid #4d5660;
        background: #06111b;
    }

    #preview {
        height: 7;
        min-height: 5;
        margin-top: 1;
    }

    #footer {
        height: 3;
        margin-top: 1;
        border: solid #4d5660;
        background: #06111b;
        content-align: center middle;
        color: #38d6c4;
    }

    #conversation-tree:focus, #recents:focus {
        border: solid #3f8fe8;
    }

    Tree > .tree--cursor, DataTable > .datatable--cursor {
        background: #174b7f;
        color: #ffffff;
    }

    DataTable > .datatable--header {
        background: #0a1a29;
        color: #62a8ff;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False, priority=True),
        Binding("j", "move_down", "Down", show=False, priority=True),
        Binding("k", "move_up", "Up", show=False, priority=True),
        Binding("h", "collapse", "Collapse", show=False, priority=True),
        Binding("l", "expand", "Expand", show=False, priority=True),
        Binding("g", "first", "First", show=False, priority=True),
        Binding("shift+g", "last", "Last", show=False, priority=True),
        Binding("tab", "next_panel", "Next panel", show=False, priority=True),
        Binding("enter", "activate", "Open", show=False, priority=True),
        Binding("o", "open", "Open", show=False, priority=True),
        Binding("s", "sort_directories", "Sort directories", show=False, priority=True),
        Binding("r", "refresh", "Refresh", show=False, priority=True),
        Binding("?", "help", "Help", show=False, priority=True),
    ]

    def __init__(self, store: ConversationStore) -> None:
        super().__init__()
        self.store = store
        self.conversations: list[Conversation] = []
        self.recent_conversations: list[Conversation] = []
        self.current_conversation: Conversation | None = None
        self.directory_sort = "recent"

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #62a8ff]Lyre[/]  [#e5a843]🪉[/]                     "
            "[#38d6c4]? Help[/]",
            id="masthead",
            markup=True,
        )
        with Horizontal(id="top"):
            yield Tree[DirectoryEntry | Conversation]("⌂  ~", id="conversation-tree")
            with Vertical(id="side"):
                yield Static(self._empty_details(), id="details")
                yield Static(self._actions(), id="actions")
        yield DataTable(id="recents", cursor_type="row", zebra_stripes=True)
        yield Static(self._empty_preview(), id="preview")
        yield Static(self._footer(), id="footer")

    def on_mount(self) -> None:
        table = self.query_one("#recents", DataTable)
        table.add_column("#", width=3)
        table.add_column("Conversation", width=38)
        table.add_column("Location", width=32)
        table.add_column("Updated", width=10)
        table.add_column("State", width=8)
        table.fixed_columns = 1
        tree = self.query_one("#conversation-tree", Tree)
        # Lyre owns expansion through h/l and Enter; merely moving the cursor
        # must not open directories.
        tree.auto_expand = False
        tree.root.expand()
        tree.focus()
        self._set_loading(True)
        self.load_conversations()

    @work(thread=True, exclusive=True, group="conversation-scan")
    def load_conversations(self) -> None:
        try:
            conversations = self.store.scan()
        except Exception as error:  # Keep unexpected provider changes visible.
            self.call_from_thread(self._load_failed, error)
            return
        self.call_from_thread(self._populate, conversations)

    def _populate(self, conversations: list[Conversation]) -> None:
        self.conversations = conversations
        self.recent_conversations = conversations[:10]
        selected_node = self._populate_tree()
        self._populate_recents()
        self._set_loading(False)

        if conversations:
            self._select(conversations[0])
            if selected_node is not None:
                tree = self.query_one("#conversation-tree", Tree)
                self.call_after_refresh(tree.select_node, selected_node)
        else:
            self.query_one("#details", Static).update(self._empty_details(no_results=True))
            self.query_one("#preview", Static).update(self._empty_preview(no_results=True))

    def _populate_tree(
        self,
        *,
        expanded_paths: set[Path] | None = None,
        selected_key: tuple[str, str] | None = None,
    ) -> Any | None:
        tree = self.query_one("#conversation-tree", Tree)
        tree.clear()
        tree.root.set_label(self._tree_root_label())
        tree.root.data = DirectoryEntry(Path.home())
        tree.root.expand()

        directory_nodes: dict[tuple[str, ...], Any] = {}
        nodes_by_key: dict[tuple[str, str], Any] = {}
        first_root_child: Any | None = None
        expanded_paths = expanded_paths or set()
        grouped = list(group_by_path(self.conversations).items())
        if self.directory_sort == "recent":
            grouped.sort(key=lambda item: item[1][0].updated_at, reverse=True)
        else:
            grouped.sort(key=lambda item: str(item[0]).casefold())

        for cwd, conversations in grouped:
            scope, parts = self._path_parts(cwd)
            parent = tree.root
            key_parts: list[str] = [scope]
            if scope == "/":
                slash_key = tuple(key_parts)
                if slash_key not in directory_nodes:
                    slash_node = tree.root.add(
                        "▰  /",
                        data=DirectoryEntry(Path("/")),
                        expand=Path("/") in expanded_paths,
                    )
                    directory_nodes[slash_key] = slash_node
                    nodes_by_key[("directory", "/")] = slash_node
                    first_root_child = first_root_child or slash_node
                parent = directory_nodes[slash_key]  # type: ignore[assignment]

            current_path = Path.home() if scope == "~" else Path("/")
            for part in parts:
                current_path = current_path / part
                key_parts.append(part)
                key = tuple(key_parts)
                node = directory_nodes.get(key)
                if node is None:
                    node = parent.add(
                        Text.assemble(("▰  ", "#e5a843"), (part, "#c8d0da")),
                        data=DirectoryEntry(current_path),
                        expand=current_path in expanded_paths,
                    )
                    directory_nodes[key] = node
                    nodes_by_key[("directory", str(current_path))] = node
                    if parent is tree.root:
                        first_root_child = first_root_child or node
                parent = node  # type: ignore[assignment]

            for conversation in conversations:
                conversation_node = parent.add_leaf(
                    Text.assemble(
                        f"{conversation.icon}  ", (conversation.title, "#d7dde5")
                    ),
                    data=conversation,
                )
                nodes_by_key[
                    ("conversation", _conversation_key(conversation))
                ] = conversation_node
                if parent is tree.root:
                    first_root_child = first_root_child or conversation_node

        return nodes_by_key.get(selected_key) or first_root_child

    def _populate_recents(self) -> None:
        table = self.query_one("#recents", DataTable)
        table.clear(columns=False)
        for index, conversation in enumerate(self.recent_conversations, start=1):
            state_label = _conversation_state(conversation)
            state_style = (
                "#ef6b73"
                if not conversation.is_available
                else "#e5a843"
                if conversation.is_archived
                else "#72d572"
            )
            state = Text(state_label, style=state_style)
            table.add_row(
                str(index),
                Text.assemble(f"{conversation.icon} ", conversation.title),
                _display_path(conversation.cwd),
                _relative_time(conversation.updated_at),
                state,
                key=_conversation_key(conversation),
            )

    @staticmethod
    def _path_parts(path: Path) -> tuple[str, tuple[str, ...]]:
        try:
            relative = path.relative_to(Path.home())
        except ValueError:
            return "/", path.parts[1:]
        return "~", relative.parts

    def _select(self, conversation: Conversation) -> None:
        self.current_conversation = conversation
        self.query_one("#details", Static).update(self._details(conversation))
        self.query_one("#preview", Static).update(self._preview(conversation))

    @on(Tree.NodeHighlighted, "#conversation-tree")
    def tree_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if isinstance(event.node.data, Conversation):
            self._select(event.node.data)

    @on(DataTable.RowHighlighted, "#recents")
    def recent_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(self.recent_conversations):
            self._select(self.recent_conversations[event.cursor_row])

    def action_move_down(self) -> None:
        focused = self.focused
        if isinstance(focused, Tree):
            focused.action_cursor_down()
        elif isinstance(focused, DataTable):
            focused.action_cursor_down()

    def action_move_up(self) -> None:
        focused = self.focused
        if isinstance(focused, Tree):
            focused.action_cursor_up()
        elif isinstance(focused, DataTable):
            focused.action_cursor_up()

    def action_collapse(self) -> None:
        tree = self.query_one("#conversation-tree", Tree)
        if not tree.has_focus or tree.cursor_node is None:
            return
        node = tree.cursor_node
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            tree.select_node(node.parent)

    def action_expand(self) -> None:
        tree = self.query_one("#conversation-tree", Tree)
        if tree.has_focus and tree.cursor_node is not None:
            tree.cursor_node.expand()

    def action_first(self) -> None:
        focused = self.focused
        if isinstance(focused, Tree):
            focused.select_node(focused.root)
        elif isinstance(focused, DataTable) and self.recent_conversations:
            focused.move_cursor(row=0)

    def action_last(self) -> None:
        focused = self.focused
        if isinstance(focused, Tree):
            focused.select_node(focused.last_node)
        elif isinstance(focused, DataTable) and self.recent_conversations:
            focused.move_cursor(row=len(self.recent_conversations) - 1)

    def action_next_panel(self) -> None:
        tree = self.query_one("#conversation-tree", Tree)
        table = self.query_one("#recents", DataTable)
        (table if tree.has_focus else tree).focus()

    def action_activate(self) -> None:
        tree = self.query_one("#conversation-tree", Tree)
        if tree.has_focus and tree.cursor_node is not None:
            data = tree.cursor_node.data
            if isinstance(data, Conversation):
                self._select(data)
                self.action_open()
            else:
                tree.cursor_node.toggle()
            return
        self.action_open()

    def action_open(self) -> None:
        conversation = self.current_conversation
        if conversation is None:
            self.notify("Select a conversation first.", severity="warning")
            return
        if not conversation.cwd.is_dir():
            self.notify(
                f"Working directory no longer exists: {conversation.cwd}",
                severity="error",
                timeout=6,
            )
            return
        program = conversation.resume_command[0]
        executable = shutil.which(program)
        if executable is None:
            self.notify(
                f"{program} executable was not found on PATH.", severity="error"
            )
            return
        self.exit(conversation)

    def action_refresh(self) -> None:
        self._set_loading(True)
        self.load_conversations()

    def action_sort_directories(self) -> None:
        tree = self.query_one("#conversation-tree", Tree)
        expanded_paths = self._expanded_directory_paths(tree)
        selected_key = self._tree_node_key(tree.cursor_node)
        self.directory_sort = "name" if self.directory_sort == "recent" else "recent"
        selected_node = self._populate_tree(
            expanded_paths=expanded_paths, selected_key=selected_key
        )
        if selected_node is not None:
            self.call_after_refresh(tree.select_node, selected_node)
        label = "most recent" if self.directory_sort == "recent" else "name"
        self.notify(f"Directories ordered by {label}.", timeout=2)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _set_loading(self, loading: bool) -> None:
        self.query_one("#conversation-tree", Tree).root.set_label(
            self._tree_root_label(loading=loading)
        )

    def _tree_root_label(self, *, loading: bool = False) -> str:
        count = "scanning…" if loading else str(len(self.conversations))
        order = "recent" if self.directory_sort == "recent" else "name"
        return f"⌂  ~  ({count})  ·  {order}"

    @staticmethod
    def _tree_node_key(node: Any | None) -> tuple[str, str] | None:
        if node is None:
            return None
        if isinstance(node.data, Conversation):
            return "conversation", _conversation_key(node.data)
        if isinstance(node.data, DirectoryEntry):
            return "directory", str(node.data.path)
        return None

    @staticmethod
    def _expanded_directory_paths(tree: Tree) -> set[Path]:
        expanded: set[Path] = set()
        pending = list(tree.root.children)
        while pending:
            node = pending.pop()
            if isinstance(node.data, DirectoryEntry) and node.is_expanded:
                expanded.add(node.data.path)
            pending.extend(node.children)
        return expanded

    def _load_failed(self, error: Exception) -> None:
        self._set_loading(False)
        self.notify(f"Could not scan conversations: {error}", severity="error")

    @staticmethod
    def _details(conversation: Conversation) -> Text:
        result = Text()
        result.append("DETAILS\n\n", style="bold #62a8ff")
        fields = (
            ("Name", conversation.title),
            ("Provider", conversation.source),
            ("Messages", str(conversation.message_count)),
            ("Created", _date_time(conversation.created_at)),
            ("Updated", _date_time(conversation.updated_at)),
            ("State", _conversation_state(conversation)),
            ("Path", _display_path(conversation.cwd)),
        )
        for label, value in fields:
            result.append(f"{label + ':':<11}", style="#aeb8c4")
            style = None
            if label == "State":
                style = (
                    "#ef6b73"
                    if not conversation.is_available
                    else "#e5a843"
                    if conversation.is_archived
                    else "#72d572"
                )
            result.append(value, style=style)
            result.append("\n")
        if conversation.git_branch:
            result.append(f"{'Branch:':<11}", style="#aeb8c4")
            result.append(conversation.git_branch)
        return result

    @staticmethod
    def _preview(conversation: Conversation) -> Text:
        result = Text()
        result.append("FIRST PROMPT\n\n", style="bold #62a8ff")
        result.append(conversation.first_prompt or "No user prompt was found.")
        result.append("\n\n")
        result.append(f"Session  {conversation.session_id}", style="dim")
        return result

    @staticmethod
    def _actions() -> Text:
        result = Text("ACTIONS\n\n", style="bold #62a8ff")
        for keys, label in (
            ("Enter / o", "Resume conversation"),
            ("h / l", "Collapse / Expand"),
            ("Tab", "Switch panel"),
            ("s", "Change directory order"),
            ("r", "Refresh conversations"),
            ("?", "Keyboard help"),
        ):
            result.append(f"[{keys}]", style="bold #d7dde5")
            result.append("  →  ", style="#5e6a77")
            result.append(label)
            result.append("\n\n")
        return result

    @staticmethod
    def _footer() -> Text:
        result = Text(justify="center")
        for keys, label in (
            ("j/k", "Navigate"),
            ("h/l", "Fold"),
            ("s", "Sort"),
            ("Enter/o", "Resume"),
            ("Tab", "Panel"),
            ("r", "Refresh"),
            ("q", "Quit"),
        ):
            result.append(f"[{keys}]", style="bold #38d6c4")
            result.append(f" {label}     ", style="#38d6c4")
        return result

    @staticmethod
    def _empty_details(no_results: bool = False) -> Text:
        result = Text("DETAILS\n\n", style="bold #62a8ff")
        result.append(
            "No conversations found."
            if no_results
            else "Scanning conversations…",
            style="dim",
        )
        return result

    @staticmethod
    def _empty_preview(no_results: bool = False) -> Text:
        result = Text("FIRST PROMPT\n\n", style="bold #62a8ff")
        result.append(
            "There is nothing to preview."
            if no_results
            else "Conversation metadata will appear here.",
            style="dim",
        )
        return result


def _display_path(path: Path) -> str:
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _conversation_key(conversation: Conversation) -> str:
    return f"{conversation.source}:{conversation.session_id}"


def _conversation_state(conversation: Conversation) -> str:
    if not conversation.is_available:
        return "Missing"
    return "Archived" if conversation.is_archived else "Ready"


def _date_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _relative_time(value: datetime) -> str:
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - value.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3_600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3_600}h ago"
    if seconds < 604_800:
        return f"{seconds // 86_400}d ago"
    return value.astimezone().strftime("%b %d")
