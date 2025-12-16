from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from pynput import keyboard, mouse


@dataclass
class InputEvent:
    t_ns: int
    event_type: str
    key_code: Optional[int] = None
    mouse_x: Optional[float] = None
    mouse_y: Optional[float] = None
    mouse_button: Optional[str] = None
    delta: Optional[float] = None
    frame_ref: Optional[int] = None
    window_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


class InputLogger:
    def __init__(
        self,
        event_queue,
        session_id: str,
        window_id: str,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
    ):
        self.events = event_queue
        self.session_id = session_id
        self.window_id = window_id
        self.capture_allowed_fn = capture_allowed_fn or (lambda: True)
        self.stop_event = threading.Event()
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release)
        self.mouse_listener = mouse.Listener(
            on_click=self.on_click, on_scroll=self.on_scroll, on_move=self.on_move
        )

    def start(self):
        self.keyboard_listener.start()
        self.mouse_listener.start()

    def stop(self):
        self.stop_event.set()
        self.keyboard_listener.stop()
        self.mouse_listener.stop()

    def _emit(self, event_type: str, **kwargs):
        if not self.capture_allowed_fn():
            return
        metadata = kwargs.pop("metadata", None)
        ev = InputEvent(
            t_ns=time.monotonic_ns(),
            event_type=event_type,
            window_id=self.window_id,
            session_id=self.session_id,
            metadata=metadata,
            **kwargs,
        )
        self.events.put(ev)

    # Keyboard callbacks
    def on_key_press(self, key):
        try:
            code = key.vk if hasattr(key, "vk") else key.value.vk  # type: ignore
        except Exception:
            code = None
        self._emit("key_down", key_code=code)

    def on_key_release(self, key):
        try:
            code = key.vk if hasattr(key, "vk") else key.value.vk  # type: ignore
        except Exception:
            code = None
        self._emit("key_up", key_code=code)

    # Mouse callbacks
    def on_click(self, x, y, button, pressed):
        btn = getattr(button, "name", str(button))
        self._emit("mouse_click", mouse_x=x, mouse_y=y, mouse_button=btn, metadata={"pressed": str(pressed)})

    def on_scroll(self, x, y, dx, dy):
        self._emit("wheel", mouse_x=x, mouse_y=y, delta=dy)

    def on_move(self, x, y):
        self._emit("mouse_move", mouse_x=x, mouse_y=y)

