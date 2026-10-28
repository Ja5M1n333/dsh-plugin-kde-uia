"""Polling primitives: wait for conditions instead of sleeping blindly.

A UIA client that hard-sleeps is either flaky (the app was slower) or slow
(the app was faster).  kde-uia polls predicates with a deadline and a small
interval, and reports the last observed state when it gives up so the caller
can see *why* nothing matched.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .errors import WaitTimeoutError

DEFAULT_INTERVAL = 0.25


def wait_for(
    probe: Callable[[], Any],
    *,
    timeout: float = 10.0,
    interval: float = DEFAULT_INTERVAL,
    what: str = "condition",
    state: Callable[[], Any] | None = None,
) -> Any:
    """Return the first truthy value from ``probe``; raise ``TIMEOUT`` after ``timeout`` s.

    ``state`` is called once on failure to enrich the error with what was
    seen last (a window list, an element list, ...).
    """
    if timeout < 0:
        raise WaitTimeoutError("timeout must be >= 0")
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            value = probe()
        except Exception as exc:  # a flaky app mid-startup is normal during polling
            last_error: Exception | None = exc
        else:
            last_error = None
            if value:
                return value
        if time.monotonic() >= deadline:
            details: dict[str, Any] = {"attempts": attempt, "timeoutSeconds": timeout}
            if last_error is not None:
                details["lastError"] = str(last_error)
            if state is not None:
                try:
                    details["lastState"] = state()
                except Exception as exc:  # pragma: no cover - diagnostic only
                    details["lastStateError"] = str(exc)
            raise WaitTimeoutError(
                f"timed out after {timeout:g}s waiting for {what}",
                hint="The call waited deliberately and found nothing. Check the lastState, then re-run "
                     "`kde-uia windows`/`tree`; increase --timeout if the application is merely slow.",
                details=details,
            )
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())) or interval)
