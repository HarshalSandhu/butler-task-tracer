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

import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime

DEFAULT_SSH_USER = "gor"
# How long ssh waits for the TCP+key-exchange handshake before giving up. 5s was too tight -
# confirmed real targets that are reachable but occasionally take a few seconds longer to
# respond (network jitter into a validation namespace, a VM waking up from idle) were getting
# a hard "Connection timed out" before ssh even finished trying. Configurable via
# SSH_CONNECT_TIMEOUT_SECONDS (docker-compose.yml env), same pattern as SSH_KEY_PATH below.
CONNECT_TIMEOUT_SECONDS = int(os.environ.get("SSH_CONNECT_TIMEOUT_SECONDS", "50"))

# Optional explicit identity file path (inside the container, e.g.
# /root/.ssh/id_ed25519) - NOT a key itself, just a path into the
# read-only ~/.ssh bind mount (see README.md "SSH access model"). Set via
# docker-compose.yml's SSH_KEY_PATH env var. Without this, ssh falls back
# to its own default identity-file trial order, which can be fragile if
# an earlier key in that order is unreadable/malformed (a genuinely
# corrupted id_rsa surfaced exactly this during this tool's own testing -
# ssh's multi-key fallback behavior on a load failure isn't reliable
# enough to depend on for an automated tool).
SSH_KEY_PATH = os.environ.get("SSH_KEY_PATH")

# ~/.ssh is mounted read-only, so ssh can't persist new host keys to the
# real known_hosts file there (StrictHostKeyChecking=accept-new would
# otherwise just warn-and-continue on a hit, but fail outright for a
# genuinely new host). Redirect to a writable, container-local file
# instead - this only affects host-key TOFU bookkeeping for this
# container, never touches the operator's real known_hosts.
CONTAINER_KNOWN_HOSTS = "/tmp/butler_tracer_known_hosts"

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


def _run(target: SshTarget, remote_command: str, timeout: int | None = None) -> str:
    """Runs `remote_command` on `target` and returns stdout. Raises
    SshCommandError on any non-zero exit or timeout - callers should
    surface this directly to the API caller as a clear error, never retry
    silently (a hung/failed SSH session should never look like "no logs
    found").

    `timeout` bounds the whole subprocess (connect + command execution), so it must always be
    at least CONNECT_TIMEOUT_SECONDS plus room for the command itself to run - otherwise this
    outer timeout fires before ssh's own -o ConnectTimeout even gets a chance to, silently
    undoing a larger CONNECT_TIMEOUT_SECONDS. Defaults to a small buffer over just that connect
    time, for callers (like a plain `ls`) that don't need much beyond it.
    """
    if timeout is None:
        timeout = CONNECT_TIMEOUT_SECONDS + 10
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",  # fail fast instead of prompting for a password
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={CONTAINER_KNOWN_HOSTS}",
    ]
    if SSH_KEY_PATH:
        ssh_cmd += ["-i", SSH_KEY_PATH, "-o", "IdentitiesOnly=yes"]
    ssh_cmd += [f"{target.user}@{target.ip}", remote_command]
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


def list_debug_log_files_with_mtime(target: SshTarget) -> list[tuple[str, datetime]]:
    """Same file set as list_debug_log_files, but paired with each file's
    mtime (UTC) -- see PLAN.md "Log discovery": a rotated file's mtime is
    approximately when it *stopped* being written (i.e. the latest
    timestamp its content could contain), so `[file for file in this list
    if mtime >= window_start]` is a safe, conservative way to skip files
    that provably can't contain anything in a target time window, without
    reading their content. This matters in practice: a naive grep across
    every rotation (12+ files, 500MB+ each) for a common substring like
    `butler_id=<N>` can take minutes even though only 1-2 files actually
    overlap any given task's real time window (confirmed against the real
    validation VM - see api/routes.py's _attach_lift_events).
    """
    globs = " ".join(f"{d}/debug.log*" for d in CANDIDATE_LOG_DIRS)
    # %Y-%m-%dT%H:%M:%S -> stat's UTC mtime, one field per file, paired
    # with the path itself via a separator that won't appear in a path.
    cmd = f"for f in {globs}; do [ -f \"$f\" ] && stat -c '%Y|||%n' \"$f\"; done 2>/dev/null"
    out = _run(target, cmd)
    results: list[tuple[str, datetime]] = []
    for line in out.splitlines():
        if "|||" not in line:
            continue
        epoch_str, path = line.split("|||", 1)
        try:
            results.append((path, datetime.utcfromtimestamp(int(epoch_str))))
        except ValueError:
            continue
    return results


def grep_logs(target: SshTarget, pattern: str, log_files: list[str], timeout: int = CONNECT_TIMEOUT_SECONDS + 60) -> list[str]:
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


_LIFT_MARKER_PATTERN = (
    r"simultaneousForkLift|Fork height adjustment completed for "
    r"simultaneous_fork_lift_to_maxdown_height|Fork height adjustment completed during "
    r"parallel navigation|simultaneous_lift_time_for_fork|liftHeight|"
    r"htm_load_tote|htm_unload_tote|pps_control|setForkHeight|tote_load|tote_unload|"
    r"set_relay_group_task_status"
)


