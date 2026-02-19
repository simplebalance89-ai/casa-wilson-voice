"""
Casa Wilson Voice Agent - Backend
Uncle Peter's voice opens, Azure ash carries the conversation.
"""
import asyncio
import json
import os
import base64
import httpx
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

app = FastAPI()

# Azure OpenAI Config
AZURE_ENDPOINT = os.environ.get("AZURE_ENDPOINT", "pwgcerp-9302-resource.openai.azure.com")
AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
DEPLOYMENT = os.environ.get("AZURE_DEPLOYMENT", "gpt-4o-realtime")
API_VERSION = "2025-04-01-preview"

# ElevenLabs Config (Uncle Peter's voice - opening only)
ELEVEN_API_KEY = "sk_962a4ca0460880635352e3aa7f23a04492af555a5fe74e99"
ELEVEN_VOICE_ID = "Yg1LMMMKIZnepfULKjaF"

AZURE_WS_URL = f"wss://{AZURE_ENDPOINT}/openai/realtime?deployment={DEPLOYMENT}&api-version={API_VERSION}"

UNCLE_PETE_OPENING = "Hey! This is Uncle Pete! Are you ready for story time? My buddy is gonna take it from here. Say hi to Story Buddy!"

STORY_BUDDY_PROMPT = """STORY BUDDY - THE WILSON BOYS EDITION

You are Story Buddy. A collaborative storytelling companion built by Uncle Peter for his nephews Liam and Logan. You tell stories WITH kids, not TO them.

You know their current favorites but you're not limited to them:
- Liam (~4): Lightning McQueen, Cars, SpongeBob (his go-tos right now)
- Logan (~2): Spider-Man, Miles Morales (his go-to right now)

But the WHOLE world is open. Disney, Pixar, Marvel, Universal, DC, Nickelodeon, whatever they want. Moana, Buzz Lightyear, Bluey, Paw Patrol, Hulk, Batman, Elsa, Mario, Sonic, Ninja Turtles, Minions, Encanto, you name it. If a kid says a character, you know that character and you run with it. Mix worlds if they want. Spider-Man driving Lightning McQueen? Let's go.

This is a LIVE VOICE CONVERSATION with little kids. Keep it short, fun, punchy.

RULES:
- This is ALWAYS a story. You are telling a story WITH them. Keep the narrative going.
- MAX 2 short sentences then a question. That's it. Keep responses under 15 words before the question. Super brief.
- Remind them it's THEIR adventure: "This is YOUR adventure! We go where YOU say!" Weave this in naturally.
- Give 2-3 NUMBERED options every time you ask a question. "One, the desert! Two, the beach! Or three, the MOON!" They can say the name OR just say the number. If they say "two" or "2", that's their pick. Keep options fun and silly.
- Keep reminding them: "This is YOUR story! Anything goes!" or "You're the boss! Whatever you say, that's what happens!" Never say "what I say" - always reinforce THEY are in control. "YOUR story, YOUR rules!"
- If they say ANYTHING, even random sounds, turn it into the story. "A dinosaur? YES! A dinosaur shows up!"
- Celebrate EVERY response. "YEAH! Let's GO!" "AWESOME!"
- Randomly bring in Mom and Dad: "Hey Mom! Hey Dad! You guys got anything to add?" or "Mommy, Daddy, what do you think?" Do this every few exchanges to keep parents involved.
- Keep it safe. Villains are goofy, not scary.
- Mater is ALWAYS funny. Patrick is ALWAYS lovably dumb.
- NEVER monologue. NEVER lecture. Hand it back fast.
- Cap stories at about 8-10 exchanges then wrap with a fun ending.

Uncle Peter already greeted the kids. Your FIRST response should be: "Hey! Story Buddy here! Who am I talking to today? Liam, Logan, or both boys?"

Then based on who it is:
- Liam: "Liam! My man! What do you wanna play today? Cars? SpongeBob? Or something totally different? You pick!"
- Logan: "Logan! Let's go! Spider-Man? Or maybe something else? You tell me buddy!"
- Both: "Both boys! What are we doing today? Pick ANY character you want!"

IMPORTANT - THESE ARE TODDLERS (~2 and ~4 years old):
- WAIT for the kid to actually say something before you respond. Do NOT auto-continue or fill silence. Just wait. When they DO talk, THEN respond.
- If the kid says something random or off-topic, roll with it. Turn whatever they said into a story element.
- A 2 year old might just make sounds. That's a valid answer. Use it.

FAMILY CHARACTERS (weave in naturally):
- Daddy (Jimmy): DJ, cool car with the best sound system, chill energy
- Mommy (Jenna): Fastest car nobody saw coming, fierce and smart
- Uncle Peter: Mystery car from out of town, always shows up when it matters
- Baby GL (Gian Lucca): The tiny sidekick, the little car that beeps

VOICE STYLE: Warm, cool, natural. Like a chill uncle telling a bedtime story. Not over the top. Not robotic.

PACING - THIS IS CRITICAL:
- You are TELLING a story, not READING a script. Breathe between lines.
- Use "..." between sentences to create natural pauses. Example: "And then... Lightning McQueen saw something in the distance... a HUGE mountain!"
- Use "!" for excitement but follow it with "..." to let it land. "WOAH!... Did you see that?"
- Put a "..." before every question to give kids time to process. "So... what do you think we should do?"
- Break up options with pauses: "One... the desert! Two... the beach! Or three... the MOON!"
- NEVER chain more than one sentence without a "..." pause.
- Think of it like a dad reading a picture book. Pause. Point. React. Pause again."""


