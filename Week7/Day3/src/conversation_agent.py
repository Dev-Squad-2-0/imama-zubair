"""
Day 3 orchestrator: wires together everything from Day 1, Day 2, and Day 3
into one turn-taking conversation agent.

    conversation_memory.py    (Day 3, Task 3)  -> what does the agent know so far
    objection_handler.py      (Day 3, Task 4)  -> is this an objection, what's the strategy
    structured_retrieval.py   (Day 2)          -> exact facts (price, availability)
    recommendation_engine.py  (Day 2)          -> ranked property matches
    speech_behaviors.py       (Day 3, Task 2)  -> fillers, hesitation, acknowledgements
    voice_pipeline.py         (Day 3, Task 1)  -> streaming + latency

"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversation_memory import ConversationMemory
from objection_handler import detect_objection, build_strategy, should_stop_pushing
from speech_behaviors import SpeechBehaviorLayer
from voice_pipeline import run_voice_turn

import recommendation_engine  # Day 2
from structured_retrieval import get_property_by_id  # Day 2

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

llm_client = OpenAI(
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY")
)

#prompts and persona
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "prompts", "system_prompt.md"), encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

with open(os.path.join(ROOT, "persona", "urdulish_persona.md"), encoding="utf-8") as f:
    PERSONA = f.read()

def _format_price(pkr: int) -> str:
    crore = pkr // 10_000_000
    remainder = pkr % 10_000_000
    lakh = remainder // 100_000
    parts = []
    if crore:
        parts.append(f"{crore} crore")
    if lakh:
        parts.append(f"{lakh} lakh")
    return " ".join(parts) if parts else f"{pkr} PKR"


def _extract_mentioned_property_id(customer_text: str) -> int | None:
    """Picks up an explicit property reference like "property 15" or
    "property #15" in the customer's text, so a direct follow-up question
    ("tell me more about property 15") can be answered with exact structured
    data. get_property_by_id() takes an int id, not free text, so this is
    needed before calling it — most turns won't mention an id at all and
    that's expected (recommend_properties() already covers the general
    "what's available" case)."""
    m = re.search(r"property\s*(?:number|no\.?|#)?\s*(\d+)", customer_text.lower())
    return int(m.group(1)) if m else None


def _generate_reply(customer_text: str, memory: ConversationMemory) -> tuple[str, bool]:
    """
    Generates the next reply using the LLM while keeping recommendation,
    objection detection and memory outside the model.
    """

    if should_stop_pushing(memory.slots.decline_count):
        return (
            "Ji theek hai sir, koi masla nahi. Jab bhi aap ready hon, hum yahan hain. Aap ka din acha guzre.",
            False,
        )

    # ---------------------------
    # Detect objection
    # ---------------------------
    objection_category = detect_objection(customer_text)

    strategy = None
    if objection_category:
        strategy = build_strategy(
            objection_category,
            memory.slots.decline_count,
        )

    # ---------------------------
    # Retrieve recommendations
    # ---------------------------
    candidates = recommendation_engine.recommend_properties(
        **memory.as_recommendation_kwargs(),
        top_n=3,
    )

    if candidates:
        memory.record_shown_properties(candidates)

    recommendation_text = ""

    if candidates:
        recommendation_text = "\n".join(
            [
                (
                    f"- {c['title']}\n"
                    f"  Price: {_format_price(c['price_pkr'])}\n"
                    f"  Bedrooms: {c['bedrooms']}\n"
                    f"  Location: {c['city']} - {c['area']}\n"
                    f"  Amenities: {c['amenities']}"
                )
                for c in candidates
            ]
        )
    else:
        recommendation_text = "No matching properties found."


    history = "\n".join(
    f"{turn['speaker'].capitalize()}: {turn['text']}"
    for turn in memory.history[-10:]
)
    property_info = None
    pid = _extract_mentioned_property_id(customer_text)
    if pid is not None:
        property_info = get_property_by_id(pid)

    memory_context = f"""
        Budget: {memory.slots.budget}
        City: {memory.slots.city}
        Area: {memory.slots.area}
        Bedrooms: {memory.slots.bedrooms}
        Purpose: {memory.slots.purpose}
        Declines: {memory.slots.decline_count}
        """
    
    # ---------------------------
    # Build context
    # ---------------------------
    user_prompt = f"""
        Customer Message:
        {customer_text}

        Conversation Memory:
        {memory_context}

        Detected Objection:
        {objection_category}

        Objection Strategy:
        {strategy}

        Recommended Properties:
        {recommendation_text}

        Property Information:
        {property_info}

        Conversation History:
        {history}

        Instructions:

    - Use ONLY the provided property information.
    - Never invent prices, amenities or availability.
    - If information is unavailable, say so honestly.
    - Maintain conversation continuity using the memory.
    - Respond in natural Pakistani Urdulish.
    - Sound like an experienced but friendly real estate sales executive.
    - Keep responses conversational instead of robotic.
    - If multiple properties match, recommend the strongest one first and briefly mention alternatives.
    - Handle objections naturally instead of arguing.
    - Keep replies under 120 words unless the customer explicitly asks for more detail.
    - This reply is spoken aloud by text-to-speech, not read on screen: write in
      plain flowing spoken sentences only. Never use markdown (no **bold**,
      no numbered or bulleted lists), never use emojis or emoticons.
    - Write only in Roman Urdu/English (UrduLish) or Urdu script mixed with
      English, matching the persona's examples. Never use Devanagari/Hindi
      script — this is a Pakistani Urdu voice, it cannot speak Devanagari.
        """

    print("\n===== PROMPT SENT TO LLM =====")
    print(user_prompt)
    # ---------------------------
    # Call LLM
    # ---------------------------
    try:
        response = llm_client.chat.completions.create(
        model="smart",temperature=0.6,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n\n" + PERSONA,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )

        
        reply = response.choices[0].message.content.strip()
        return reply, True
    except Exception as e:
        print("\n========== LLM ERROR ==========")
        print(e)
        return (
            "Maazrat, iss waqt system temporarily unavailable hai. "
            "Thori dair baad dobara try karein.",
            False,
        )


def run_turn(customer_text: str, memory: ConversationMemory,
             behaviors: SpeechBehaviorLayer, interrupted: bool = False):
    """Runs one full customer -> agent turn: memory update, reply composition,
    speech behavior wrapping, and voice pipeline latency simulation."""

    if interrupted:
        ack = behaviors.handle_interruption()
        memory.add_turn("agent", ack)
        return ack, None

    memory.add_turn("customer", customer_text)
    memory.update_from_customer_text(customer_text)

    # print(memory.history)

    reply_text, used_tool = _generate_reply(customer_text, memory)
    is_reasoning_heavy = used_tool

    spoken_text = behaviors.wrap_reply(
        reply_text, used_tool=used_tool, is_reasoning_heavy=is_reasoning_heavy
    )

    report, sentences = run_voice_turn(customer_text, spoken_text)
    memory.add_turn("agent", spoken_text)

    return spoken_text, report


if __name__ == "__main__":
    memory = ConversationMemory()
    behaviors = SpeechBehaviorLayer(seed=3)

    turns = [
        "Assalam o alaikum, mujhe ghar chahiye Lahore mein.",
        "Budget 3 crore hai.",
        "DHA mein kya options hain?",
        "Yeh property thori mehngi hai.",
        "Us se sasti koi option?",
    ]

    for t in turns:
        print(f"CUSTOMER: {t}")
        spoken, report = run_turn(t, memory, behaviors)
        print(f"AGENT: {spoken}")
        if report:
            print(f"  [latency: {report.total_first_audio_ms}ms, "
                  f"{'within' if report.under_budget else 'OVER'} budget]")
        print()