def grep_bot_lift_lines(
    target: SshTarget, bot_id: str, log_files: list[str], timeout: int = CONNECT_TIMEOUT_SECONDS + 60
) -> list[str]:
    """Lines relevant to reconstructing simultaneousForkLift completion
    timing (see parsers/lift_events.py) for one bot -- including its
    SECOND, differently-worded premature-completion message ("Fork height
    adjustment completed during parallel navigation", confirmed real:
    task da1cfdc4-5f0d-49c5-8678-157d9f4675a3, bot 209, a real
    simultaneousForkLift to 880mm issued mid-travel via
    compute_parallel_lift_goto_barcode -- this exact message was silently
    filtered out here before it existed as a marker, so that lift never
    became a LiftEvent at all, only ever showing up via the generic
    telemetry-plateau fallback with no order/timing-correction pairing).
    PLUS the discrete load/unload/pps-control orders (also via
    `gmc_mqtt_agv_communicator:
    pub_order`, same mechanism -- confirmed real: `Order = {htm_unload_tote,
    #{height => 420, tote_id => ..., coordinate => ...}}`) used as hard
    boundaries so a real drop/pick action never gets silently merged away
    into a surrounding fork-height plateau transition (see
    build_fork_adjustment_events). Also fetches VTM's entirely different
    `setForkHeight`/`tote_load`/`tote_unload` orders (same mechanism, same
    `pub_order` line) -- their completion signal (the VDA5050 actionStates
    stream) rides on the SAME `#recv` lines already matched via
    "liftHeight" below, so no additional marker is needed for that half.
    Also fetches relay_group_task's own `set_relay_group_task_status`
    status-transition lines -- like the fork/tote lines above, these never
    restate the task_id either (see terminal_state.py's module docstring),
    so terminal_state.classify() can never actually see the real
    completion marker from the task_id-scoped grep alone; api/routes.py
    re-checks status against these once fetched (see
    _maybe_reclassify_relay_group_completion).
    These lines never restate a task_id/MainTaskKey, so a plain
    `grep_logs(pattern=task_id)` would never find them at all -- this
    greps by butler_id instead (piped through a second grep for the
    specific markers, since a single `zgrep -E` pattern can't express
    "line contains A AND matches one of B/C/D" without a lookahead POSIX
    EREs don't support). Reuses the same `log_files` list already resolved
    for the task, no extra remote round-trip to re-list files.
    """
    if not log_files:
        return []
    quoted_files = " ".join(shlex.quote(f) for f in log_files)
    bot_pattern = shlex.quote(f"butler_id={bot_id}")
    marker_pattern = shlex.quote(_LIFT_MARKER_PATTERN)
    cmd = f"zgrep -h -E {bot_pattern} {quoted_files} 2>/dev/null | grep -E {marker_pattern}"
    out = _run(target, cmd, timeout=timeout)
    return out.splitlines()


_ROTATION_MARKER_PATTERN = r"turn_step|agvPosition|reached_destination"


def grep_bot_rotation_lines(
    target: SshTarget, bot_id: str, log_files: list[str], timeout: int = CONNECT_TIMEOUT_SECONDS + 60
) -> list[str]:
    """Lines relevant to reconstructing HTM in-place rotation time (see
    parsers/rotation_events.py): navigator_agent's "Got goal pathlist"
    lines (planned-path `turn_step` estimate), plus the AGV's own state
    stream (`agvPosition.theta`, ground truth -- same `#recv` lines
    grep_bot_lift_lines already matches via "liftHeight", fetched again
    here so this module stays self-contained). Also fetches
    `navigator_agent:reached_destination` -- a DIFFERENT software
    version's movement-arrival line (see parsers/generic_movement.py),
    piggybacked onto this same butler_id-scoped fetch since it's already
    running for the same bot/window; costs nothing extra to also grab it,
    and api/routes.py only ever acts on it when the task's own EXACT
    movement resolver found nothing at all. Same two-stage
    butler_id-then-marker grep as grep_bot_lift_lines, for the same reason
    (these lines don't restate a task_id either).
    """
    if not log_files:
        return []
    quoted_files = " ".join(shlex.quote(f) for f in log_files)
    bot_pattern = shlex.quote(f"butler_id={bot_id}")
    marker_pattern = shlex.quote(_ROTATION_MARKER_PATTERN)
    cmd = f"zgrep -h -E {bot_pattern} {quoted_files} 2>/dev/null | grep -E {marker_pattern}"
    out = _run(target, cmd, timeout=timeout)
    return out.splitlines()


def check_connectivity(target: SshTarget) -> None:
    """Raises SshCommandError with a clear message if passwordless
    key-based SSH isn't already working for this target - callers should
    call this before a scan so the UI can show "SSH not configured for
    this IP" instead of a confusing downstream parse failure.
    """
    _run(target, "true", timeout=CONNECT_TIMEOUT_SECONDS + 2)
