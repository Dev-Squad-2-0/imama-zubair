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

HESITATION_TOOL_CALL = [
    "Ek second sir, main abhi availability check kar leta hoon.",
    "Bas do minute dijiye, main details nikaal raha hoon aap ke liye.",
    "Zara rukiye, main confirm kar ke batata hoon.",
]

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

    def __init__(self, filler_probability=0.35, ack_probability=0.5, seed=None):
        self.filler_probability = filler_probability
        self.ack_probability = ack_probability
        self._rng = random.Random(seed)

    def maybe_thinking_filler(self):
        """Short 'Hmm... / Acha...' before a reasoning-heavy answer."""
        if self._rng.random() < self.filler_probability:
            return self._rng.choice(FILLERS_THINKING)
        return None

    def hesitation_for_tool_call(self, tool_name: str = None):
        """Always returns a phrase - used specifically while a tool call
        (calendar check, RAG search, SQL lookup) is in flight, since the
        customer needs to hear SOMETHING during that gap or the line feels
        dead. This is the one behavior that is not probabilistic, because
        silence during a real tool-call delay reads as a dropped call."""
        return self._rng.choice(HESITATION_TOOL_CALL)

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

    def wrap_reply(self, reply_text: str, used_tool: bool, is_reasoning_heavy: bool,
                    context_is_light: bool = False):
        """
        Assembles the final spoken text for a turn:
        [optional thinking filler] [optional tool hesitation] reply [optional laughter]
        """
        parts = []

        if is_reasoning_heavy:
            filler = self.maybe_thinking_filler()
            if filler:
                parts.append(filler)

        if used_tool:
            parts.append(self.hesitation_for_tool_call())

        parts.append(reply_text)

        laugh = self.maybe_light_laughter(context_is_light)
        if laugh:
            parts.append(laugh)

        return " ".join(parts)


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
