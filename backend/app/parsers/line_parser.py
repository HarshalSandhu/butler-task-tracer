"""Parses one raw MHS debug.log line into its structural fields.

Format confirmed universal across all severities in this session's research
(apps/butler_base/src/critical/gm_lager.erl + butler_setup.erl in the
butler_server repo - lager's default file-backend format):

    YYYY-MM-DD HH:MM:SS.mmm [level][pid] --- module:function:line: message

Example:
    2026-07-27 11:39:36.434 [debug][<0.5720.0>] --- rm_common_subtasks:goto_barcode_completed:{929,6}: butler_id=200 goto_barcode_completed: ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator

_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) "
    r"\[(?P<level>\w+)\]\[(?P<pid>[^\]]+)\] --- "
    r"(?P<module>[\w.]+):(?P<function>\w+):\{(?P<line_no>\d+),\d+\}: "
    r"(?P<message>.*)$"
)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


@dataclass
class ParsedLine:
    timestamp: datetime
    level: str
    pid: str
    module: str
    function: str
    line_no: int
    message: str
    raw_line: str


def parse_line(raw_line: str) -> ParsedLine | None:
    """Returns None for lines that don't match the expected format (e.g.
    multi-line continuations of a large ~p dump, or non-lager output) -
    callers should skip those rather than error, since a single malformed
    line must never abort a whole scan.
    """
    line = raw_line.rstrip("\n")
    m = _LINE_RE.match(line)
    if not m:
        return None
    ts = datetime.strptime(f"{m.group('date')} {m.group('time')}", _TS_FORMAT)
    return ParsedLine(
        timestamp=ts,
        level=m.group("level"),
        pid=m.group("pid"),
        module=m.group("module"),
        function=m.group("function"),
        line_no=int(m.group("line_no")),
        message=m.group("message"),
        raw_line=line,
    )


def parse_lines(raw_lines: "Iterable[str]") -> "Iterator[ParsedLine]":
    """Streaming variant - skips unparseable lines rather than raising, so a
    malformed/truncated line (e.g. a ~p dump that itself contains an
    embedded newline) never aborts the whole scan.
    """
    for raw in raw_lines:
        parsed = parse_line(raw)
        if parsed is not None:
            yield parsed
