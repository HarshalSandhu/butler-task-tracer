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


def test_completed_when_relay_pps_task_own_completion_marker_present():
    # Real line from a live relay_pps_task trace (task 70f0fa18...) that the
    # generic pgsql "Delete Request with Task key" marker never fires for --
    # without this, a task that unambiguously finished per its own log was
    # reported "incomplete".
    messages = [
        "some ordinary progress line",
        'relay_pps_task:set_status: butler_id=210 #relay_pps_task_delete: deleting '
        'relay_pps_task <<"70f0fa18-c9d9-4992-b209-0225654bf05f">> because status is complete',
        'Relay Pps task: <<"70f0fa18-c9d9-4992-b209-0225654bf05f">> complete, for HTM: 210',
    ]
    assert classify(messages) == TaskStatus.COMPLETED


def test_completed_when_relay_group_task_own_completion_marker_present():
    # Real line shape from relay_group_subtasks: the *executed* status
    # transition, not the planned SubTask_list dump (which always lists
    # this as a future step regardless of whether it ran).
    messages = [
        "The Current SubTask is : {subtask,set_relay_group_task_status,"
        "set_relay_group_task_status,[complete]}",
    ]
    assert classify(messages) == TaskStatus.COMPLETED


def test_completed_wins_even_if_an_earlier_abandon_line_exists():
    # e.g. a bot briefly abandoned a subtask then the task still completed
    # later - success should win over a stale failure signal.
    messages = [
        "Abandoning the current_subtask as there is new schedule with new task: x",
        'Delete Request with Task key <<"task-1">>',
    ]
    assert classify(messages) == TaskStatus.COMPLETED
