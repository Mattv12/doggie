#!/usr/bin/env python3
"""Persistent memory for Doggie.

Stores owner identity, relationship cues, recurring wake phrases, remembered
notes, and recent scene summaries on the Pi so the assistant can build a more
consistent character across conversations and restarts.
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
MAX_NOTES = 12
MAX_WAKE_PHRASES = 8
MAX_ITEMS_PER_BUCKET = 8


class DoggieMemory:
    def __init__(self, path: Path = MEMORY_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _default(self) -> dict[str, Any]:
        return {
            "owner": {
                "name": "Matt",
                "nicknames": [],
                "face_learned": False,
                "sample_count": 0,
                "last_seen_at": None,
                "last_learned_at": None,
                "last_interaction_at": None,
                "interaction_count": 0,
                "petting_count": 0,
                "preferred_wake_phrases": [],
                "recent_wake_phrase": None,
                "voice_familiarity": 0,
                "preferences": {
                    "likes": [],
                    "dislikes": [],
                    "favorite_things": [],
                    "places": [],
                    "routines": [],
                },
                "notes": [],
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
        owner["last_interaction_at"] = int(time.time())
        self.save()

    def note_owner_seen(self, *, name: str | None = None) -> None:
        owner = self._data["owner"]
        if name:
            owner["name"] = name
        owner["last_seen_at"] = int(time.time())
        self.save()

    def note_interaction(self, text: str = "") -> None:
        owner = self._data["owner"]
        owner["last_interaction_at"] = int(time.time())
        owner["interaction_count"] = int(owner.get("interaction_count", 0)) + 1
        if text:
            wake_text = " ".join(text.lower().split())
            if wake_text:
                owner["recent_wake_phrase"] = wake_text[:80]
        self.save()

    def note_petting(self) -> None:
        owner = self._data["owner"]
        owner["petting_count"] = int(owner.get("petting_count", 0)) + 1
        owner["last_interaction_at"] = int(time.time())
        self.save()

    def remember_name(self, name: str) -> None:
        cleaned = self._clean_value(name, max_words=4)
        if not cleaned:
            return
        owner = self._data["owner"]
        owner["name"] = cleaned
        owner["last_interaction_at"] = int(time.time())
        self.save()

    def remember_nickname(self, nickname: str) -> None:
        cleaned = self._clean_value(nickname, max_words=4)
        if not cleaned:
            return
        self._append_unique(self._data["owner"]["nicknames"], cleaned, MAX_ITEMS_PER_BUCKET)
        self.save()

    def note_wake_phrase(self, phrase: str) -> None:
        cleaned = self._clean_value(phrase, max_words=6)
        if not cleaned:
            return
        owner = self._data["owner"]
        owner["recent_wake_phrase"] = cleaned
        owner["voice_familiarity"] = min(100, int(owner.get("voice_familiarity", 0)) + 1)
        self._append_unique(owner["preferred_wake_phrases"], cleaned, MAX_WAKE_PHRASES)
        self.save()

    def remember_preference(self, bucket: str, value: str) -> None:
        prefs = self._data["owner"]["preferences"]
        if bucket not in prefs:
            return
        cleaned = self._clean_value(value, max_words=8)
        if not cleaned:
            return
        self._append_unique(prefs[bucket], cleaned, MAX_ITEMS_PER_BUCKET)
        self.save()

    def remember_note(self, note: str) -> None:
        cleaned = self._clean_value(note, max_words=18)
        if not cleaned:
            return
        notes = self._data["owner"]["notes"]
        notes.append({"timestamp": int(time.time()), "text": cleaned})
        del notes[:-MAX_NOTES]
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
        nicknames = ", ".join(owner.get("nicknames", [])) or "none"
        wake_phrases = ", ".join(owner.get("preferred_wake_phrases", [])[:3]) or "none"
        notes = "; ".join(note.get("text", "") for note in owner.get("notes", [])[-3:]) or "none"
        prefs = owner.get("preferences", {})
        likes = ", ".join(prefs.get("likes", [])[:4]) or "none"
        dislikes = ", ".join(prefs.get("dislikes", [])[:4]) or "none"
        favorites = ", ".join(prefs.get("favorite_things", [])[:4]) or "none"
        places = ", ".join(prefs.get("places", [])[:4]) or "none"
        routines = ", ".join(prefs.get("routines", [])[:4]) or "none"
        if owner.get("face_learned"):
            learned = self._format_age(owner.get("last_learned_at"))
            seen = self._format_age(owner.get("last_seen_at"))
            return (
                f"Owner memory: {owner.get('name', 'Matt')} is learned "
                f"({owner.get('sample_count', 0)} face samples, learned {learned}). "
                f"Nicknames: {nicknames}. Last seen {seen}. "
                f"Voice familiarity score: {owner.get('voice_familiarity', 0)} via recurring wake phrases, not biometric speaker ID. "
                f"Preferred wake phrases: {wake_phrases}. "
                f"Interactions: {owner.get('interaction_count', 0)}, petting count: {owner.get('petting_count', 0)}. "
                f"Likes: {likes}. Dislikes: {dislikes}. Favorites: {favorites}. Places: {places}. "
                f"Routines: {routines}. Notes: {notes}."
            )
        return (
            f"Owner memory: {owner.get('name', 'Matt')} is not learned yet. "
            f"Nicknames: {nicknames}. Voice familiarity score: {owner.get('voice_familiarity', 0)} via recurring wake phrases, not biometric speaker ID. "
            f"Preferred wake phrases: {wake_phrases}. Likes: {likes}. Dislikes: {dislikes}. "
            f"Favorites: {favorites}. Places: {places}. Routines: {routines}. Notes: {notes}. "
            "If asked to remember the owner visually, use the learn my face action."
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

    @staticmethod
    def _clean_value(value: str, *, max_words: int) -> str:
        cleaned = " ".join(str(value).strip().split())
        if not cleaned:
            return ""
        return " ".join(cleaned.split()[:max_words]).strip(" .,!?:;")

    @staticmethod
    def _append_unique(items: list[str], value: str, limit: int) -> None:
        lowered = {item.lower(): index for index, item in enumerate(items)}
        if value.lower() in lowered:
            items.pop(lowered[value.lower()])
        items.append(value)
        del items[:-limit]
