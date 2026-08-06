"""
Day 5 - Task 2: Graph Design

Assembles the LangGraph StateGraph from nodes.py's 9 nodes. Every routing
decision is a deterministic conditional edge (see nodes.py's module
docstring for why - graph routing is never left to an LLM's judgement in
this project).

    START --(no customer_text yet: call just connected)--> greeting --> END
    START --(customer_text present)--> intent_detection
    intent_detection --(goodbye keywords / 2 declines)--> goodbye --> END
    intent_detection --(appointment_intent == book)--> booking
    intent_detection --(appointment_intent == reschedule)--> rescheduling
    intent_detection --(appointment_intent == cancel)--> cancellation
    intent_detection --(looks like a factual/FAQ question)--> rag --> END
    intent_detection --(otherwise)--> recommendation --> END
    booking/rescheduling/cancellation --(write action succeeded)--> email --> END
    booking/rescheduling/cancellation --(failed / needs clarification)--> END
"""

import os
import re
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, START, END

from state import AgentState, SessionStore
from graph_logger import get_execution_trace
import nodes


_QUESTION_WORDS = re.compile(
    r"\b(kya|kaisa|kaisi|kaise|kab|kahan|kyun|kyu|kitna|kitni|kitne|konsa|konsi|kaun|"
    r"amenities|policy|maintenance|payment\s*plan|schools?|hospitals?)\b",
    re.IGNORECASE,
)


def _looks_like_factual_question(text: str) -> bool:
    """Heuristic split between 'answer a fact' (rag_node) and 'find me a
    property' (recommendation_node) - best-effort keyword matching, same
    honest-limitations spirit as appointment_intent.py's date parser: not
    perfect NLU, but deterministic and good enough for the common case."""
    return "?" in text or bool(_QUESTION_WORDS.search(text))


def _entry_router(state: AgentState) -> str:
    return "greeting" if not state["customer_text"] else "intent_detection"


def _route_after_intent(state: AgentState) -> str:
    if nodes.is_goodbye_turn(state):
        return "goodbye"

    appointment_intent = state["intent"].get("appointment_intent")
    if appointment_intent == "book":
        return "booking"
    if appointment_intent == "reschedule":
        return "rescheduling"
    if appointment_intent == "cancel":
        return "cancellation"

    if _looks_like_factual_question(state["customer_text"]):
        return "rag"
    return "recommendation"


def _route_after_write_action(state: AgentState) -> str:
    last = state["tool_outputs"].get("last_write_action", {})
    return "email" if last.get("success") else END


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("greeting", nodes.greeting_node)
    graph.add_node("intent_detection", nodes.intent_detection_node)
    graph.add_node("rag", nodes.rag_node)
    graph.add_node("recommendation", nodes.recommendation_node)
    graph.add_node("booking", nodes.booking_node)
    graph.add_node("rescheduling", nodes.rescheduling_node)
    graph.add_node("cancellation", nodes.cancellation_node)
    graph.add_node("email", nodes.email_node)
    graph.add_node("goodbye", nodes.goodbye_node)

    graph.add_conditional_edges(START, _entry_router,
                                 {"greeting": "greeting", "intent_detection": "intent_detection"})
    graph.add_conditional_edges("intent_detection", _route_after_intent, {
        "goodbye": "goodbye", "booking": "booking", "rescheduling": "rescheduling",
        "cancellation": "cancellation", "rag": "rag", "recommendation": "recommendation",
    })
    graph.add_conditional_edges("booking", _route_after_write_action, {"email": "email", END: END})
    graph.add_conditional_edges("rescheduling", _route_after_write_action, {"email": "email", END: END})
    graph.add_conditional_edges("cancellation", _route_after_write_action, {"email": "email", END: END})

    graph.add_edge("greeting", END)
    graph.add_edge("rag", END)
    graph.add_edge("recommendation", END)
    graph.add_edge("email", END)
    graph.add_edge("goodbye", END)

    return graph.compile()


_compiled_graph = None


def _get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


_session_store = SessionStore()


def run_turn(session_id: str, customer_text: str = "") -> Tuple[str, List[dict]]:
    """Runs one turn through the compiled graph for session_id. Empty
    customer_text is a call-start/greeting invocation. Returns
    (agent_reply, node_trace) - node_trace is this turn's annotated
    execution trace from graph_logger (Task 5), ready to print or show in
    a UI."""
    state = _session_store.get_or_create(session_id)
    state["customer_text"] = customer_text
    state["turn_id"] = state.get("turn_id", 0) + 1

    result_state = _get_compiled_graph().invoke(state)

    _session_store.save(result_state)
    trace = get_execution_trace(session_id, result_state["turn_id"])
    return result_state.get("agent_reply", ""), trace


def get_session_state(session_id: str) -> Optional[AgentState]:
    return _session_store._sessions.get(session_id)


def save_graph_diagram(path: Optional[str] = None) -> str:
    """Renders the compiled graph's structure to a PNG (via LangGraph's
    Mermaid renderer) - a visual of Task 2's routing table, not something
    generated from the execution traces."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "graph_diagram.png")
    path = os.path.abspath(path)
    png_bytes = _get_compiled_graph().get_graph().draw_mermaid_png()
    with open(path, "wb") as f:
        f.write(png_bytes)
    return path


if __name__ == "__main__":
    try:
        diagram_path = save_graph_diagram()
        print(f"Graph diagram saved to: {diagram_path}\n")
    except Exception as e:
        print(f"Could not render graph diagram (non-fatal, needs network access to mermaid.ink): {e}\n")

    sid = "graph-smoke-test"

    reply, trace = run_turn(sid, "")
    print("AGENT:", reply)

    reply, trace = run_turn(
        sid,
        "Assalam o Alaikum, mera naam Ahmed hai, budget 3 crore hai, DHA Phase 6 mein ghar chahiye.",
    )
    print("AGENT:", reply)
    print(f"\nTrace for this turn ({len(trace)} node(s)):")
    for row in trace:
        print(f"  {row['node_name']} ({row['duration_ms']}ms) - {row['annotation']}")
