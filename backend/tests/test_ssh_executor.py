"""Unit tests for ssh/executor.py parsing logic, with subprocess mocked out
-- these never touch a real network connection.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from app.ssh import executor


def _fake_completed_process(stdout: str, returncode: int = 0):
    class _Result:
        pass

    r = _Result()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


def test_list_debug_log_files_with_mtime_parses_stat_output():
    stdout = (
        "1785000000|||/var/log/butler_server/log/mhs/debug.log\n"
        "1784900000|||/var/log/butler_server/log/mhs/debug.log.0\n"
    )
    with patch.object(executor.subprocess, "run", return_value=_fake_completed_process(stdout)):
        result = executor.list_debug_log_files_with_mtime(executor.SshTarget(ip="1.2.3.4"))

    assert len(result) == 2
    path0, mtime0 = result[0]
    assert path0 == "/var/log/butler_server/log/mhs/debug.log"
    assert mtime0 == datetime.utcfromtimestamp(1785000000)


def test_list_debug_log_files_with_mtime_skips_malformed_lines():
    stdout = "not-a-valid-line\nbad|||also-bad-epoch\n1785000000|||/var/log/debug.log\n"
    with patch.object(executor.subprocess, "run", return_value=_fake_completed_process(stdout)):
        result = executor.list_debug_log_files_with_mtime(executor.SshTarget(ip="1.2.3.4"))

    assert len(result) == 1
    assert result[0][0] == "/var/log/debug.log"


def test_list_debug_log_files_with_mtime_empty_output():
    with patch.object(executor.subprocess, "run", return_value=_fake_completed_process("")):
        result = executor.list_debug_log_files_with_mtime(executor.SshTarget(ip="1.2.3.4"))
    assert result == []
