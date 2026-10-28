"""Allow ``python -m kde_uia [ops ...]`` on every supported Python."""

from __future__ import annotations

import sys

if sys.argv[1:2] == ["ops"]:
    from .ops_cli import main

    sys.exit(main(sys.argv[2:]))

from .cli import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
