"""
Day 3 orchestrator: wires together everything from Day 1, Day 2, and Day 3
into one turn-taking conversation agent.

    conversation_memory.py    (Day 3, Task 3)  -> what does the agent know so far
    objection_handler.py      (Day 3, Task 4)  -> is this an objection, what's the strategy
    structured_retrieval.py   (Day 2)          -> exact facts (price, availability, schools,
                                                   hospitals, developer reputation, market data)
    recommendation_engine.py  (Day 2)          -> ranked property matches
    rag_pipeline.py           (Day 2)          -> semantic search over brochures/descriptions/FAQs
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
from voice_pipeline import run_voice_turn, generate_llm_reply_stream

import recommendation_engine  # Day 2
import rag_pipeline  # Day 2
from structured_retrieval import (  # Day 2
    get_property_by_id, get_nearby_schools, get_nearby_hospitals,
    get_developer_by_id, get_location_info, get_payment_plans,
)

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


def _build_focus_property_context(focus_property: dict | None) -> tuple[str, str, str, str]:
    """Nearby schools/hospitals, developer reputation, and location market data for
    whichever property is currently in focus (explicitly mentioned, else top
    recommendation). Returns (schools_text, hospitals_text, developer_text, location_text)."""
    schools_text = hospitals_text = "None found"
    developer_text = location_text = "Not available"

    if not focus_property:
        return schools_text, hospitals_text, developer_text, location_text

    location_id = focus_property.get("location_id")
    developer_id = focus_property.get("developer_id")

    if location_id is not None:
        schools = get_nearby_schools(location_id)
        if schools:
            schools_text = "\n".join(
                f"- {s['school_name']} ({s['level']}, {s['distance_km']}km away)" for s in schools
            )

        hospitals = get_nearby_hospitals(location_id)
        if hospitals:
            hospitals_text = "\n".join(
                f"- {h['hospital_name']} ({h['distance_km']}km away, "
                f"{'emergency available' if h['emergency_available'] else 'no emergency care'})"
                for h in hospitals
            )

        loc_info = get_location_info(location_id)
        if loc_info:
            location_text = (
                f"Average price per marla: {_format_price(loc_info['avg_price_per_marla_pkr'])}, "
                f"price trend: {loc_info['price_trend']}"
            )

    if developer_id is not None:
        dev = get_developer_by_id(developer_id)
        if dev:
            developer_text = (
                f"{dev['developer_name']}, founded {dev['founded_year']}, "
                f"{dev['completed_projects']} completed projects, "
                f"reputation score {dev['reputation_score']}/5"
            )

    return schools_text, hospitals_text, developer_text, location_text


def _build_prompt_context(customer_text: str, memory: ConversationMemory) -> str:
    """Builds the user prompt (objection strategy + recommendations + memory + history)
    shared by both the blocking and streaming reply paths."""

    objection_category = detect_objection(customer_text)

    strategy = None
    if objection_category:
        strategy = build_strategy(
            objection_category,
            memory.slots.decline_count,
        )

    candidates = recommendation_engine.recommend_properties(
        **memory.as_recommendation_kwargs(),
        top_n=3,
    )

    if candidates:
        memory.record_shown_properties(candidates)

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

    focus_property = property_info or (candidates[0] if candidates else None)
    schools_text, hospitals_text, developer_text, location_text = _build_focus_property_context(focus_property)

    payment_plans = get_payment_plans()
    payment_plans_text = "\n".join(
        f"- {p['plan_name']}: {p['down_payment_pct']}% down, "
        f"{p['duration_years']} years, {p['installment_frequency']} installments"
        for p in payment_plans
    ) or "Not available"

    rag_hits = rag_pipeline.retrieve(rag_pipeline.get_collection(), customer_text, top_k=3)
    rag_text = "\n\n".join(
        f"[{h['metadata']['source']}] {h['text'][:500]}" for h in rag_hits
    ) or "No relevant reference material found"

    memory_context = f"""
        Budget: {memory.slots.budget}
        City: {memory.slots.city}
        Area: {memory.slots.area}
        Bedrooms: {memory.slots.bedrooms}
        Purpose: {memory.slots.purpose}
        Declines: {memory.slots.decline_count}
        """

    return f"""
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

        Nearby Schools:
        {schools_text}

        Nearby Hospitals:
        {hospitals_text}

        Developer Info:
        {developer_text}

        Location Market Data:
        {location_text}

        Payment Plans Available:
        {payment_plans_text}

        Reference Material (brochures/descriptions/FAQs, may not all be relevant to this message):
        {rag_text}

        Conversation History:
        {history}

        Instructions:

    - Use ONLY the information provided above (properties, schools, hospitals,
      developer, location, payment plans, reference material).
    - Never invent prices, amenities, availability, or facts not given above.
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


_STOP_PUSHING_REPLY = (
    "Ji theek hai sir, koi masla nahi. Jab bhi aap ready hon, hum yahan hain. Aap ka din acha guzre."
)
_LLM_ERROR_REPLY = (
    "Maazrat, iss waqt system temporarily unavailable hai. Thori dair baad dobara try karein."
)


