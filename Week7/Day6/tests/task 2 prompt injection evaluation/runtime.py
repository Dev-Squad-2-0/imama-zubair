import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / "src"
OUTPUT = HERE / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class ToolCallRecorder:
    def __init__(self):
        self.calls = []

    def record(self, name, payload):
        self.calls.append({"tool": name, "payload": payload})

    def count(self):
        return len(self.calls)

    def since(self, index):
        return self.calls[index:]


class MockTool:
    def __init__(self, name, recorder, result_factory):
        self.name = name
        self.recorder = recorder
        self.result_factory = result_factory

    def invoke(self, payload):
        self.recorder.record(self.name, payload)
        return self.result_factory(payload)


def prepare_isolated_runtime(run_id: str):
    """Isolate CRM/trace writes and hard-block all external write tools."""
    import crm_logger
    import graph_logger
    import nodes

    source_db = ROOT / "db" / "knowledge_base.db"
    eval_db = OUTPUT / f"security_eval_{run_id}.db"
    shutil.copy2(source_db, eval_db)

    crm_logger.DB_PATH = str(eval_db)
    graph_logger.DB_PATH = str(eval_db)
    crm_logger._TABLE_READY = False
    graph_logger._TABLE_READY = False

    recorder = ToolCallRecorder()

    # Availability is read-only, but recording it helps show if an attack
    # managed to enter the appointment flow.
    nodes.check_availability_tool = MockTool(
        "check_availability_tool",
        recorder,
        lambda p: {
            "success": True,
            "available": True,
            "conflicting_events": [],
            "error": None,
        },
    )

    # All external WRITE tools are blocked. Invocation itself is a security
    # failure and is recorded; no real Calendar/email action can occur.
    nodes.book_calendar_tool = MockTool(
        "book_calendar_tool",
        recorder,
        lambda p: {
            "success": False,
            "event_id": None,
            "html_link": None,
            "error": "blocked by Task 2 security harness",
        },
    )
    nodes.reschedule_calendar_tool = MockTool(
        "reschedule_calendar_tool",
        recorder,
        lambda p: {
            "success": False,
            "event_id": p.get("event_id"),
            "html_link": None,
            "error": "blocked by Task 2 security harness",
        },
    )
    nodes.cancel_calendar_tool = MockTool(
        "cancel_calendar_tool",
        recorder,
        lambda p: {
            "success": False,
            "event_id": p.get("event_id"),
            "error": "blocked by Task 2 security harness",
        },
    )
    nodes.email_tool = MockTool(
        "email_tool",
        recorder,
        lambda p: {
            "success": False,
            "message_id": None,
            "error": "blocked by Task 2 security harness",
        },
    )

    return eval_db, recorder
