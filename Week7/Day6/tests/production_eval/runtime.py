import os, shutil, sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / 'src'
OUTPUT = HERE / 'output'
OUTPUT.mkdir(parents=True, exist_ok=True)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def prepare_isolated_runtime(run_id: str, mock_writes: bool = True):
    """Use production read paths but isolate CRM/trace writes for evaluation."""
    import crm_logger, graph_logger
    source_db = ROOT / 'db' / 'knowledge_base.db'
    eval_db = OUTPUT / f'eval_{run_id}.db'
    shutil.copy2(source_db, eval_db)
    crm_logger.DB_PATH = str(eval_db)
    graph_logger.DB_PATH = str(eval_db)
    crm_logger._TABLE_READY = False
    graph_logger._TABLE_READY = False

    if mock_writes:
        import nodes
        counter = {'n': 0}
        class MockTool:
            def __init__(self, fn): self.fn = fn
            def invoke(self, payload): return self.fn(payload)
        def book(payload):
            counter['n'] += 1
            return {'success': True, 'event_id': f'eval-event-{run_id}-{counter["n"]}', 'html_link': None, 'error': None}
        nodes.check_availability_tool = MockTool(lambda p: {'success': True, 'available': True, 'conflicting_events': [], 'error': None})
        nodes.book_calendar_tool = MockTool(book)
        nodes.reschedule_calendar_tool = MockTool(lambda p: {'success': True, 'event_id': p['event_id'], 'html_link': None, 'error': None})
        nodes.cancel_calendar_tool = MockTool(lambda p: {'success': True, 'event_id': p['event_id'], 'error': None})
        nodes.email_tool = MockTool(lambda p: {'success': True, 'message_id': f'eval-mail-{run_id}', 'error': None})
    return eval_db
