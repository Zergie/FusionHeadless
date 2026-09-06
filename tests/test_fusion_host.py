from __future__ import annotations

import unittest
import threading

from fusion_host import FusionHost


class FakeEvent:
    def __init__(self) -> None:
        self.handler = None

    def add(self, handler) -> None:
        self.handler = handler


class FakeApplication:
    def __init__(self) -> None:
        self.userInterface = object()
        self.events: dict[str, FakeEvent] = {}

    def registerCustomEvent(self, event_id: str) -> FakeEvent:
        event = FakeEvent()
        self.events[event_id] = event
        return event

    def fireCustomEvent(self, event_id: str, request_id: str) -> None:
        self.events[event_id].handler.notify(
            type("EventArgs", (), {"additionalInfo": request_id})()
        )

    def unregisterCustomEvent(self, event_id: str) -> None:
        self.events.pop(event_id, None)


class FusionHostTests(unittest.TestCase):
    def test_dispatches_a_callback_on_the_registered_custom_event(self) -> None:
        app = FakeApplication()
        adsk = type("Adsk", (), {"core": type("Core", (), {"CustomEventHandler": object})})()
        host = FusionHost(app, adsk)
        host.start()

        self.assertEqual(host.dispatch(lambda left, right: left + right, 40, 2), 42)
        first_context = host.context()
        self.assertEqual(first_context, {
            "app": app,
            "ui": app.userInterface,
            "adsk": adsk,
        })
        self.assertIsNot(first_context, host.context())

    def test_dispatch_propagates_callback_errors(self) -> None:
        app = FakeApplication()
        adsk = type("Adsk", (), {"core": type("Core", (), {"CustomEventHandler": object})})()
        host = FusionHost(app, adsk)
        host.start()

        with self.assertRaisesRegex(ValueError, "invalid document"):
            host.dispatch(lambda: (_ for _ in ()).throw(ValueError("invalid document")))

    def test_close_releases_waiting_dispatch(self) -> None:
        app = FakeApplication()
        adsk = type("Adsk", (), {"core": type("Core", (), {"CustomEventHandler": object})})()
        host = FusionHost(app, adsk)
        host.start()
        original_fire = app.fireCustomEvent
        app.fireCustomEvent = lambda event_id, request_id: None
        outcome: list[BaseException] = []

        def wait_for_dispatch() -> None:
            try:
                host.dispatch(lambda: None)
            except BaseException as error:
                outcome.append(error)

        worker = threading.Thread(target=wait_for_dispatch)
        worker.start()
        host.close()
        worker.join(timeout=1)
        app.fireCustomEvent = original_fire

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], RuntimeError)
        self.assertNotIn(FusionHost.EVENT_ID, app.events)


if __name__ == "__main__":
    unittest.main()
