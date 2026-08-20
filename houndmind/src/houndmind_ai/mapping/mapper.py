from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class MappingModule(Module):
    """Lightweight, location-scoped mapping with optional persistence.

    This does not implement full SLAM. It stores sensor snapshots and can save
    an independent map for each named location (for example ``home``, ``work``,
    or ``car``). Location maps are observational only: this module never
    enables movement or autonomous navigation.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.last_save_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if not settings.get("enabled", True):
            return

        location = self._active_location(settings)

        # A map never carries across named locations. This protects against
        # applying home observations to work, a car, or a new temporary area.
        sensors = context.get("sensors") or {}
        mapping_state = context.get("mapping_state") or {"samples": []}
        if mapping_state.get("location") != location:
            mapping_state = {"location": location, "samples": []}
        context.set(
            "location_status",
            {
                "active_location": location,
                "map_only": bool(settings.get("map_only", True)),
                "autonomous_navigation_enabled": False,
                "map_persistence_enabled": self._location_map_enabled(settings),
            },
        )

        scan_latest = context.get("scan_latest") or {}
        scan_angles = (
            scan_latest.get("angles", {}) if isinstance(scan_latest, dict) else {}
        )
        openings, safe_paths, best_path = self._analyze_scan_openings(
            scan_angles, settings
        )

        sample = {
            "timestamp": time.time(),
            "distance_cm": sensors.get("distance"),
            "touch": sensors.get("touch"),
            "sound": sensors.get("sound_detected"),
            "acc": sensors.get("acc"),
            "gyro": sensors.get("gyro"),
            "openings": openings,
            "safe_paths": safe_paths,
            "best_path": best_path,
        }
        mapping_state["samples"].append(sample)
        max_samples = int(settings.get("sample_history_max", 500))
        if max_samples > 0 and len(mapping_state["samples"]) > max_samples:
            mapping_state["samples"] = mapping_state["samples"][-max_samples:]
        max_age_s = float(settings.get("sample_max_age_s", 0))
        if max_age_s > 0:
            cutoff = time.time() - max_age_s
            mapping_state["samples"] = [
                entry
                for entry in mapping_state["samples"]
                if entry.get("timestamp", 0) >= cutoff
            ]
        context.set("mapping_state", mapping_state)

        context.set(
            "mapping_openings",
            {
                "timestamp": sample["timestamp"],
                "openings": openings,
                "safe_paths": safe_paths,
                "best_path": best_path,
            },
        )

        # Optionally ingest sweep angles into a simple occupancy grid for
        # lightweight map-aware avoidance. This keeps a histogram of observed
        # hits by grid cell (coordinates in centimeters relative to robot).
        if bool(settings.get("grid_enabled", True)):
            try:
                self._ingest_into_grid(scan_angles, settings, mapping_state)
            except Exception:  # noqa: BLE001
                logger.debug("Grid ingestion failed", exc_info=True)

        # Optional path-planning hook (future expansion).
        if settings.get("path_planning_enabled", False):
            hook = context.get("path_planning_hook")
            if callable(hook):
                try:
                    plan = hook(mapping_state, sample, settings)
                    context.set("path_planning", plan)
                except Exception:  # noqa: BLE001
                    logger.debug("Path planning hook failed", exc_info=True)

        # Persist the active location's map snapshot on a configured interval.
        save_interval = settings.get(
            "location_map_save_interval_s",
            settings.get("home_map_save_interval_s", 30),
        )
        now = time.time()
        if (
            self._location_map_enabled(settings)
            and now - self.last_save_ts >= save_interval
        ):
            self.save_location_map(mapping_state, settings)
            self.last_save_ts = now

    @staticmethod
    def _active_location(settings: dict) -> str:
        """Return a safe, stable name for the selected physical location."""
        raw = str(settings.get("active_location", "home")).strip().lower()
        slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
        return slug or "home"

    @staticmethod
    def _location_map_enabled(settings: dict) -> bool:
        """Support the legacy home-map option while adopting location maps."""
        return bool(settings.get("location_map_enabled", settings.get("home_map_enabled", False)))

    def _location_map_path(self, settings: dict, location: str) -> Path:
        template = str(
            settings.get(
                "location_map_path_template",
                "data/maps/{location}/map.json",
            )
        )
        try:
            configured_path = template.format(location=location)
        except (KeyError, ValueError):
            logger.warning("Invalid location map path template; using default")
            configured_path = f"data/maps/{location}/map.json"
        output_path = Path(configured_path)
        if not output_path.is_absolute():
            output_path = Path(__file__).resolve().parents[3] / output_path
        return output_path

    def save_location_map(self, mapping_state: dict, settings: dict) -> None:
        """Persist only the active location's samples to its own JSON map."""
        location = self._active_location(settings)
        output_path = self._location_map_path(settings, location)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        samples = list(mapping_state.get("samples", []))
        max_samples = int(
            settings.get("location_map_max_samples", settings.get("home_map_max_samples", 0))
        )
        max_age_s = float(
            settings.get("location_map_max_age_s", settings.get("home_map_max_age_s", 0))
        )
        if max_age_s > 0:
            cutoff = time.time() - max_age_s
            samples = [
                entry for entry in samples if entry.get("timestamp", 0) >= cutoff
            ]
        if max_samples > 0 and len(samples) > max_samples:
            samples = samples[-max_samples:]

        payload = {
            "meta": {
                "saved_at": time.time(),
                "location": location,
                "map_only": bool(settings.get("map_only", True)),
                "autonomous_navigation_enabled": False,
                "cell_size_cm": settings.get("cell_size_cm", 10),
                "grid_size": settings.get("grid_size", [100, 100]),
                "opening_min_width_cm": settings.get("opening_min_width_cm", 60),
                "safe_path_min_width_cm": settings.get("safe_path_min_width_cm", 40),
                "safe_path_score_weight_width": settings.get(
                    "safe_path_score_weight_width", 0.6
                ),
                "safe_path_score_weight_distance": settings.get(
                    "safe_path_score_weight_distance", 0.4
                ),
                "location_map_max_samples": max_samples,
                "location_map_max_age_s": max_age_s,
            },
            "samples": samples,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved %s location map to %s", location, output_path)

    def save_home_map(self, mapping_state: dict, settings: dict) -> None:
        """Backward-compatible alias for callers using the former method name."""
        self.save_location_map(mapping_state, settings)

    def stop(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if self._location_map_enabled(settings):
            mapping_state = context.get("mapping_state") or {"samples": []}
            self.save_location_map(mapping_state, settings)

    def _ingest_into_grid(self, angles: dict, settings: dict, mapping_state: dict) -> None:
        if not isinstance(angles, dict) or not angles:
            return
        cell_size_cm = float(settings.get("cell_size_cm", 10.0))
        grid_size = settings.get("grid_size", [100, 100])
        try:
            gx = int(grid_size[0])
            gy = int(grid_size[1])
        except Exception:
            gx, gy = 100, 100
        half_x = gx // 2
        half_y = gy // 2

        grid = mapping_state.get("grid") or {"cells": {}}
        cells = grid.get("cells") or {}

        for key, raw in angles.items():
            try:
                yaw = float(key)
                dist = float(raw)
            except Exception:
                continue
            if dist <= 0:
                continue
            # Convert polar (distance cm, yaw deg) to grid indices. Yaw is
            # degrees where 0 = forward, positive = left.
            rad = math.radians(yaw)
            x_cm = dist * math.cos(rad)  # forward
            y_cm = dist * math.sin(rad)  # left
            ix = int(round(y_cm / cell_size_cm))
            iy = int(round(x_cm / cell_size_cm))
            # Bound to grid size
            if abs(ix) > half_x or abs(iy) > half_y:
                continue
            k = f"{ix},{iy}"
            cells[k] = cells.get(k, 0) + 1

        grid["cells"] = cells
        mapping_state["grid"] = grid

    @staticmethod
    def _analyze_scan_openings(
        angles: dict, settings: dict
    ) -> tuple[list[dict], list[dict], dict | None]:
        if not isinstance(angles, dict) or not angles:
            return [], [], None

        min_open_width_cm = float(settings.get("opening_min_width_cm", 60))
        max_open_width_cm = float(settings.get("opening_max_width_cm", 120))
        min_open_conf = float(settings.get("opening_cell_conf_min", 0.6))
        min_safe_width_cm = float(settings.get("safe_path_min_width_cm", 40))
        max_safe_width_cm = float(settings.get("safe_path_max_width_cm", 200))
        min_safe_conf = float(settings.get("safe_path_cell_conf_min", 0.5))

        items = []
        for key, dist in angles.items():
            try:
                yaw = int(float(key))
                distance = float(dist)
            except Exception:
                continue
            if distance <= 0:
                continue
            items.append((yaw, distance))

        if not items:
            return [], [], None

        items.sort(key=lambda it: it[0])
        openings: list[dict] = []
        safe_paths: list[dict] = []

        def estimate_width_cm(dist: float, step_deg: float) -> float:
            return max(0.0, dist * (step_deg * 0.0174533))

        step_deg = float(settings.get("scan_step_deg", 0.0))
        if step_deg <= 0.0 and len(items) > 1:
            diffs = [abs(items[i + 1][0] - items[i][0]) for i in range(len(items) - 1)]
            diffs = [d for d in diffs if d > 0]
            if diffs:
                diffs.sort()
                mid = len(diffs) // 2
                step_deg = diffs[mid]
        if step_deg <= 0.0:
            step_deg = 15.0

        for yaw, dist in items:
            width_cm = estimate_width_cm(dist, step_deg)
            conf = min(1.0, dist / 200.0)
            entry = {
                "yaw": yaw,
                "distance_cm": dist,
                "width_cm": width_cm,
                "confidence": conf,
            }
            if (
                min_open_width_cm <= width_cm <= max_open_width_cm
                and conf >= min_open_conf
            ):
                openings.append(entry)
            if (
                min_safe_width_cm <= width_cm <= max_safe_width_cm
                and conf >= min_safe_conf
            ):
                safe_paths.append(entry)

        best_path = None
        if safe_paths:
            weight_width = float(settings.get("safe_path_score_weight_width", 0.6))
            weight_distance = float(
                settings.get("safe_path_score_weight_distance", 0.4)
            )
            best_score = -1.0
            for entry in safe_paths:
                score = (entry["width_cm"] * weight_width) + (
                    entry["distance_cm"] * weight_distance
                )
                if score > best_score:
                    best_score = score
                    best_path = {**entry, "score": score}

        return openings, safe_paths, best_path
