"""OMNI entry point: interactive REPL, or one-shot: python -m omni "your goal"."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    import argparse
    from rich.console import Console

    parser = argparse.ArgumentParser(prog="omni", description="OMNI — your all-powerful permission-gated AI agent")
    parser.add_argument("text", nargs="*", help="run this as a single goal, then exit")
    parser.add_argument("--trust", action="store_true", help="start in trusted mode")
    parser.add_argument("--guarded", action="store_true", help="start in guarded mode (default)")
    parser.add_argument("--cautious", action="store_true", help="ask before EVERY action")
    parser.add_argument("--setup", action="store_true", help="run the setup wizard")
    parser.add_argument("--version", action="version", version="OMNI 1.0.0")
    args = parser.parse_args(argv)

    from omni import config
    if args.trust:
        config.set_config("permission_level", "trusted")
    elif args.cautious:
        config.set_config("permission_level", "cautious")
    elif args.guarded:
        config.set_config("permission_level", "guarded")

    console = Console(highlight=False)
    from omni.repl import REPL
    repl = REPL(console=console)
    repl.start_early()
    if args.setup:
        repl.ui.console.print("[bold]OMNI setup[/bold]")
        from omni.setupwizard import run as wizard
        wizard(repl.ui)
        return 0
    if args.text:
        goal = " ".join(args.text).strip()
        if not repl.ensure_brain():
            return 1
        repl._run_goal(goal)
        repl._stop_browser()
        return 0
    try:
        repl.start()
    except KeyboardInterrupt:
        print("\nbye.")
    repl._stop_browser()
    return 0


if __name__ == "__main__":
    sys.exit(main())
