"""
client/websocket_client/ws_client.py
WebSocket Stream Controller.
Vexa pattern: client connects to WhisperLive WebSocket stream.

Duy trì 2 WebSocket connections song song:
  /ws/audio/{session_id}?direction=inbound   ← Virtual Speaker (Teams/Meet audio)
  /ws/audio/{session_id}?direction=outbound  ← Real Microphone
"""
import asyncio
import base64
import inspect
import json
import logging
import threading
from typing import Callable, Optional, Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("meeting_ai.ws")


class MeetingWSClient:
    def __init__(
        self,
        server_ws_url: str,
        session_id: str,
        api_key: str = "",
        on_subtitle: Optional[Callable] = None,
        on_inbound_audio: Optional[Callable[[str], None]] = None,
        on_outbound_text: Optional[Callable[[str, str], None]] = None,
        on_listening: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.base_url = server_ws_url
        self.session_id = session_id
        self.api_key = api_key

        self._on_subtitle = on_subtitle
        self._on_inbound_audio = on_inbound_audio
        self._on_outbound_text = on_outbound_text
        self._on_listening = on_listening
        self._on_error = on_error

        self._running = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)

        self._inbound_q = asyncio.Queue(maxsize=100)
        self._outbound_q = asyncio.Queue(maxsize=100)

        self.inbound_src_lang = "auto"
        self.inbound_tgt_lang = "vie_Latn"
        self.outbound_src_lang = "vie_Latn"
        self.outbound_tgt_lang = "eng_Latn"

        self.inbound_only = True

        # chống duplicate
        self._last_inbound_final = ""
        self._last_outbound_final = ""

    # ─────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop.is_running():
            def _cancel_all():
                for task in asyncio.all_tasks(self._loop):
                    task.cancel()
            self._loop.call_soon_threadsafe(_cancel_all)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def set_languages(
        self,
        inbound_src: str,
        inbound_tgt: str,
        outbound_src: str,
        outbound_tgt: str,
    ):
        self.inbound_src_lang = inbound_src
        self.inbound_tgt_lang = inbound_tgt
        self.outbound_src_lang = outbound_src
        self.outbound_tgt_lang = outbound_tgt

    @staticmethod
    def _to_b64(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, bytes):
            return base64.b64encode(data).decode("utf-8")
        if hasattr(data, "tobytes"):
            return base64.b64encode(data.tobytes()).decode("utf-8")
        return str(data)

    def _enqueue(self, chunk: Any, direction: str = "inbound", is_final: bool = True):
        if not self._running:
            return

        if isinstance(chunk, dict):
            payload = chunk
        else:
            b64_data = self._to_b64(chunk)
            payload = {
                "type": "audio_chunk",
                "data": b64_data,
                "src_lang": (
                    self.inbound_src_lang
                    if direction == "inbound"
                    else self.outbound_src_lang
                ),
                "tgt_lang": (
                    self.inbound_tgt_lang
                    if direction == "inbound"
                    else self.outbound_tgt_lang
                ),
                "is_final": is_final,
                "session_id": self.session_id,
            }

        q = self._inbound_q if direction == "inbound" else self._outbound_q

        def _put():
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(payload)

        try:
            self._loop.call_soon_threadsafe(_put)
        except RuntimeError:
            pass

    def send_inbound_chunk(self, chunk: Any, is_final: bool = True):
        """Callback cho InboundAudioManager: gửi chunk audio từ Virtual Cable / Meet."""
        self._enqueue(chunk, direction="inbound", is_final=is_final)

    def send_outbound_chunk(self, chunk: Any, is_final: bool = True):
        """Callback cho Outbound: gửi chunk audio từ micro thật."""
        self._enqueue(chunk, direction="outbound", is_final=is_final)

    def push_audio(self, chunk: Any, direction: str = "inbound", is_final: bool = True):
        """Generic method để đẩy audio chunk."""
        self._enqueue(chunk, direction=direction, is_final=is_final)

    # ─────────────────────────────────────────────

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()
            except Exception:
                pass

    async def _main(self):
        tasks = [
            self._handle_stream("inbound", self._inbound_q),
        ]

        if not self.inbound_only:
            tasks.append(
                self._handle_stream("outbound", self._outbound_q)
            )

        await asyncio.gather(*tasks, return_exceptions=True)

    # ─────────────────────────────────────────────

    async def _handle_stream(self, direction: str, audio_q: asyncio.Queue):
        url = (
            f"{self.base_url.rstrip('/')}/ws/audio/{self.session_id}"
            f"?direction={direction}"
        )
        if self.api_key:
            url += f"&api_key={self.api_key}"

        connect_kwargs = {
            "ping_interval": 10,
            "ping_timeout": 10,
        }
        if self.api_key:
            sig = inspect.signature(websockets.connect)
            if "additional_headers" in sig.parameters:
                connect_kwargs["additional_headers"] = {"X-API-Key": self.api_key}
            elif "extra_headers" in sig.parameters:
                connect_kwargs["extra_headers"] = {"X-API-Key": self.api_key}

        while self._running:
            try:
                async with websockets.connect(url, **connect_kwargs) as ws:

                    cfg = {
                        "type": "config",
                        "src_lang": (
                            self.inbound_src_lang
                            if direction == "inbound"
                            else self.outbound_src_lang
                        ),
                        "tgt_lang": (
                            self.inbound_tgt_lang
                            if direction == "inbound"
                            else self.outbound_tgt_lang
                        ),
                    }
                    await ws.send(json.dumps(cfg))

                    sender = asyncio.create_task(
                        self._sender(ws, audio_q, direction)
                    )
                    receiver = asyncio.create_task(
                        self._receiver(ws, direction)
                    )

                    done, pending = await asyncio.wait(
                        [sender, receiver],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()

            except asyncio.CancelledError:
                break
            except ConnectionClosed:
                logger.warning(f"WS [{direction}] disconnected, retry in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WS [{direction}] error: {e}")
                if self._on_error:
                    self._on_error(str(e))
                await asyncio.sleep(3)

    # ─────────────────────────────────────────────

    async def _sender(self, ws, audio_q: asyncio.Queue, direction: str):
        while self._running:
            try:
                payload = await asyncio.wait_for(audio_q.get(), timeout=1.0)
                if isinstance(payload, dict):
                    await ws.send(json.dumps(payload))
                elif isinstance(payload, (str, bytes)):
                    await ws.send(payload)
                else:
                    await ws.send(str(payload))
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"WS sender [{direction}] stopped: {e}")
                break

    # ─────────────────────────────────────────────

    def _safe_call_subtitle(self, orig: str, trans: str, latency_ms: float):
        if not self._on_subtitle:
            return
        try:
            sig = inspect.signature(self._on_subtitle)
            params = len(sig.parameters)
            if params == 2:
                self._on_subtitle(trans, latency_ms)
            else:
                self._on_subtitle(orig, trans, latency_ms)
        except Exception:
            try:
                self._on_subtitle(orig, trans, latency_ms)
            except TypeError:
                try:
                    self._on_subtitle(trans, latency_ms)
                except Exception as e:
                    logger.error(f"Error calling on_subtitle callback: {e}")

    async def _receiver(self, ws, direction: str):
        async for msg in ws:
            try:
                data = json.loads(msg)
                t = data.get("type")

                # =========================
                # LISTENING
                # =========================
                if t == "listening":
                    if self._on_listening:
                        self._on_listening(data.get("text", ""))

                # =========================
                # INBOUND RESULT (Full translation + TTS)
                # =========================
                elif t == "inbound_result":
                    orig = data.get("original_text", "").strip()
                    trans = data.get("translated_text", "").strip()
                    latency_ms = float(data.get("latency_ms", 0.0))
                    audio_b64 = data.get("audio_b64")

                    if trans or orig:
                        key = f"{orig}|{trans}"
                        if key != self._last_inbound_final:
                            self._last_inbound_final = key
                            print(f"📝 [INBOUND] {orig} → {trans}")
                            self._safe_call_subtitle(orig, trans, latency_ms)

                    if self._on_inbound_audio and audio_b64:
                        self._on_inbound_audio(audio_b64)

                # =========================
                # SUBTITLE (Overlay text)
                # =========================
                elif t == "subtitle":
                    orig = data.get("original_text", "").strip()
                    trans = (data.get("translated_text") or data.get("text", "")).strip()
                    latency_ms = float(data.get("latency_ms", 0.0))
                    audio_b64 = data.get("audio_b64")

                    if trans or orig:
                        key = f"{orig}|{trans}"
                        if key != self._last_inbound_final:
                            self._last_inbound_final = key
                            print(f"📝 [SUBTITLE] {orig} → {trans}")
                            self._safe_call_subtitle(orig, trans, latency_ms)

                    if self._on_inbound_audio and audio_b64:
                        self._on_inbound_audio(audio_b64)

                # =========================
                # OUTBOUND RESULT
                # =========================
                elif t == "outbound_result":
                    orig = data.get("original_text", "").strip()
                    trans = data.get("translated_text", "").strip()

                    key = f"{orig}|{trans}"
                    if key and key != self._last_outbound_final:
                        self._last_outbound_final = key
                        print(f"📝 [OUTBOUND] {orig} → {trans}")
                        if self._on_outbound_text:
                            self._on_outbound_text(orig, trans)

                elif t == "error":
                    err_msg = data.get("message", "Unknown error")
                    logger.error(f"Server error frame [{direction}]: {err_msg}")
                    if self._on_error:
                        self._on_error(err_msg)

            except Exception as e:
                logger.error(f"Receiver error [{direction}]: {e}")