"""Shells out to the real `ssh`/`scp`-adjacent tooling on the host.

INVARIANT (do not weaken this): this module, and every caller of it, must
NEVER accept, store, or transmit private key material. The only credential
concept in this entire codebase is a `butler_ip` + `ssh_user` pair - actual
authentication is delegated entirely to the host's own `ssh` binary, which
resolves keys/agent/known_hosts exactly as it would for a user's own
terminal session (see PLAN.md "SSH access model" and README.md). The
container this runs in mounts the operator's `~/.ssh` read-only; this
module never reads that path directly, it only ever invokes `ssh`.

Uses `subprocess`, not a pure-Python SSH client library, specifically so
there is no reimplementation of key/agent/known_hosts resolution to get
subtly wrong - it is exactly the same `ssh` command the operator already
trusts.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

DEFAULT_SSH_USER = "gor"
CONNECT_TIMEOUT_SECONDS = 5

# Candidate MHS debug.log locations - installs vary (see PLAN.md "Log
# discovery"). Extend this list as new install layouts are encountered;
# never hardcode a single path as gospel.
CANDIDATE_LOG_DIRS = [
    "/var/log/butler_server/log/mhs",
]


class SshCommandError(RuntimeError):
    """Raised when the remote command fails or the connection can't be
    established (including the BatchMode=yes fast-fail case - see
    _run below)."""


@dataclass
class SshTarget:
    ip: str
    user: str = DEFAULT_SSH_USER


def _run(target: SshTarget, remote_command: str, timeout: int = 30) -> str:
    """Runs `remote_command` on `target` and returns stdout. Raises
    SshCommandError on any non-zero exit or timeout - callers should
    surface this directly to the API caller as a clear error, never retry
    silently (a hung/failed SSH session should never look like "no logs
    found").
    """
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",  # fail fast instead of prompting for a password
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{target.user}@{target.ip}",
        remote_command,
    ]
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SshCommandError(
            f"SSH command to {target.user}@{target.ip} timed out after {timeout}s"
        ) from exc

    if result.returncode != 0:
        raise SshCommandError(
            f"SSH command to {target.user}@{target.ip} failed "
            f"(exit {result.returncode}): {result.stderr.strip()[:500]}"
        )
    return result.stdout


def list_debug_log_files(target: SshTarget) -> list[str]:
    """One remote round-trip: lists every debug.log* candidate across all
    known install paths, newest mtime first is NOT assumed - callers that
    care about chronological order (anything computing durations across
    file boundaries) must sort by mtime themselves; this just returns the
    file list."""
    globs = " ".join(f"{d}/debug.log*" for d in CANDIDATE_LOG_DIRS)
    cmd = f"ls -1 {globs} 2>/dev/null"
    out = _run(target, cmd)
    return [line for line in out.splitlines() if line.strip()]


def grep_logs(target: SshTarget, pattern: str, log_files: list[str], timeout: int = 60) -> list[str]:
    """Greps `pattern` across `log_files` remotely (server-side, streamed
    back over the SSH pipe) - never copies the files themselves. Handles
    both plain and gzip-rotated files transparently via `zgrep`, which
    degrades gracefully to plain grep behavior on non-gzip input.
    """
    if not log_files:
        return []
    quoted_files = " ".join(shlex.quote(f) for f in log_files)
    quoted_pattern = shlex.quote(pattern)
    cmd = f"zgrep -h -E {quoted_pattern} {quoted_files} 2>/dev/null"
    out = _run(target, cmd, timeout=timeout)
    return out.splitlines()


def check_connectivity(target: SshTarget) -> None:
    """Raises SshCommandError with a clear message if passwordless
    key-based SSH isn't already working for this target - callers should
    call this before a scan so the UI can show "SSH not configured for
    this IP" instead of a confusing downstream parse failure.
    """
    _run(target, "true", timeout=CONNECT_TIMEOUT_SECONDS + 2)
