from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.target_tracking import TargetTrackingModule


def _context(labels, faces=None):
    return RuntimeContext({
        "settings": {"target_tracking": {"enabled": True, "confirm_frames": 2}},
        "semantic_labels": {"labels": labels},
        "faces": {"detected": faces or []},
    })


def test_person_requires_stable_detection_then_locks_face():
    target = {"label": "person", "confidence": 0.9, "bbox": [10, 20, 100, 160]}
    face = {"label": "Alex", "confidence": 0.8, "bbox": [35, 40, 30, 30]}
    context = _context([target], [face])
    module = TargetTrackingModule("target_tracking")
    module.start(context)
    module.tick(context)
    assert context.get("target_lock")["phase"] == "acquiring"
    module.tick(context)
    lock = context.get("target_lock")
    assert lock["phase"] == "face_locked"
    assert lock["target"]["face"]["label"] == "Alex"


def test_animal_locks_body_without_face():
    target = {"label": "dog", "confidence": 0.9, "bbox": [10, 20, 100, 160]}
    context = _context([target])
    module = TargetTrackingModule("target_tracking")
    module.start(context)
    module.tick(context)
    module.tick(context)
    lock = context.get("target_lock")
    assert lock["phase"] == "body_locked"
    assert "face" not in lock["target"]
