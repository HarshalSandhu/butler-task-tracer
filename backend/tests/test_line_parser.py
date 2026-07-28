from datetime import datetime

from app.parsers.line_parser import parse_line, parse_lines


def test_parses_debug_line():
    raw = (
        '2026-07-27 11:39:36.434 [debug][<0.5720.0>] --- rm_common_subtasks:'
        'goto_barcode_completed:{929,6}: butler_id=200 goto_barcode_completed: '
        'bot 200 reached {14,56} (attr=relay_storable_io_point)'
    )
    p = parse_line(raw)
    assert p is not None
    assert p.timestamp == datetime(2026, 7, 27, 11, 39, 36, 434000)
    assert p.level == "debug"
    assert p.module == "rm_common_subtasks"
    assert p.function == "goto_barcode_completed"
    assert p.line_no == 929
    assert p.message.startswith("butler_id=200")


def test_parses_info_and_warning_levels_identically_structured():
    for level in ("info", "warning", "error"):
        raw = f'2026-07-27 00:00:00.000 [{level}][<0.1.0>] --- mod:fun:{{1,1}}: hello'
        p = parse_line(raw)
        assert p is not None
        assert p.level == level


def test_unparseable_line_returns_none_not_raise():
    assert parse_line("this is not a lager line at all") is None


def test_parse_lines_skips_bad_lines_without_aborting():
    lines = [
        '2026-07-27 00:00:00.000 [debug][<0.1.0>] --- mod:fun:{1,1}: ok1\n',
        "garbage line in the middle\n",
        '2026-07-27 00:00:01.000 [debug][<0.1.0>] --- mod:fun:{2,1}: ok2\n',
    ]
    parsed = list(parse_lines(lines))
    assert len(parsed) == 2
    assert parsed[0].message == "ok1"
    assert parsed[1].message == "ok2"
