from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Any

from houndmind_ai.core.module import Module
from houndmind_ai.optional.vision_preprocessing import VisionPreprocessor
from houndmind_ai.optional.vision_inference_scheduler import VisionInferenceScheduler

logger = logging.getLogger(__name__)


class VisionPi4Module(Module):
    """Pi4-focused vision feed.

    Publishes `vision_frame` into context. Supports Picamera2 if available,
    otherwise falls back to OpenCV VideoCapture.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._camera: Any | None = None
        self._cv2: Any | None = None
        self._capture: Any | None = None
        self._last_frame_ts = 0.0
        self._last_frame = None

        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None

        self._preprocessor: Optional[VisionPreprocessor] = None
        self._inference_scheduler: Optional[VisionInferenceScheduler] = None
        self._last_inference_result = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("vision_pi4", {})
        self._context = context
        backend = settings.get("backend", "picamera2")

        # Setup preprocessor and inference scheduler if enabled
        self._preprocessor = VisionPreprocessor(settings.get("preprocessing", {}))
        if settings.get("inference_scheduler_enabled", True):
            def _on_inference_result(result):
                self._last_inference_result = result
                context.set("vision_inference_result", result)
            # Dummy inference function, replace with actual model
            def _dummy_inference(frame):
                time.sleep(0.05)
                return {"frame_id": id(frame), "result": "ok"}
            self._inference_scheduler = VisionInferenceScheduler(
                _dummy_inference, result_callback=_on_inference_result
            )
            assert self._inference_scheduler is not None
            self._inference_scheduler.start()

        if backend == "picamera2":
            try:
                from picamera2 import Picamera2  # type: ignore
                import cv2  # type: ignore
            except Exception as exc:  # noqa: BLE001
                logger.warning("Picamera2 unavailable: %s", exc)
            else:
                try:
                    cam = Picamera2()
                    config = cam.create_preview_configuration()
                    cam.configure(config)
                    cam.start()
                    self._camera = cam
                    self._cv2 = cv2
                    self.available = True
                    context.set(
                        "vision_status", {"status": "ready", "backend": backend}
                    )
                    self._maybe_start_http(settings)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Picamera2 init failed: %s", exc)

        try:
            import cv2  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.disable(f"Vision backend unavailable: {exc}")
            return

        device_index = int(settings.get("device_index", 0))
        capture = cv2.VideoCapture(device_index)
        if not capture.isOpened():
            self.disable("Failed to open camera device")
            return

        self._cv2 = cv2
        self._capture = capture
        self.available = True
        context.set("vision_status", {"status": "ready", "backend": "opencv"})
        self._maybe_start_http(settings)

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("vision_pi4", {})
        if not settings.get("enabled", True):
            return

        override_interval = context.get("vision_frame_interval_override_s")
        if isinstance(override_interval, (int, float)):
            frame_interval = float(override_interval)
        else:
            frame_interval = float(settings.get("frame_interval_s", 0.2))
        now = time.time()
        if now - self._last_frame_ts < frame_interval:
            return

        frame = None
        if self._camera is not None:
            try:
                frame = self._camera.capture_array()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Picamera2 capture failed: %s", exc)
        elif self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:
                frame = None

        if frame is not None:
            context.set("vision_frame", frame)
            context.set("vision_frame_ts", now)
            self._last_frame_ts = now
            self._last_frame = self._cv2.cvtColor(frame, self._cv2.COLOR_RGBA2BGR) if frame.ndim == 3 and frame.shape[2] == 4 and self._cv2 is not None else frame
            # Preprocess and schedule inference if enabled
            if self._preprocessor and self._inference_scheduler:
                try:
                    processed = self._preprocessor.process(frame)
                    self._inference_scheduler.submit_frame(processed)
                except Exception as exc:
                    logger.warning("Vision preprocessing/inference failed: %s", exc)

    def stop(self, context) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Picamera2 stop failed: %s", exc)
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception as exc:  # noqa: BLE001
                logger.warning("VideoCapture release failed: %s", exc)
        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Vision HTTP server shutdown failed: %s", exc)
        if self._inference_scheduler:
            self._inference_scheduler.stop()
            self._inference_scheduler = None

    def _maybe_start_http(self, settings: dict) -> None:
        http_settings = settings.get("http", {})
        if not http_settings.get("enabled", False):
            return
        host = http_settings.get("host", "0.0.0.0")
        port = int(http_settings.get("port", 8090))

        module = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    html = b"""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Doggie Live View</title><style>body{margin:0;background:#0b1020;color:#e7eefb;font:16px system-ui;text-align:center}h1{font-size:1rem;margin:12px}img{width:100%;max-width:960px;max-height:calc(100vh - 52px);object-fit:contain}</style><h1>Doggie Live View</h1><img src='/stream' alt='Doggie live camera'>"""
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                if self.path != "/stream":
                    self.send_response(404)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.end_headers()

                try:
                    while True:
                        frame = module._last_frame
                        if frame is None or module._cv2 is None:
                            time.sleep(0.05)
                            continue

                        display = module._annotate(frame)
                        ok, buf = module._cv2.imencode(".jpg", display)
                        if not ok:
                            time.sleep(0.05)
                            continue
                        payload = buf.tobytes()
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(payload)}\r\n\r\n".encode()
                        )
                        self.wfile.write(payload)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.1)
                except Exception:
                    return

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start vision HTTP server: %s", exc)
            return
        self._http_server = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()
        logger.info("Vision HTTP stream on http://%s:%s/stream", host, port)

    def _annotate(self, frame):
        """Draw the visual acquisition state without mutating the camera frame."""
        if self._cv2 is None:
            return frame
        lock = getattr(self, "_context", None)
        lock = lock.get("target_lock") if lock is not None else None
        target = lock.get("target") if isinstance(lock, dict) else None
        if not isinstance(target, dict) or not isinstance(target.get("bbox"), (list, tuple)):
            return frame
        image = frame.copy()
        x, y, w, h = [int(v) for v in target["bbox"]]
        phase = str(lock.get("phase", "target"))
        color = (0, 220, 255) if phase == "face_locked" else (0, 200, 0)
        self._cv2.rectangle(image, (x, y), (x + w, y + h), color, 2)
        label = f"{target.get('label', 'target')} — {phase}"
        face = target.get("face")
        if isinstance(face, dict) and isinstance(face.get("bbox"), (list, tuple)):
            fx, fy, fw, fh = [int(v) for v in face["bbox"]]
            self._cv2.rectangle(image, (fx, fy), (fx + fw, fy + fh), (255, 160, 0), 2)
            label += f" ({face.get('label', 'unknown')})"
        self._cv2.putText(image, label, (x, max(20, y - 8)), self._cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        return image
