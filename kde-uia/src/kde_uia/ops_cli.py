"""``python -m kde_uia ops <name>`` - one JSON operation per process invocation.

This entry point is what the DeepSeek Harness plugin calls over WSL/SSH:
the plugin sends *arguments only* (never a shell string) and reads one JSON
document from stdout (or from the file named by ``--result``).  It is also
handy from any language: ``subprocess`` + ``json.loads``.

Contract:

* exit ``0``: success, stdout is ``{"ok": true, "result": {...}}``
* exit ``2``: invalid usage, stdout is ``{"ok": false, "error": {...}}``
* exit ``1``: any other coded failure, same error shape
* with ``--result PATH``: the document is also written atomically to PATH,
  so a broken pipe in the caller cannot lose the answer.

Environment overrides are read from ``KDE_UIA_*`` variables (see
:mod:`kde_uia.session`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import env as env_mod
from .errors import ERROR_CODES, KdeUiaError, UsageError
from .ops import OPS
from .session import DesktopSession, Options

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _emit(document: dict[str, Any], result_path: str | None) -> None:
    payload = json.dumps(document, ensure_ascii=False, indent=1)
    if result_path:
        target = Path(result_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".kde-uia-", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(tmp, target)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _error_exit(error: KdeUiaError) -> int:
    return EXIT_USAGE if error.code == "USAGE" else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(__doc__ or "")
        return EXIT_USAGE
    op_name = argv[0]
    parser = argparse.ArgumentParser(prog=f"kde-uia ops {op_name}", add_help=False)
    parser.add_argument("--args", default="{}", help="JSON object of operation arguments")
    parser.add_argument("--args-file", default=None, help="read the JSON arguments from this file")
    parser.add_argument("--result", default=None, help="also write the JSON answer to this path")
    parser.add_argument("--backend", default=None, help="window backend: auto|kwin|x11|atspi")
    parser.add_argument("--dry-run", action="store_true", help="never move the pointer or press keys")
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        _emit({"ok": False, "error": {"code": "USAGE", "message": "bad arguments to the ops runner",
                                      "hint": "usage: python -m kde_uia ops <op> --args '<json>' [--result PATH]"}}, None)
        return EXIT_USAGE
    if op_name not in OPS:
        _emit({"ok": False, "error": {"code": "USAGE", "message": f"unknown op {op_name!r}",
                                      "hint": "Ops: " + ", ".join(sorted(OPS))}}, ns.result)
        return EXIT_USAGE
    try:
        raw = Path(ns.args_file).read_text(encoding="utf-8") if ns.args_file else ns.args
        args = json.loads(raw or "{}")
        if not isinstance(args, dict):
            raise UsageError("--args must be a JSON object")
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "error": {"code": "USAGE", "message": f"invalid JSON arguments: {exc}"}}, ns.result)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"ok": False, "error": {"code": "USAGE", "message": f"cannot read --args-file: {exc}"}}, ns.result)
        return EXIT_USAGE

    options = Options(
        window_backend=ns.backend or os.environ.get("KDE_UIA_BACKEND", "auto"),
        input_strategy=os.environ.get("KDE_UIA_INPUT", "auto"),
        screenshot_strategy=os.environ.get("KDE_UIA_SCREENSHOT", "auto"),
        allow_xdotool_on_wayland=os.environ.get("KDE_UIA_ALLOW_XDOTOOL_ON_WAYLAND", "") not in ("", "0", "false"),
        dry_run=bool(ns.dry_run),
    )
    session = DesktopSession(options)
    try:
        result = OPS[op_name](session, args)
        _emit({"ok": True, "result": result}, ns.result)
        return EXIT_OK
    except KdeUiaError as exc:
        _emit({"ok": False, "error": exc.to_dict()}, ns.result)
        return _error_exit(exc)
    except KeyboardInterrupt:
        _emit({"ok": False, "error": {"code": "INTERNAL", "message": "interrupted"}}, ns.result)
        return 130
    except Exception as exc:  # noqa: BLE001 - the contract is one JSON document, never a traceback
        _emit({"ok": False, "error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}",
                                      "hint": "Re-run with `kde-uia doctor`; set KDE_UIA_DEBUG=1 for a traceback."}}, ns.result)
        if os.environ.get("KDE_UIA_DEBUG"):
            import traceback

            traceback.print_exc()
        return EXIT_FAILED
    finally:
        session.close()


__all__ = ["main", "ERROR_CODES", "env_mod"]
