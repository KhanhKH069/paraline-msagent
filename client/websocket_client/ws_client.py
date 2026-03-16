"""
client/websocket_client/ws_client.py
WebSocket Stream Controller.
Vexa pattern: client connects to WhisperLive WebSocket stream.

Duy trì 2 WebSocket connections song song:
  /ws/audio/{session_id}?direction=inbound   ← Virtual Speaker (Teams audio)
  /ws/audio/{session_id}?direction=outbound  ← Real Microphone
"""
import asyncio
import json
import logging
import threading
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("paraline.ws")


class ParalineWSClient:
    def __init__(
        self,
        server_ws_url: str,   # e.g. "ws://192.168.1.100:8765"
        session_id: str,
        api_key: str = "",
        on_subtitle:      Optional[Callable[[str, float], None]] = None,
        on_inbound_audio: Optional[Callable[[str], None]] = None,
        on_outbound_text: Optional[Callable[[str, str], None]] = None,
        on_error:         Optional[Callable[[str], None]] = None,
    ):
        self.base_url   = server_ws_url
        self.session_id = session_id
        self.api_key    = api_key

        self._on_subtitle      = on_subtitle
        self._on_inbound_audio = on_inbound_audio
        self._on_outbound_text = on_outbound_text
        self._on_error         = on_error

        self._running = False
        self._loop    = asyncio.new_event_loop()
        self._thread  = threading.Thread(target=self._run, daemon=True)

        # Thread-safe queues (put from audio callback threads)
        self._inbound_q  = asyncio.Queue(maxsize=100)
        self._outbound_q = asyncio.Queue(maxsize=100)

        # Language config
        self.inbound_src_lang  = "jpn_Jpan"
        self.inbound_tgt_lang  = "vie_Latn"
        self.outbound_src_lang = "vie_Latn"
        self.outbound_tgt_lang = "jpn_Jpan"

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread.start()
        logger.info(f"WS client started — session {self.session_id[:8]}")

    def stop(self):
        self._running = False
        self._loop.call_soon_threadsafe(self._loop.stop)

    def send_inbound_chunk(self, pcm_b64: str):
        """Call from audio thread: push inbound audio chunk."""
        self._loop.call_soon_threadsafe(
            lambda: self._inbound_q.put_nowait(pcm_b64) if not self._inbound_q.full() else None
        )

    def send_outbound_chunk(self, pcm_b64: str):
        """Call from audio thread: push outbound audio chunk."""
        self._loop.call_soon_threadsafe(
            lambda: self._outbound_q.put_nowait(pcm_b64) if not self._outbound_q.full() else None
        )

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(asyncio.gather(
            self._inbound_ws_loop(),
            self._outbound_ws_loop(),
        ))

    def _ws_url(self, direction: str) -> str:
        return (f"{self.base_url}/ws/audio/{self.session_id}"
                f"?direction={direction}&api_key={self.api_key}")

    async def _inbound_ws_loop(self):
        """Inbound: Virtual Speaker → server → TTS audio + subtitle."""
        while self._running:
            try:
                async with websockets.connect(self._ws_url("inbound"), ping_interval=20) as ws:
                    logger.info("Inbound WS connected ✓")
                    await asyncio.gather(
                        self._sender(ws, self._inbound_q, self.inbound_src_lang, self.inbound_tgt_lang),
                        self._receiver(ws, "inbound"),
                    )
            except ConnectionClosed:
                logger.warning("Inbound WS closed. Reconnecting...")
            except Exception as e:
                logger.error(f"Inbound WS error: {e}")
            if self._running:
                await asyncio.sleep(2)

    async def _outbound_ws_loop(self):
        """Outbound: Real Mic → server → Teams text."""
        while self._running:
            try:
                async with websockets.connect(self._ws_url("outbound"), ping_interval=20) as ws:
                    logger.info("Outbound WS connected ✓")
                    await asyncio.gather(
                        self._sender(ws, self._outbound_q, self.outbound_src_lang, self.outbound_tgt_lang),
                        self._receiver(ws, "outbound"),
                    )
            except ConnectionClosed:
                logger.warning("Outbound WS closed. Reconnecting...")
            except Exception as e:
                logger.error(f"Outbound WS error: {e}")
            if self._running:
                await asyncio.sleep(2)

    async def _sender(self, ws, queue: asyncio.Queue, src: str, tgt: str):
        """Continuously drain queue and send audio chunks."""
        idx = 0
        while self._running:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=0.5)
                await ws.send(json.dumps({
                    "type":        "audio_chunk",
                    "data":        data,
                    "src_lang":    src,
                    "tgt_lang":    tgt,
                    "session_id":  self.session_id,
                    "chunk_index": idx,
                }))
                idx += 1
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"Sender error: {e}")
                break

    async def _receiver(self, ws, direction: str):
        """Receive and dispatch server messages."""
        async for msg in ws:
            try:
                data = json.loads(msg)
                t = data.get("type", "")

                if t in ("subtitle", "listening") and self._on_subtitle:
                    self._on_subtitle(data.get("text", ""), data.get("latency_ms", 0))

                elif t == "inbound_result":
                    if self._on_subtitle:
                        self._on_subtitle(data.get("translated_text", ""), data.get("latency_ms", 0))
                    if self._on_inbound_audio and data.get("audio_b64"):
                        self._on_inbound_audio(data["audio_b64"])

                elif t == "outbound_result" and self._on_outbound_text:
                    self._on_outbound_text(
                        data.get("original_text", ""),
                        data.get("translated_text", ""),
                    )

                elif t == "error" and self._on_error:
                    self._on_error(data.get("message", "Unknown error"))

            except Exception as e:
                logger.error(f"Receiver error [{direction}]: {e}")
