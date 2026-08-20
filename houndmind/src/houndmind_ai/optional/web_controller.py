from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class WebControllerModule(Module):
    """LAN-only touch controller. Commands are allow-listed before publishing."""

    BODY_ACTIONS = {"forward", "backward", "turn left", "turn right", "stop"}
    HEAD_ACTIONS = {"left", "right", "up", "down", "center"}

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._pending: list[dict] = []

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("web_controller", {})
        if not settings.get("enabled", True):
            return
        context.set("web_controller_enqueue", lambda payload: self._queue(payload, settings))
        self._start_http(settings)
        context.set("web_controller", {"status": "ready", "port": settings.get("http", {}).get("port")})

    def tick(self, context) -> None:
        if not self.status.enabled or not self._pending:
            return
        command = self._pending.pop(0)
        kind, value = command["kind"], command["value"]
        if kind == "body":
            context.set("web_body_action", value)
        elif kind == "head":
            context.set("web_head_action", value)
        else:
            context.set("web_body_action", value)
        context.set("web_controller", {"status": "command", "last": command})
        logger.info("Web controller %s -> %s", kind, value)

    def _queue(self, payload: dict, settings: dict) -> tuple[bool, str]:
        kind, value = payload.get("kind"), payload.get("value")
        if kind == "body" and value in self.BODY_ACTIONS:
            self._pending.append({"kind": kind, "value": value})
            return True, value
        if kind == "head" and value in self.HEAD_ACTIONS:
            self._pending.append({"kind": kind, "value": value})
            return True, value
        if kind == "button":
            actions = settings.get("buttons", {})
            action = actions.get(str(value)) if isinstance(actions, dict) else None
            if isinstance(action, str) and action in self.BODY_ACTIONS | {"stand", "lie", "wag tail", "sit"}:
                self._pending.append({"kind": kind, "value": action})
                return True, action
        return False, "unsupported command"

    def _start_http(self, settings: dict) -> None:
        http = settings.get("http", {})
        if not http.get("enabled", False):
            return
        host, port = http.get("host", "0.0.0.0"), int(http.get("port", 8093))
        module = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, data: dict, status: int = 200) -> None:
                raw = json.dumps(data).encode()
                self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def do_GET(self) -> None:
                if urlparse(self.path).path != "/":
                    self._json({"error": "not found"}, 404); return
                host_name = self.headers.get("Host", "").split(":", 1)[0]
                html = _PAGE.replace("{{HOST}}", host_name).encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(html))); self.end_headers(); self.wfile.write(html)

            def do_POST(self) -> None:
                if urlparse(self.path).path not in ("/command", "/controller/command"):
                    self._json({"error": "not found"}, 404); return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode())
                except Exception:
                    self._json({"error": "invalid JSON"}, 400); return
                ok, message = module._queue(payload, settings)
                self._json({"status": "queued", "command": message} if ok else {"error": message}, 200 if ok else 400)

            def log_message(self, format, *args):
                return

        try:
            self._server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:
            logger.warning("Web controller failed to bind %s:%s: %s", host, port, exc)
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Web controller on http://%s:%s/", host, port)

    def stop(self, context) -> None:
        if self._server:
            self._server.shutdown(); self._server.server_close()


_PAGE = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Doggie Controller</title><style>
*{box-sizing:border-box}body{margin:0;background:#07101b;color:white;font-family:system-ui;overflow:hidden}.cam{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;opacity:.55}.ui{position:relative;min-height:100vh;display:flex;align-items:end;justify-content:space-between;padding:20px;background:linear-gradient(transparent 35%,#06101ddd)}.pad{display:grid;grid-template:repeat(3,64px)/repeat(3,64px);gap:6px}.pad button{grid-area:auto}.u{grid-column:2}.l{grid-column:1;grid-row:2}.c{grid-column:2;grid-row:2}.r{grid-column:3;grid-row:2}.d{grid-column:2;grid-row:3}button{border:1px solid #7dd3fc;border-radius:18px;background:#0e2947dd;color:#fff;font-size:22px;touch-action:manipulation}button:active{background:#0284c7}.right{display:flex;gap:18px;align-items:end}.actions{display:grid;grid-template-columns:repeat(2,64px);gap:8px}.actions button{height:64px;font-weight:700}.label{text-align:center;font-size:12px;margin:0 0 7px;text-shadow:0 1px 2px #000}@media(max-width:620px){.ui{padding:12px}.pad{grid-template:repeat(3,54px)/repeat(3,54px);gap:4px}.right{gap:8px}.actions{grid-template-columns:repeat(2,54px)}.actions button{height:54px}}</style><img class=cam src='http://{{HOST}}:8090/stream'><main class=ui><section><p class=label>BODY</p><div class=pad><button class=u data-k=body data-v=forward>▲</button><button class=l data-k=body data-v='turn left'>◀</button><button class=c data-k=body data-v=stop>■</button><button class=r data-k=body data-v='turn right'>▶</button><button class=d data-k=body data-v=backward>▼</button></div></section><section class=right><div><p class=label>HEAD</p><div class=pad><button class=u data-k=head data-v=up>▲</button><button class=l data-k=head data-v=left>◀</button><button class=c data-k=head data-v=center>●</button><button class=r data-k=head data-v=right>▶</button><button class=d data-k=head data-v=down>▼</button></div></div><div><p class=label>ACTIONS</p><div class=actions><button data-k=button data-v=A>A</button><button data-k=button data-v=B>B</button><button data-k=button data-v=Y>Y</button><button data-k=button data-v=Z>Z</button></div></div></section></main><script>document.querySelectorAll('button').forEach(b=>b.onclick=()=>fetch('/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:b.dataset.k,value:b.dataset.v})}))</script>"""