def _generate_reply(customer_text: str, memory: ConversationMemory) -> tuple[str, bool]:
    """Blocking reply generation. Used by the offline-test path (voice_pipeline.py)."""

    if should_stop_pushing(memory.slots.decline_count):
        return _STOP_PUSHING_REPLY, False

    user_prompt = _build_prompt_context(customer_text, memory)

    print("\n===== PROMPT SENT TO LLM =====")
    print(user_prompt)
    try:
        response = llm_client.chat.completions.create(
            model="smart", temperature=0.6,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + PERSONA},
                {"role": "user", "content": user_prompt},
            ],
        )
        reply = response.choices[0].message.content.strip()
        return reply, True
    except Exception as e:
        print("\n========== LLM ERROR ==========")
        print(e)
        return _LLM_ERROR_REPLY, False


def _generate_reply_stream(customer_text: str, memory: ConversationMemory):
    """Streaming reply generation for the live call path: yields (sentence, latency_ms)
    so TTS can start on the first sentence while the LLM is still generating the rest."""

    if should_stop_pushing(memory.slots.decline_count):
        yield _STOP_PUSHING_REPLY, 0
        return

    user_prompt = _build_prompt_context(customer_text, memory)

    print("\n===== PROMPT SENT TO LLM (stream) =====")
    print(user_prompt)
    try:
        yield from generate_llm_reply_stream(
            user_prompt, system_prompt=SYSTEM_PROMPT + "\n\n" + PERSONA
        )
    except RuntimeError as e:
        print("\n========== LLM STREAM ERROR ==========")
        print(e)
        yield _LLM_ERROR_REPLY, 0


def run_turn(customer_text: str, memory: ConversationMemory,
             behaviors: SpeechBehaviorLayer, interrupted: bool = False,
             output_dir: str = None):
    """Runs one full customer -> agent turn. Reply generation streams so TTS
    starts on the first sentence while the LLM is still generating the rest —
    the filler/hesitation opener plays immediately and covers that wait.

    customer_text must already be transcribed text, not an audio path/bytes —
    memory is updated from it directly, before run_voice_turn() would do any
    STT. output_dir, if given, is where the agent's TTS audio gets saved
    (passed through to run_voice_turn(); defaults to GENERATED_AUDIO_DIR).
    """
    tts_kwargs = {"output_dir": output_dir} if output_dir else {}

    if interrupted:
        ack = behaviors.handle_interruption()
        memory.add_turn("agent", ack)
        return ack, None

    memory.add_turn("customer", customer_text)
    memory.update_from_customer_text(customer_text)

    if should_stop_pushing(memory.slots.decline_count):
        report, _ = run_voice_turn(customer_text, _STOP_PUSHING_REPLY, **tts_kwargs)
        memory.add_turn("agent", _STOP_PUSHING_REPLY)
        return _STOP_PUSHING_REPLY, report

    opener_parts = []
    filler = behaviors.maybe_thinking_filler()
    if filler:
        opener_parts.append(filler)
    opener_parts.append(behaviors.hesitation_for_tool_call())

    def full_stream():
        for opener in opener_parts:
            yield opener, 0
        yield from _generate_reply_stream(customer_text, memory)
        laugh = behaviors.maybe_light_laughter(context_is_light=False)
        if laugh:
            yield laugh, 0

    report, sentences = run_voice_turn(customer_text, agent_reply_stream=full_stream(), **tts_kwargs)
    memory.add_turn("agent", report.reply_text)

    return report.reply_text, report


# ---------- Live microphone conversation loop (commented out) ----------
#
# Not wired into the scripted __main__ demo below. run_turn() needs
# already-transcribed text (it updates memory from customer_text directly,
# before any STT would happen) — so a live-mic version has to do STT
# explicitly first, then hand the transcript to run_turn(), same pattern as
# full_pipeline_test/run_full_pipeline_test.py uses for pre-recorded audio.
# Needs record_microphone_audio() uncommented in voice_pipeline.py first
# (and `pip install sounddevice`).
#
# from voice_pipeline import record_microphone_audio, stt_transcribe
#
# def run_live_mic_conversation(turns: int = 5, seconds_per_turn: float = 5.0):
#     memory = ConversationMemory()
#     behaviors = SpeechBehaviorLayer()
#
#     for i in range(turns):
#         audio_bytes, mimetype = record_microphone_audio(duration_s=seconds_per_turn)
#         transcript, stt_ms = stt_transcribe(audio_bytes, mimetype=mimetype)
#         print(f"CUSTOMER (transcribed): {transcript!r}  [stt: {stt_ms}ms]")
#
#         if not transcript.strip():
#             print("  (no speech detected, skipping turn)")
#             continue
#
#         spoken, report = run_turn(transcript, memory, behaviors)
#         print(f"AGENT: {spoken}")
#         if report:
#             print(f"  [latency: {report.total_first_audio_ms}ms]")


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
