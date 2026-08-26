import json

from houndmind_ai.mapping.mapper import MappingModule
from houndmind_ai.core.runtime import RuntimeContext


def test_location_name_is_sanitized():
    assert MappingModule._active_location({"active_location": "Work / Bay 2"}) == "work-bay-2"
    assert MappingModule._active_location({"active_location": "../../"}) == "home"


def test_location_change_resets_in_memory_map_and_surfaces_safe_status():
    ctx = RuntimeContext()
    ctx.set("settings", {"mapping": {"active_location": "work", "map_only": True}})
    ctx.set("mapping_state", {"location": "home", "samples": [{"timestamp": 1}]})

    module = MappingModule("mapping")
    module.tick(ctx)

    assert ctx.get("mapping_state")["location"] == "work"
    assert ctx.get("mapping_state")["samples"]
    status = ctx.get("location_status")
    assert status["active_location"] == "work"
    assert status["map_only"] is True
    assert status["autonomous_navigation_enabled"] is False


def test_location_map_writes_to_its_own_directory(tmp_path):
    module = MappingModule("mapping")
    settings = {
        "active_location": "car",
        "map_only": True,
        "location_map_path_template": str(tmp_path / "{location}" / "map.json"),
    }
    module.save_location_map({"location": "car", "samples": [{"distance_cm": 42}]}, settings)

    payload = json.loads((tmp_path / "car" / "map.json").read_text(encoding="utf-8"))
    assert payload["meta"]["location"] == "car"
    assert payload["meta"]["autonomous_navigation_enabled"] is False
    assert payload["samples"] == [{"distance_cm": 42}]
