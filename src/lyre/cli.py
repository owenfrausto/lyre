from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from lyre import __version__
from lyre.app import LyreApp
from lyre.catalog import CompositeStore
from lyre.claude import ClaudeStore, default_claude_home
from lyre.codex import CodexStore, default_codex_home
from lyre.models import Conversation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lyre", description="Browse and resume agentic conversations."
    )
    parser.add_argument(
        "--claude-home",
        type=Path,
        default=default_claude_home(),
        help="Claude config directory (default: %(default)s)",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=default_codex_home(),
        help="Codex config directory (default: %(default)s)",
    )
    parser.add_argument("--version", action="version", version=f"lyre {__version__}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    conversation = LyreApp(
        CompositeStore(
            (ClaudeStore(args.claude_home), CodexStore(args.codex_home))
        )
    ).run()
    if conversation is not None:
        handoff(conversation)


def handoff(conversation: Conversation) -> None:
    """Replace Lyre with the selected provider in its original directory."""

    program, *arguments = conversation.resume_command
    executable = shutil.which(program)
    if executable is None:
        raise SystemExit(f"lyre: {program} executable was not found on PATH")
    try:
        os.chdir(conversation.cwd)
        os.execv(executable, [executable, *arguments])
    except OSError as error:
        raise SystemExit(f"lyre: could not open {conversation.title}: {error}") from error
