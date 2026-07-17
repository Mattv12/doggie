#!/usr/bin/env python3
"""Persistent lightweight memory for Doggie.

Stores owner memory and recent scene summaries on the Pi so the assistant can
refer back to what it learned across rounds and restarts.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


MEMORY_DIR = Path("/home/matt/.doggie_memory")
MEMORY_PATH = MEMORY_DIR / "memory.json"
MAX_SCENES = 8
SCENE_FRESH_SECONDS = 15 * 60


class DoggieMemory:
    def __init__(self, path: Path = MEMORY_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _default(self) -> dict[str, Any]:
        return {
            "owner": {
                "name": "Matt",
                "face_learned": False,
                "sample_count": 0,
                "last_seen_at": None,
                "last_learned_at": None,
            },
            "scenes": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default()
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return self._default()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def note_owner_learned(self, *, name: str = "Matt", sample_count: int = 0) -> None:
        owner = self._data["owner"]
        owner["name"] = name
        owner["face_learned"] = True
        owner["sample_count"] = sample_count
        owner["last_learned_at"] = int(time.time())
        self.save()

    def note_owner_seen(self, *, name: str | None = None) -> None:
        owner = self._data["owner"]
        if name:
            owner["name"] = name
        owner["last_seen_at"] = int(time.time())
        self.save()

    def note_scene(self, *, query: str, summary: str) -> None:
        clean_summary = " ".join(summary.split())
        clean_query = " ".join(query.split())
        if not clean_summary:
            return
        scenes = self._data["scenes"]
        scenes.append(
            {
                "timestamp": int(time.time()),
                "query": clean_query,
                "summary": clean_summary,
            }
        )
        del scenes[:-MAX_SCENES]
        self.save()

    def owner_context(self) -> str:
        owner = self._data["owner"]
        if owner.get("face_learned"):
            learned = self._format_age(owner.get("last_learned_at"))
            seen = self._format_age(owner.get("last_seen_at"))
            return (
                f"Owner memory: {owner.get('name', 'Matt')} is learned "
                f"({owner.get('sample_count', 0)} face samples, learned {learned}). "
                f"Last seen {seen}."
            )
        return (
            f"Owner memory: {owner.get('name', 'Matt')} is not learned yet. "
            "If asked to remember the owner, use the learn my face action."
        )

    def recent_scene_context(self) -> str:
        fresh = [
            scene for scene in self._data["scenes"]
            if int(time.time()) - int(scene.get("timestamp", 0)) <= SCENE_FRESH_SECONDS
        ]
        if not fresh:
            return "Scene memory: no recent remembered scene."

        latest = fresh[-1]
        previous = fresh[-2]["summary"] if len(fresh) > 1 else None
        text = f"Scene memory: latest scene summary ({self._format_age(latest.get('timestamp'))}) - {latest.get('summary', '')}."
        if previous and previous != latest.get("summary"):
            text += f" Previous scene summary - {previous}."
        return text

    def build_context(self) -> str:
        return f"{self.owner_context()}\n{self.recent_scene_context()}"

    @staticmethod
    def _format_age(timestamp: Any) -> str:
        if not timestamp:
            return "never"
        seconds = max(0, int(time.time()) - int(timestamp))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h ago"
