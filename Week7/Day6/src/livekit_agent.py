"""
LiveKit telephony front end for the RealEstate Hub agent.

This is a THIRD front end over the same one brain (graph.run_turn), next to
conversation_agent.py (text) and live_voice_pipeline.py (local mic/speaker):

    conversation_agent.py   -> text in, text out
    live_voice_pipeline.py  -> local mic in, local speaker out
    livekit_agent.py        -> phone call in (LiveKit SIP), phone call out

Call flow:
    caller dials +1 484 990 3019
        -> LiveKit SIP trunk receives the call
        -> dispatch rule creates a LiveKit room and puts the caller in it
        -> this worker gets dispatched into that room (agent_name="realestate-hub-agent")
        -> caller audio -> Deepgram STT (same model/keyterms as the rest of the project)
        -> final transcript -> graph.run_turn(session_id, text, caller_id=phone_number)
        -> reply text -> Fish Audio TTS (src/voice_pipeline.tts_stream_audio, same voice)
        -> audio -> caller

No conversation logic lives in this file, same rule as the other two front
ends. If a reply is wrong, fix nodes.py/graph.py, not here.

Run:
    python src/livekit_agent.py dev      # local dev worker, connects to LiveKit Cloud
    python src/livekit_agent.py start    # production worker process

Requires in .env:
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    DEEPGRAM_API_KEY, FISH_AUDIO_API_KEY (already used elsewhere in this project)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
from typing import AsyncIterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ChatChunk, ChatContext
from livekit.agents.tts import TTS, ChunkedStream, SynthesizedAudio, TTSCapabilities
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import AudioBuffer
from livekit.plugins import deepgram, silero

import graph  # the ONE orchestrator, same as the other two front ends
import voice_pipeline as vp  # reuse tts_stream_audio + Fish/Deepgram settings

logger = logging.getLogger("livekit-agent")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "realestate-hub-agent")


# ---------------------------------------------------------------------------
# TTS adapter: wraps the project's existing Fish Audio call
# (src/voice_pipeline.tts_stream_audio) as a LiveKit TTS plugin, instead of
# pulling in a second TTS stack. Fish returns full mp3 bytes per call (not a
# token-by-token stream), so this decodes the mp3 and pushes it as one
# synthesized audio chunk. Good enough for phone calls; if per-sentence
# streaming latency matters later, call this once per sentence instead of
# once per full reply (graph.run_turn already returns whole replies, so
# splitting on ". " / "? " / "! " before calling synthesize is the next step).
# ---------------------------------------------------------------------------
class FishAudioTTS(TTS):
    def __init__(self, *, voice_id: Optional[str] = None, sample_rate: int = 24000):
        super().__init__(
            capabilities=TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._voice_id = voice_id

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "FishAudioChunkedStream":
        return FishAudioChunkedStream(tts=self, input_text=text, conn_options=conn_options, voice_id=self._voice_id)


class FishAudioChunkedStream(ChunkedStream):
    def __init__(self, *, tts: FishAudioTTS, input_text: str, conn_options: APIConnectOptions, voice_id: Optional[str]):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._voice_id = voice_id

    async def _run(self, output_emitter) -> None:
        # tts_stream_audio() is a blocking `requests` call - run it off the event loop.
        audio_bytes, _first_byte_ms = await asyncio.to_thread(
            vp.tts_stream_audio, self.input_text, self._voice_id
        )

        # Decode mp3 -> 16-bit PCM so LiveKit can push it to the call as frames.
        from pydub import AudioSegment

        segment = await asyncio.to_thread(AudioSegment.from_file, io.BytesIO(audio_bytes), "mp3")
        segment = segment.set_frame_rate(self._tts.sample_rate).set_channels(1).set_sample_width(2)
        pcm_bytes = segment.raw_data

        output_emitter.initialize(
            request_id=self.input_text[:16] or "tts",
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm_bytes)
        output_emitter.flush()


# ---------------------------------------------------------------------------
# "LLM": no LLM plugin is used. graph.run_turn() (the existing LangGraph
# brain) IS the brain. Overriding Agent.llm_node lets AgentSession's normal
# STT -> turn-detection -> [this] -> TTS pipeline run without ever touching
# an LLM plugin, so persona/RAG/booking/memory logic stays only in
# nodes.py/graph.py, not duplicated here.
# ---------------------------------------------------------------------------
class RealEstateHubAgent(Agent):
    def __init__(self, session_id: str, caller_id: Optional[str]):
        super().__init__(instructions="Handled entirely by graph.run_turn(); no LLM plugin is used here.")
        self.session_id = session_id
        self.caller_id = caller_id

    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list,
        model_settings=None,
    ) -> AsyncIterable[str]:
        user_text = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "user":
                user_text = item.text_content or ""
                break

        reply, _trace = await asyncio.to_thread(
            graph.run_turn, self.session_id, user_text, self.caller_id
        )
        yield reply


def prewarm(proc: JobProcess) -> None:
    # Loads the VAD model once per worker process instead of once per call.
    proc.userdata["vad"] = silero.VAD.load()

#extra

async def send_dtmf(ctx: JobContext, digit: str) -> None:
    """Send a DTMF digit through the active SIP call."""
    await ctx.room.local_participant.publish_dtmf(
        code=int(digit),
        digit=digit,
    )
    logger.info("Sent DTMF digit: %s", digit)



async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    # async def send_dtmf(ctx: JobContext, digit: str) -> None:
    # """Send a DTMF digit through the active SIP call."""
    # await ctx.room.local_participant.publish_dtmf(
    #     code=int(digit),
    #     digit=digit,
    # )
    # logger.info("Sent DTMF digit: %s", digit)
    # The SIP participant's phone number becomes the session id and the
    # caller_id passed into graph.run_turn(), same field CRM/appointments use.
    caller_phone: Optional[str] = None
    for participant in ctx.room.remote_participants.values():
        attrs = getattr(participant, "attributes", {}) or {}
        caller_phone = attrs.get("sip.phoneNumber") or attrs.get("sip.callerNumber")
        if caller_phone:
            break

    session_id = caller_phone or f"call-{ctx.room.name}"
    logger.info("Inbound call room=%s caller=%s session=%s", ctx.room.name, caller_phone, session_id)

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=vp.DEEPGRAM_MODEL,
            language="en",
            api_key=vp.DEEPGRAM_API_KEY,
            keyterms=vp.DEEPGRAM_KEYTERMS or None,
        ),
        tts=FishAudioTTS(voice_id=vp.FISH_VOICE_ID or None),
        turn_detection="vad",
    )

    agent = RealEstateHubAgent(session_id=session_id, caller_id=caller_phone)

    await session.start(agent=agent, room=ctx.room)

    # Same "empty first turn triggers the greeting" contract as the other
    # two front ends (conversation_agent.run_scripted_conversation,
    # live_voice_pipeline's call start).
    greeting, _trace = await asyncio.to_thread(graph.run_turn, session_id, "", caller_phone)
    if greeting:
        await session.say(greeting, allow_interruptions=True)

    # TEST: automatically press 7 on the SIP call.
    await asyncio.sleep(8)
    await send_dtmf(ctx, "7")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=AGENT_NAME,
        )
    )