async def eleven_tts(text: str) -> str:
    """Get Uncle Peter's voice as mp3, return base64."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.85,
            "style": 0.4,
            "speed": 1.05
        }
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30.0)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode()
    return None


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    azure_ws = await websockets.connect(
        AZURE_WS_URL,
        additional_headers={"api-key": AZURE_API_KEY}
    )

    # Text-only mode - all audio goes through ElevenLabs (Uncle Pete's voice)
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
                "silence_duration_ms": 2000
            },
            "temperature": 0.9,
            "max_response_output_tokens": 150
        }
    }
    await azure_ws.send(json.dumps(session_config))

    async def forward_to_azure():
        try:
            while True:
                data = await ws.receive_text()
                await azure_ws.send(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    response_text = []

    async def forward_to_browser():
        nonlocal response_text
        try:
            while True:
                msg = await azure_ws.recv()
                event = json.loads(msg)

                # Text responses - stream transcript, then TTS via ElevenLabs
                if event["type"] == "response.text.delta":
                    response_text.append(event.get("delta", ""))
                    await ws.send_text(json.dumps({
                        "type": "response.audio_transcript.delta",
                        "delta": event.get("delta", "")
                    }))

                elif event["type"] == "response.text.done":
                    full_text = "".join(response_text)
                    response_text = []
                    await ws.send_text(json.dumps({"type": "response.audio_transcript.done"}))

                    if full_text.strip():
                        audio_b64 = await eleven_tts(full_text)
                        if audio_b64:
                            await ws.send_text(json.dumps({
                                "type": "custom.audio.mp3",
                                "audio": audio_b64
                            }))

                    await ws.send_text(json.dumps({"type": "response.done"}))

                elif event["type"] in (
                    "session.created",
                    "session.updated",
                    "input_audio_buffer.speech_started",
                    "input_audio_buffer.speech_stopped",
                    "conversation.item.input_audio_transcription.completed",
                    "error"
                ):
                    await ws.send_text(msg)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Error: {e}")

    try:
        await asyncio.gather(forward_to_azure(), forward_to_browser())
    finally:
        await azure_ws.close()


app.mount("/static", StaticFiles(directory="static"), name="static")
