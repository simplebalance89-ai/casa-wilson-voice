"""
Casa Wilson Voice Agent - Backend
Browser <-> This Server <-> Azure OpenAI Realtime (text) + ElevenLabs TTS (Uncle Peter's voice)
"""
import asyncio
import json
import os
import base64
import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# Azure OpenAI Config
AZURE_ENDPOINT = os.environ.get("AZURE_ENDPOINT", "pwgcerp-9302-resource.openai.azure.com")
AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
DEPLOYMENT = os.environ.get("AZURE_DEPLOYMENT", "gpt-4o-realtime")
API_VERSION = "2025-04-01-preview"

# ElevenLabs Config (Uncle Peter's cloned voice)
ELEVEN_API_KEY = os.environ.get("ELEVEN_API_KEY", "sk_962a4ca0460880635352e3aa7f23a04492af555a5fe74e99")
ELEVEN_VOICE_ID = os.environ.get("ELEVEN_VOICE_ID", "7pzUKjYjFInTuktZwpOu")

AZURE_WS_URL = f"wss://{AZURE_ENDPOINT}/openai/realtime?deployment={DEPLOYMENT}&api-version={API_VERSION}"

# Story Buddy System Prompt
STORY_BUDDY_PROMPT = """STORY BUDDY - THE WILSON BOYS EDITION

You are Story Buddy. A collaborative storytelling companion built by Uncle Peter for his nephews Liam and Logan. You tell stories WITH kids, not TO them.

You know two worlds:
- Liam's world: Lightning McQueen, Cars, Radiator Springs, SpongeBob, Bikini Bottom
- Logan's world: Spider-Man, web-swinging, Miles Morales, Spider-verse

This is a LIVE VOICE CONVERSATION with little kids. Keep it short, fun, punchy.

RULES:
- ONE sentence of story, then ask an open question. That's it. 5 seconds max.
- Mix it up. Sometimes ask open-ended: "What do you think happens next?" or "Where should Lightning go?" Sometimes give two fun choices. Don't always do A or B. Let the kids surprise you.
- If the kid doesn't answer, give a fun suggestion or bring in Daddy/Mommy.
- Celebrate EVERY response. "YEAH! Let's GO!"
- Keep it safe. Villains are goofy, not scary.
- Mater is ALWAYS funny. Patrick is ALWAYS lovably dumb.
- NEVER monologue. NEVER lecture. Hand it back fast.
- Cap stories at about 8-10 exchanges then wrap with a fun ending.

OPENING: When the conversation starts, say: "Hey! Story Buddy here! Who am I talking to today? Liam, Logan, or both boys?"

Then based on who it is:
- Liam: "Liam! My man! Lightning McQueen or SpongeBob?"
- Logan: "Logan! Let's go! Spider-Man adventure?"
- Both: "Both boys! Crossover time! Buckle up!"

FAMILY CHARACTERS (weave in naturally):
- Daddy (Jimmy): DJ, cool car with the best sound system, chill energy
- Mommy (Jenna): Fastest car nobody saw coming, fierce and smart
- Uncle Peter: Mystery car from out of town, always shows up when it matters
- Baby GL (Gian Lucca): The tiny sidekick, the little car that beeps

VOICE STYLE: Warm, cool, natural. Like a chill uncle. Not over the top. Extra energy only on Ka-chow and Thwip sounds."""


async def eleven_tts_stream(text: str, ws: WebSocket):
    """Stream Uncle Peter's cloned voice via ElevenLabs TTS."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.75,
            "speed": 0.9
        },
        "output_format": "pcm_24000"
    }

    async with httpx.AsyncClient() as client:
        async with client.stream("POST", url, json=payload, headers=headers, timeout=30.0) as response:
            async for chunk in response.aiter_bytes(chunk_size=4800):
                if chunk:
                    b64_audio = base64.b64encode(chunk).decode()
                    await ws.send_text(json.dumps({
                        "type": "response.audio.delta",
                        "delta": b64_audio
                    }))

    await ws.send_text(json.dumps({"type": "response.audio.done"}))


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Connect to Azure OpenAI Realtime API
    azure_ws = await websockets.connect(
        AZURE_WS_URL,
        additional_headers={"api-key": AZURE_API_KEY}
    )

    # Configure session - TEXT ONLY output (voice comes from ElevenLabs)
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text"],
            "instructions": STORY_BUDDY_PROMPT,
            "input_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.7,
                "prefix_padding_ms": 500,
                "silence_duration_ms": 4000
            },
            "temperature": 0.9,
            "max_response_output_tokens": 500
        }
    }
    await azure_ws.send(json.dumps(session_config))

    # Track response text
    response_text = []

    async def forward_to_azure():
        """Forward browser audio to Azure."""
        try:
            while True:
                data = await ws.receive_text()
                await azure_ws.send(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def forward_to_browser():
        """Intercept Azure text, convert to Uncle Peter's voice via ElevenLabs."""
        nonlocal response_text
        try:
            while True:
                msg = await azure_ws.recv()
                event = json.loads(msg)

                if event["type"] == "response.text.delta":
                    # Collect text and forward transcript to browser
                    response_text.append(event.get("delta", ""))
                    await ws.send_text(json.dumps({
                        "type": "response.audio_transcript.delta",
                        "delta": event.get("delta", "")
                    }))

                elif event["type"] == "response.text.done":
                    # Full text ready - send to ElevenLabs for Uncle Peter's voice
                    full_text = "".join(response_text)
                    response_text = []

                    await ws.send_text(json.dumps({
                        "type": "response.audio_transcript.done"
                    }))

                    if full_text.strip():
                        # Stream Uncle Peter's voice
                        await eleven_tts_stream(full_text, ws)

                    # Signal response complete
                    await ws.send_text(json.dumps({
                        "type": "response.done"
                    }))

                elif event["type"] in (
                    "session.created", "session.updated",
                    "input_audio_buffer.speech_started",
                    "input_audio_buffer.speech_stopped",
                    "conversation.item.input_audio_transcription.completed",
                    "error"
                ):
                    # Pass these through to browser as-is
                    await ws.send_text(msg)

                # Ignore Azure audio events (response.audio.delta etc) - we use ElevenLabs instead

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Error in forward_to_browser: {e}")

    try:
        await asyncio.gather(
            forward_to_azure(),
            forward_to_browser()
        )
    finally:
        await azure_ws.close()


# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")
