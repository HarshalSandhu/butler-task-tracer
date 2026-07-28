from app.models import TaskStatus
from app.parsers.terminal_state import classify


def test_completed_when_success_marker_present():
    messages = [
        "some line",
        'Delete Request with Task key <<"task-1">>',
    ]
    assert classify(messages) == TaskStatus.COMPLETED


def test_failed_when_deassigned_without_success():
    messages = ["Deassigning task: task-1 for butler: 200"]
    assert classify(messages) == TaskStatus.FAILED


def test_failed_when_abandoned_without_success():
    messages = [
        "Abandoning the current_subtask as there is new schedule with new task: task-2"
    ]
    assert classify(messages) == TaskStatus.FAILED


def test_incomplete_when_neither_marker_present():
    messages = ["some ordinary progress line", "another line"]
    assert classify(messages) == TaskStatus.INCOMPLETE


def test_completed_wins_even_if_an_earlier_abandon_line_exists():
    # e.g. a bot briefly abandoned a subtask then the task still completed
    # later - success should win over a stale failure signal.
    messages = [
        "Abandoning the current_subtask as there is new schedule with new task: x",
        'Delete Request with Task key <<"task-1">>',
    ]
    assert classify(messages) == TaskStatus.COMPLETED
