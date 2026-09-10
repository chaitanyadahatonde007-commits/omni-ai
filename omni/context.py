"""Shared context handed to every tool call."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from omni import config


class Context:
    def __init__(self, workspace: Path, session_dir: Path):
        self.workspace: Path = workspace
        self.session_dir: Path = session_dir
        self.log_path: Optional[Path] = None
        # The agent injects a gate callable for human-interactive tools
        # (browser, shell) so they can prompt even when running as a tool.
        self.interactive_gate: Optional[Callable[[str, str], bool]] = None
        self.state: dict = {}
        self.auto_yes: bool = False  # non-interactive: never auto-run risky steps

    # -- helpers used by tools --------------------------------------------
    @property
    def shell_style(self) -> str:
        return config.detect_shell()

    def log_event(self, message: str) -> None:
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(message.rstrip() + "\n")
            except Exception:
                pass

    def ask_human(self, prompt: str, default: bool = False) -> bool:
        """Blocking yes/no question. Returns False automatically when
        non-interactive."""
        if self.interactive_gate is None:
            return False
        return self.interactive_gate(prompt, "y" if default else "n")

    def remember_state(self, key: str, value) -> None:
        self.state[key] = value

    def get_state(self, key: str, default=None):
        return self.state.get(key, default)
