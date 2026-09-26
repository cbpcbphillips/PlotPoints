"""Shared pass/fail harness for the per-endpoint connection checks.

check_tmdb / check_snowflake / check_aws each build a list of named probes and hand
them to run_checks, which runs every probe independently, prints one PASS/WARN/FAIL
line each, and returns an exit code. Probes are isolated on purpose: one failure
shouldn't hide the rest, since the point is a full picture of which endpoint is
broken rather than just the first error.

These checks are read-only against the live services -- they report what exists
instead of creating it. `just smoke-test` remains the one that provisions the RAW
landing objects.

Output is ASCII-only: the Windows console these run on mangles non-ASCII.
"""

import traceback

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

LABEL_WIDTH = 26


class CheckWarning(Exception):
    """Raised by a probe for a non-fatal finding -- reported as WARN, not FAIL."""


def run_checks(title, checks, verbose=False):
    """Run a list of (label, probe) pairs.

    Each probe takes no arguments and returns a detail string (or None). Raising
    CheckWarning reports WARN; any other exception reports FAIL. Returns 0 when
    nothing failed, 1 otherwise, so callers can use it as an exit code.
    """
    print(f"== {title} ==")
    statuses = []

    for label, probe in checks:
        try:
            detail = probe() or ""
            status = PASS
        except CheckWarning as exc:
            status, detail = WARN, str(exc)
        except Exception as exc:
            status, detail = FAIL, f"{type(exc).__name__}: {exc}"
            if verbose:
                traceback.print_exc()

        statuses.append(status)
        print(f"{status}  {label:<{LABEL_WIDTH}} {detail}")

    return _print_summary(statuses)


def _print_summary(statuses):
    passed = statuses.count(PASS)
    warned = statuses.count(WARN)
    failed = statuses.count(FAIL)

    summary = f"{passed} passed"
    if warned:
        summary += f", {warned} warned"
    if failed:
        summary += f", {failed} FAILED"

    print(f"\n{summary}")
    return 1 if failed else 0


def human_bytes(n):
    """Byte count as a short human-readable string (for payload-size reporting)."""
    for unit in ("B", "KB", "MB"):
        if abs(n) < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
