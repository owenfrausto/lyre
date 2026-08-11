# Lyre

Lyre is a terminal home for agentic conversations. It discovers local Claude
Code and Codex sessions, groups them by the directory or worktree where they
began, previews their metadata, and resumes them in place. Claude conversations
use `🦀`; Codex conversations use `🤖`.

## Run it

Python 3.11+ is required. Install the Claude Code and/or Codex CLI for the
providers you want Lyre to discover and resume.

```console
uv run lyre
```

To install the `lyre` command globally from this checkout:

```console
uv tool install .
lyre
```

Lyre uses `~/.claude` and `~/.codex` by default. It honors
`CLAUDE_CONFIG_DIR` and `CODEX_HOME`; either location can also be selected
explicitly:

```console
lyre --claude-home /path/to/.claude --codex-home /path/to/.codex
```

## Controls

| Key | Action |
| --- | --- |
| `j` / `k` | Move down / up |
| `h` / `l` | Collapse / expand a directory |
| `g` / `G` | Jump to the first / last item |
| `Tab` | Switch between the tree and recent conversations |
| `Enter` / `o` | Resume the selected conversation |
| `s` | Toggle directory order between most recent and name |
| `r` | Rescan provider conversation stores |
| `?` | Show keyboard help |
| `q` | Quit |

Opening a conversation exits Lyre, changes into the conversation's recorded
working directory, and replaces the Lyre process with the matching provider:

```console
claude --resume <session-id>
codex resume <session-id>
```

Because this is a process handoff, exiting the provider returns directly to the
shell rather than reopening Lyre.

Directories start collapsed and are ordered by their most recently updated
conversation. The `s` binding switches to alphabetical order and back while
preserving the directories currently expanded.

## Scope

The initial release is intentionally read-only. It reads top-level Claude Code
JSONL transcripts under `~/.claude/projects` and current Codex rollouts under
`~/.codex/sessions`. Codex titles are read from its thread index when available.
Lyre uses each provider's recorded `cwd`, ignores Claude sidechains and Codex
subagent rollouts, and never renames, moves, or deletes provider data.

Older Codex rollout formats that do not record a working directory are skipped
because Lyre cannot place them accurately in the directory tree.

Search and Lyre-owned tags are natural follow-ons; tags should live in Lyre's
own metadata rather than altering provider transcripts.

## Development

```console
uv sync --dev
uv run pytest
```
