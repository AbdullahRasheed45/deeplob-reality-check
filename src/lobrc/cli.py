"""Command-line entry point: `lobrc <subcommand>`.

Finance concept: every experiment is launched the same way (a config file plus optional
overrides), so results are reproducible and comparable across phases.

Later phases add subcommands by exposing `register(subparsers)` in their own module and
listing that module in `_COMMAND_MODULES`.
"""
from __future__ import annotations

import argparse
import importlib
import sys

from lobrc import __version__
from lobrc.logging_setup import setup_logging

# Modules that expose `register(subparsers)`. Later phases append their module path here.
_COMMAND_MODULES: list[str] = []


def add_common_args(p: argparse.ArgumentParser) -> None:
    """Add the --config and repeated --set options every subcommand accepts."""
    p.add_argument("--config", default="configs/default.yaml", help="YAML config path")
    p.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
        help="override a config value, e.g. --set seed=7 (repeatable)",
    )


def _cmd_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser and register all subcommands."""
    parser = argparse.ArgumentParser(prog="lobrc", description="DeepLOB Reality Check")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("version", help="print the package version")
    add_common_args(p)
    p.set_defaults(func=_cmd_version)
    for mod_name in _COMMAND_MODULES:
        importlib.import_module(mod_name).register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the chosen subcommand."""
    setup_logging()
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
