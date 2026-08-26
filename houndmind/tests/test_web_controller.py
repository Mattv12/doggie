from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.web_controller import WebControllerModule


def test_controller_allows_only_known_commands():
    controller = WebControllerModule("web_controller")
    settings = {"buttons": {"A": "stand"}}
    assert controller._queue({"kind": "body", "value": "forward"}, settings)[0]
    assert controller._queue({"kind": "button", "value": "A"}, settings)[1] == "stand"
    assert not controller._queue({"kind": "body", "value": "dance forever"}, settings)[0]


def test_controller_publishes_one_command_per_tick():
    controller = WebControllerModule("web_controller")
    context = RuntimeContext()
    controller._pending.append({"kind": "head", "value": "left"})
    controller.tick(context)
    assert context.get("web_head_action") == "left"
