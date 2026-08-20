from __future__ import annotations

"""Visual target acquisition for people and common animals.

This module deliberately publishes a *visual* lock only.  It does not command
motors or navigation; a separate, explicitly enabled behaviour may consume the
published ``target_lock`` if that is ever desired.
"""

import time
from typing import Any

from houndmind_ai.core.module import Module


class TargetTrackingModule(Module):
    """Stabilise person/animal detections and associate a face with a person."""

    DEFAULT_TARGETS = {"person", "cat", "dog", "bird", "horse", "sheep", "cow"}

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._candidate: dict[str, Any] | None = None
        self._hits = 0
        self._last_seen = 0.0
        self._lock: dict[str, Any] | None = None
        self._motion_seen = False

    def start(self, context) -> None:
        if self.status.enabled:
            context.set("target_lock", self._status("searching"))

    def tick(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("target_tracking", {})
        if not settings.get("enabled", True):
            return

        now = time.time()
        labels = (context.get("semantic_labels") or {}).get("labels", [])
        allowed = {str(x).lower() for x in settings.get("labels", self.DEFAULT_TARGETS)}
        minimum = float(settings.get("confidence_threshold", 0.55))
        candidates = [
            item for item in labels if isinstance(item, dict)
            and str(item.get("label", "")).lower() in allowed
            and float(item.get("confidence", 0.0)) >= minimum
            and self._valid_box(item.get("bbox"))
        ]
        candidates = [item for item in candidates if self._plausible_target(item, settings)]
        candidate = max(candidates, key=lambda item: float(item.get("confidence", 0.0)), default=None)
        confirm_frames = max(1, int(settings.get("confirm_frames", 3)))
        lost_after_s = max(0.1, float(settings.get("lost_after_s", 1.0)))

        if candidate is not None:
            if self._candidate and self._same_target(self._candidate, candidate):
                self._motion_seen = self._motion_seen or self._moved(self._candidate, candidate, settings)
                self._hits += 1
            else:
                self._candidate, self._hits, self._motion_seen = candidate, 1, False
            self._last_seen = now
            if self._hits >= confirm_frames:
                self._lock = dict(candidate)
                phase = "body_locked"
                if str(candidate.get("label", "")).lower() == "person":
                    face = self._face_in(candidate, (context.get("faces") or {}).get("detected", []))
                    if face is not None:
                        self._lock["face"] = face
                        phase = "face_locked"
                    elif settings.get("require_face_for_person", False):
                        context.set("target_lock", self._status("acquiring_face", candidate, self._hits))
                        return
                    elif settings.get("require_motion_for_person", False) and not self._motion_seen:
                        context.set("target_lock", self._status("acquiring_motion", candidate, self._hits))
                        return
                context.set("target_lock", self._status(phase, self._lock, self._hits))
                return
            context.set("target_lock", self._status("acquiring", candidate, self._hits))
            return

        if self._lock is not None and now - self._last_seen <= lost_after_s:
            context.set("target_lock", self._status("holding", self._lock, self._hits))
            return
        self._candidate = self._lock = None
        self._hits = 0
        self._motion_seen = False
        context.set("target_lock", self._status("searching"))

    @staticmethod
    def _valid_box(box: Any) -> bool:
        return isinstance(box, (list, tuple)) and len(box) == 4 and box[2] > 0 and box[3] > 0

    @staticmethod
    def _same_target(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if str(a.get("label", "")).lower() != str(b.get("label", "")).lower():
            return False
        ax, ay, aw, ah = a["bbox"]
        bx, by, bw, bh = b["bbox"]
        center_distance = ((ax + aw / 2 - bx - bw / 2) ** 2 + (ay + ah / 2 - by - bh / 2) ** 2) ** 0.5
        return center_distance <= max(40.0, max(aw, ah, bw, bh) * 0.5)

    @staticmethod
    def _moved(a: dict[str, Any], b: dict[str, Any], settings: dict) -> bool:
        ax, ay, aw, ah = a["bbox"]
        bx, by, bw, bh = b["bbox"]
        distance = ((ax + aw / 2 - bx - bw / 2) ** 2 + (ay + ah / 2 - by - bh / 2) ** 2) ** 0.5
        return distance >= float(settings.get("min_motion_px", 18))

    @staticmethod
    def _plausible_target(item: dict[str, Any], settings: dict) -> bool:
        if str(item.get("label", "")).lower() != "person":
            return True
        _, _, width, height = item["bbox"]
        return height / max(width, 1) >= float(settings.get("person_min_aspect_ratio", 1.15))

    @staticmethod
    def _face_in(body: dict[str, Any], faces: Any) -> dict[str, Any] | None:
        if not isinstance(faces, list):
            return None
        x, y, w, h = body["bbox"]
        for face in faces:
            box = face.get("bbox") if isinstance(face, dict) else None
            if not TargetTrackingModule._valid_box(box):
                continue
            fx, fy, fw, fh = box
            cx, cy = fx + fw / 2, fy + fh / 2
            if x <= cx <= x + w and y <= cy <= y + h:
                return dict(face)
        return None

    @staticmethod
    def _status(phase: str, target: dict[str, Any] | None = None, hits: int = 0) -> dict[str, Any]:
        return {"timestamp": time.time(), "phase": phase, "target": target, "confirmations": hits}
