from app.parsers.id_resolver import find_request_id, resolve_task_id_from_request_id


def test_find_request_id_from_triggered_line():
    lines = [
        '... #Triggered task creation: RequestId <<"abc-123">>\n',
        "... unrelated line\n",
    ]
    assert find_request_id(lines) == "abc-123"


def test_find_request_id_returns_none_when_absent():
    assert find_request_id(["no request id here\n"]) is None


def test_resolve_via_task_created_line():
    lines = [
        '... #Task created , Task-type relay_pps_task Task <<"task-1">> '
        'Request-Id <<"req-1">> DestinationType <<"pps">>\n',
    ]
    resolved = resolve_task_id_from_request_id("req-1", lines)
    assert resolved is not None
    assert resolved.task_id == "task-1"
    assert resolved.task_type == "relay_pps_task"
    assert resolved.request_id == "req-1"


def test_resolve_via_save_array_fallback():
    lines = [
        '... #saving Rack Transport Request ["req-1","created","tote",'
        '"{}","relay_pps_task","task-1","put","pps",...]\n',
    ]
    resolved = resolve_task_id_from_request_id("req-1", lines)
    assert resolved is not None
    assert resolved.task_id == "task-1"
    assert resolved.task_type == "relay_pps_task"


def test_resolve_returns_none_when_task_not_yet_created():
    lines = ['... #Triggered task creation: RequestId <<"req-1">>\n']
    assert resolve_task_id_from_request_id("req-1", lines) is None


def test_resolve_ignores_lines_for_a_different_request_id():
    lines = [
        '... #Task created , Task-type relay_pps_task Task <<"task-1">> '
        'Request-Id <<"some-other-request">> DestinationType <<"pps">>\n',
    ]
    assert resolve_task_id_from_request_id("req-1", lines) is None
