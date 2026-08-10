"""
Day 3 - Task 2: Natural Speech Behaviors

Adds the small verbal habits that make a voice agent sound like a real person
on the phone instead of a script reader: fillers, hesitation before a tool
call, thinking pauses, light laughter, and acknowledgements.

This pulls its phrase pool from urdulish_persona.md (Day 1) rather than
inventing a new voice. Nothing here is a new persona, it's just organizing
the existing hesitation/acknowledgement phrases by WHEN to use them during
a live call, plus handling interruptions (barge-in).

Design rule: these are inserted sparingly and probabilistically, not on
every single turn. A real agent doesn't say "Ek second sir" before every
sentence. Overusing fillers is exactly what makes a bot sound scripted.
"""

import random


# ---------- Phrase pools (sourced from urdulish_persona.md) ----------

FILLERS_THINKING = [
    "Hmm...",
    "Acha...",
    "Dekhiye...",
]

# These are ONLY for audio that is played WHILE a genuinely slow tool is
# still running. They must never be blindly prepended to the final answer
# after the tool has already completed; doing that is what made the agent
# repeat the same three robotic lines on ordinary turns.
HESITATION_TOOL_CALL = {
    "calendar": [
        "Ek moment, calendar check kar raha hoon.",
        "Ji, availability dekh leta hoon.",
        "Theek hai, time confirm kar leta hoon.",
    ],
    "property_search": [
        "Ji, options dekh raha hoon.",
        "Ek moment, matching properties check karta hoon.",
        "Theek hai, available options dekh leta hoon.",
    ],
    "rag": [
        "Ji, iski detail confirm kar leta hoon.",
        "Ek moment, exact information dekh leta hoon.",
    ],
    "generic": [
        "Ek moment.",
        "Ji, check kar leta hoon.",
    ],
}

ACKNOWLEDGEMENTS = [
    "Ji bilkul samajh gaya.",
    "Achi baat hai, yeh bhi ek acha option hai.",
    "Sahi keh rahe hain aap.",
    "Ji zaroor.",
]

LIGHT_LAUGHTER = [
    "haha, ji bilkul",
    "(halki hasi) theek hai sir",
]

INTERRUPTION_ACKNOWLEDGEMENT = [
    "Ji sir, boliye.",
    "Ji, main sun raha hoon.",
    "Sorry sir, aap boliye pehle.",
]


class SpeechBehaviorLayer:
    """
    Wraps agent text with natural speech behaviors before it goes to TTS.
    Call sites decide WHEN to invoke each behavior; this class only decides
    WHICH phrase to use and applies probability so it doesn't fire every
    single turn.
    """

    def __init__(
        self,
        filler_probability=0.0,
        ack_probability=0.0,
        tool_hesitation_probability=0.0,
        seed=None,
    ):
        # Low probabilities are intentional. The LLM already writes natural
        # UrduLish; this layer should add texture, not become a second script.
        self.filler_probability = filler_probability
        self.ack_probability = ack_probability
        self.tool_hesitation_probability = tool_hesitation_probability
        self._rng = random.Random(seed)
        self._last_behavior_phrase = None

    def maybe_thinking_filler(self):
        """Short 'Hmm... / Acha...' before a reasoning-heavy answer."""
        if self._rng.random() < self.filler_probability:
            return self._rng.choice(FILLERS_THINKING)
        return None

    def _choose_nonrepeating(self, phrases):
        choices = [p for p in phrases if p != self._last_behavior_phrase] or list(phrases)
        phrase = self._rng.choice(choices)
        self._last_behavior_phrase = phrase
        return phrase

    def hesitation_for_tool_call(self, tool_name: str = None, force: bool = False):
        """Return a short wait phrase only when the caller can actually hear
        it WHILE a slow tool is running.

        The synchronous LangGraph path receives the tool result before it
        constructs the final reply, so graph.py intentionally calls this
        with used_tool=False. A future streaming implementation can call
        this method before starting a slow Calendar/RAG/search operation.
        """
        if not force and self._rng.random() >= self.tool_hesitation_probability:
            return None
        pool = HESITATION_TOOL_CALL.get(tool_name or "generic", HESITATION_TOOL_CALL["generic"])
        return self._choose_nonrepeating(pool)

    def maybe_acknowledgement(self):
        if self._rng.random() < self.ack_probability:
            return self._rng.choice(ACKNOWLEDGEMENTS)
        return None

    def maybe_light_laughter(self, context_is_light: bool):
        """Only offered when the conversational context is genuinely light
        (e.g. customer made a small joke or a warm comment). Never used
        around price objections, complaints, or anything sensitive."""
        if context_is_light and self._rng.random() < 0.25:
            return self._rng.choice(LIGHT_LAUGHTER)
        return None

    def handle_interruption(self):
        """Called when barge-in is detected (customer started speaking while
        TTS audio was still playing). Returns the phrase the agent should
        say, and the caller (conversation_agent.py) is responsible for
        actually stopping the in-flight TTS stream."""
        return self._rng.choice(INTERRUPTION_ACKNOWLEDGEMENT)

    def wrap_reply(
        self,
        reply_text: str,
        used_tool: bool,
        is_reasoning_heavy: bool,
        context_is_light: bool = False,
        tool_name: str = None,
    ):
        """Apply only light, optional speech texture.

        Crucially, a completed tool call does NOT automatically earn a wait
        phrase. ``used_tool`` should be True only when this text is actually
        being emitted while the tool is still in flight.
        """
        parts = []

        if is_reasoning_heavy:
            filler = self.maybe_thinking_filler()
            if filler:
                parts.append(filler)

        if used_tool:
            wait_phrase = self.hesitation_for_tool_call(tool_name=tool_name)
            if wait_phrase:
                parts.append(wait_phrase)

        parts.append(reply_text.strip())

        laugh = self.maybe_light_laughter(context_is_light)
        if laugh:
            parts.append(laugh)

        return " ".join(part for part in parts if part)


if __name__ == "__main__":
    layer = SpeechBehaviorLayer(seed=7)

    print("-- Reply after a tool call (RAG/SQL lookup), reasoning heavy --")
    print(layer.wrap_reply(
        "DHA Phase 6 mein hamare paas 10 marla corner house available hai, 3 crore 20 lakh ka.",
        used_tool=True, is_reasoning_heavy=True,
    ))

    print("\n-- Simple acknowledgement, no tool call --")
    ack = layer.maybe_acknowledgement()
    print(ack)

    print("\n-- Interruption mid-sentence --")
    print(layer.handle_interruption())
