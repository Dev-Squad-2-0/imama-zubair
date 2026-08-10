from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parent


class FakeStore:
    def __init__(self):
        self._sessions = {"old": {"session_id": "old"}}


class FakeGraphWithStore:
    def __init__(self):
        self._session_store = FakeStore()


class FakeGraphWithReset:
    def __init__(self):
        self.called = False

    def reset_sessions(self):
        self.called = True


class RunnerCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Extract helper source without importing the full runner/agent stack.
        source = (ROOT / "run_prompt_injection_suite.py").read_text(encoding="utf-8")
        start = source.index("def reset_graph_sessions_compat")
        end = source.index("\ndef main():", start)
        ns = {}
        exec(source[start:end], ns)
        cls.reset = staticmethod(ns["reset_graph_sessions_compat"])

    def test_works_with_current_session_store_graph(self):
        graph = FakeGraphWithStore()
        self.reset(graph)
        self.assertEqual(graph._session_store._sessions, {})

    def test_works_with_old_reset_sessions_graph(self):
        graph = FakeGraphWithReset()
        self.reset(graph)
        self.assertTrue(graph.called)

    def test_works_without_any_reset_api(self):
        class BareGraph:
            pass
        self.reset(BareGraph())


if __name__ == "__main__":
    unittest.main()
