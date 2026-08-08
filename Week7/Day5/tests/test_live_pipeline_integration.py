"""
Week 7 - Day 5 (extension): integration test for the two front ends onto
the one LangGraph brain (graph.run_turn).

conversation_agent.py is now a TEXT front end (no mic) over graph.run_turn,
and live_voice_pipeline.py is the mic/speaker front end over the same
graph.run_turn - see conversation_agent.py's module docstring. This file
verifies both front ends wire correctly onto that one orchestrator: session
continuity (every turn reaches run_turn() under the same session_id),
replies get surfaced correctly (printed for text, synthesized+played for
live), and each loop stops on goodbye / an empty reply rather than
spinning forever.

No real audio hardware, Deepgram, Fish Audio, LLM gateway, Google
Calendar, or Gmail calls are made. graph.run_turn() itself is mocked here
in both classes - Day 5's node/routing logic already has its own coverage
elsewhere; this file's only job is the front-end wiring.

Run:
    cd Day5/src
    python test_live_pipeline_integration.py
    # or: python -m pytest test_live_pipeline_integration.py -v
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _stub_sentence_transformers_if_needed():
    """rag_pipeline.py loads a real SentenceTransformer model at IMPORT
    time (embedding_model = SentenceTransformer(...)), which needs to
    download from huggingface.co on first use. That's a non-issue on a dev
    machine with the model already cached (the normal case for this
    project), but breaks this test with a confusing OSError deep inside
    transformers' internals on a machine with no network (CI, sandboxes).
    This only kicks in as a fallback if the real import fails - it does
    nothing, and changes nothing, on a machine where the real import
    already works."""
    try:
        import conversation_agent  # noqa: F401
        return
    except Exception:
        pass

    for mod in ("conversation_agent", "rag_pipeline", "graph", "nodes",
                "sentence_transformers", "chromadb"):
        sys.modules.pop(mod, None)

    st_stub = types.ModuleType("sentence_transformers")

    class _FakeSentenceTransformer:
        def __init__(self, *a, **k):
            pass

        def encode(self, texts, **k):
            n = len(texts) if isinstance(texts, list) else 1
            return [[0.0] * 8 for _ in range(n)]

    st_stub.SentenceTransformer = _FakeSentenceTransformer
    sys.modules["sentence_transformers"] = st_stub


_stub_sentence_transformers_if_needed()

import conversation_agent as ca  # noqa: E402
import graph  # noqa: E402


# ---------- shared fakes for the external boundaries ----------

class _ScriptedMic:
    """Stand-in for live_audio_io.listen_for_utterance(): returns each
    transcript in `turns`, in order, then None forever (silence/timeout)
    so a loop that outlives the script doesn't spin forever."""

    def __init__(self, turns):
        self.turns = list(turns)

    def __call__(self, timeout_s=None):
        if self.turns:
            return self.turns.pop(0)
        return None


class _RecordingSpeaker:
    """Stand-in for live_audio_io.play_audio_bytes(): counts calls and
    remembers what it was asked to play, instead of touching a real
    speaker/pygame mixer."""

    def __init__(self):
        self.calls = []

    def __call__(self, audio_bytes):
        self.calls.append(audio_bytes)


def _fake_tts_stream_audio(text, voice_id=None):
    """Stand-in for voice_pipeline.tts_stream_audio(): returns a tiny fake
    'audio' payload instead of calling Fish Audio - fast, free, offline."""
    return f"FAKE_AUDIO[{text}]".encode("utf-8"), 5


# ---------- conversation_agent.py backend (text, no mic) ----------

class TextConversationAgentIntegrationTest(unittest.TestCase):
    """conversation_agent.run_scripted_conversation(): mocks graph.run_turn()
    itself (Day 5's node/routing/booking logic already has its own coverage)
    and checks the front-end wiring: every scripted utterance reaches
    run_turn() under the same session_id (SessionStore continuity), every
    turn's reply is captured in the returned transcript, and the loop stops
    on goodbye / an empty reply instead of running past the script."""

    def test_transcripts_routed_to_run_turn_with_session_continuity(self):
        seen_calls = []

        def fake_run_turn(session_id, customer_text=""):
            seen_calls.append((session_id, customer_text))
            if customer_text == "":
                return "Assalam o alaikum, RealEstate Hub mein khush aamdeed.", []
            if "khuda hafiz" in customer_text.lower():
                return "Khuda hafiz, aap ka din acha guzre.", [{"node_name": "goodbye"}]
            return f"Ji, samajh gaya: {customer_text}", [{"node_name": "recommendation"}]

        scripted_turns = [
            "Assalam o alaikum, mera naam Ahmed hai, mera number 0300-1234567 hai.",
            "Budget 3 crore hai, DHA Phase 6 mein ghar chahiye.",
            "Shukriya, khuda hafiz.",
        ]

        with patch.object(graph, "run_turn", side_effect=fake_run_turn):
            results = ca.run_scripted_conversation(
                scripted_turns, session_id="test-session-001", verbose=False
            )

        # every call went through under the SAME session_id (SessionStore continuity)
        session_ids = {c[0] for c in seen_calls}
        self.assertEqual(session_ids, {"test-session-001"})

        # greeting call (empty text) + one call per scripted transcript
        self.assertEqual(len(seen_calls), 1 + 3)
        self.assertEqual(seen_calls[0][1], "")
        self.assertEqual(seen_calls[1][1], scripted_turns[0])

        # returned transcript has greeting + all 3 turns, in order, with replies attached
        self.assertEqual(len(results), 1 + 3)
        self.assertEqual(results[1]["customer_text"], scripted_turns[0])
        self.assertEqual(results[1]["agent_reply"], f"Ji, samajh gaya: {scripted_turns[0]}")

        # loop stopped after the goodbye turn, not stuck expecting a 4th turn
        self.assertEqual(results[-1]["customer_text"], scripted_turns[-1])

    def test_empty_reply_ends_the_scripted_conversation(self):
        """A turn that produces no reply text should end the conversation,
        not keep feeding it the rest of the script."""
        def fake_run_turn(session_id, customer_text=""):
            if customer_text == "":
                return "Khush aamdeed.", []
            return "", []  # simulate a failure/empty reply

        with patch.object(graph, "run_turn", side_effect=fake_run_turn):
            results = ca.run_scripted_conversation(
                ["Kuch bhi.", "Yeh nahi chalna chahiye."],
                session_id="test-session-002", verbose=False,
            )

        # stopped right after the first (empty-reply) turn - second scripted
        # utterance never got sent through run_turn at all
        self.assertEqual(len(results), 2)  # greeting + the one empty-reply turn
        self.assertEqual(results[-1]["customer_text"], "Kuch bhi.")
        self.assertEqual(results[-1]["agent_reply"], "")


