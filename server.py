"""
Casa Wilson Voice Agent - Backend
WebSocket proxy: Browser <-> This Server <-> Azure OpenAI Realtime API
"""
import asyncio
import json
import os
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# Azure OpenAI Config
AZURE_ENDPOINT = os.environ.get("AZURE_ENDPOINT", "pwgcerp-9302-resource.openai.azure.com")
AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
DEPLOYMENT = os.environ.get("AZURE_DEPLOYMENT", "gpt-4o-realtime")
API_VERSION = "2025-04-01-preview"

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

    # Configure session
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": STORY_BUDDY_PROMPT,
            "voice": "ash",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
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
        """Forward Azure responses to browser."""
        try:
            while True:
                msg = await azure_ws.recv()
                await ws.send_text(msg)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception:
            pass

    # Run both directions concurrently
    try:
        await asyncio.gather(
            forward_to_azure(),
            forward_to_browser()
        )
    finally:
        await azure_ws.close()


# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")