# ---------- graph.py / live_voice_pipeline.py (unified LangGraph backend) ----------

class LiveGraphIntegrationTest(unittest.TestCase):
    """live_voice_pipeline.run_live_session(): mocks graph.run_turn() itself
    (Day 5's node/routing logic already has its own coverage) plus the
    external mic/speaker/TTS boundaries, and checks the wiring: every
    transcript reaches run_turn() under the same session_id (proving
    SessionStore continuity is being used correctly), every non-empty reply
    gets synthesized and played, and the loop stops on goodbye."""

    def test_transcripts_routed_to_run_turn_and_spoken(self):
        import graph
        import live_voice_pipeline as lvp

        scripted_mic = _ScriptedMic([
            "Assalam o Alaikum, mera naam Sara hai.",
            "Budget 2 crore hai.",
            "Shukriya, khuda hafiz.",
        ])
        speaker = _RecordingSpeaker()
        seen_calls = []

        def fake_run_turn(session_id, customer_text=""):
            seen_calls.append((session_id, customer_text))
            if customer_text == "":
                return "Assalam o alaikum, RealEstate Hub mein khush aamdeed.", []
            if "khuda hafiz" in customer_text.lower():
                return "Khuda hafiz, aap ka din acha guzre.", []
            return f"Ji, samajh gaya: {customer_text}", []

        with patch.object(graph, "run_turn", side_effect=fake_run_turn), \
             patch("live_audio_io.listen_for_utterance", side_effect=scripted_mic), \
             patch("live_audio_io.play_audio_bytes", side_effect=speaker), \
             patch("voice_pipeline.warmup_tts", return_value=None), \
             patch("voice_pipeline.tts_stream_audio", side_effect=_fake_tts_stream_audio):

            lvp.run_live_session(session_id="test-graph-session")

        # every call went through under the SAME session_id (SessionStore continuity)
        session_ids = {c[0] for c in seen_calls}
        self.assertEqual(session_ids, {"test-graph-session"})

        # greeting call (empty text) + one call per scripted transcript
        self.assertEqual(len(seen_calls), 1 + 3)
        self.assertEqual(seen_calls[0][1], "")
        self.assertEqual(seen_calls[1][1], "Assalam o Alaikum, mera naam Sara hai.")

        # every reply (greeting + 3 turns) got synthesized and played
        self.assertEqual(len(speaker.calls), 4)

        # loop stopped after the goodbye turn, no leftover scripted transcripts
        self.assertEqual(len(scripted_mic.turns), 0)

    def test_empty_reply_ends_call(self):
        """A turn that produces no reply text should end the call, not spin
        forever waiting for more speech."""
        import graph
        import live_voice_pipeline as lvp

        scripted_mic = _ScriptedMic(["Kuch bhi.", "Yeh nahi chalna chahiye."])
        speaker = _RecordingSpeaker()

        def fake_run_turn(session_id, customer_text=""):
            if customer_text == "":
                return "Khush aamdeed.", []
            return "", []  # simulate a failure/empty reply

        with patch.object(graph, "run_turn", side_effect=fake_run_turn), \
             patch("live_audio_io.listen_for_utterance", side_effect=scripted_mic), \
             patch("live_audio_io.play_audio_bytes", side_effect=speaker), \
             patch("voice_pipeline.warmup_tts", return_value=None), \
             patch("voice_pipeline.tts_stream_audio", side_effect=_fake_tts_stream_audio):

            lvp.run_live_session(session_id="test-graph-session-2")

        # stopped after the first empty reply, second scripted transcript never consumed
        self.assertEqual(scripted_mic.turns, ["Yeh nahi chalna chahiye."])


if __name__ == "__main__":
    unittest.main(verbosity=2)
