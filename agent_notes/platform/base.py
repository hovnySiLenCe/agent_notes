"""Platform abstraction. X11 is implemented today; Windows (UIA) / macOS (AX) slot in behind the same API.

Methods documented as "worker" may block (D-Bus / X round-trips) and must run on the worker thread.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WindowInfo:
    xid: int            # native window handle
    pid: int | None
    wm_instance: str
    wm_class: str
    title: str


class Platform(ABC):
    @abstractmethod
    def active_window(self) -> WindowInfo | None: ...

    @abstractmethod
    def window_exists(self, xid: int) -> bool: ...

    @abstractmethod
    def activate(self, xid: int) -> None: ...

    @abstractmethod
    def is_terminal(self, win: WindowInfo) -> bool: ...

    @abstractmethod
    def hotkey_listener(self):
        """A QObject with `triggered(str action)` / `failed(str spec, str reason)` signals and start/stop."""

    @abstractmethod
    def selection_belongs_to(self, win: WindowInfo) -> bool:
        """Was the system 'primary selection' made in `win`'s application (i.e. not stale text from elsewhere)?"""

    @abstractmethod
    def capture_selection(self, win: WindowInfo, primary: str = '') -> dict | None:
        """worker: quote + anchor for the current text selection inside `win`, or None.
        `primary` is the X PRIMARY selection text, used to correct toolkits with unreliable offsets."""

    @abstractmethod
    def inject(self, target: WindowInfo, terminal: bool, anchor_path: list | None, auto_send: bool) -> dict:
        """worker: activate `target`, focus its chat input and paste (clipboard already prepared)."""

    @abstractmethod
    def track(self, reqs: list[dict], focus: set[str]) -> dict:
        """worker: current screen rectangles of annotated text (see atspi.tracker.Tracker.update)."""

    @abstractmethod
    def reveal(self, req: dict) -> bool:
        """worker: scroll the annotated text into view in its (already activated) window."""

    @abstractmethod
    def accessibility_enabled(self) -> bool: ...

    def warm_up(self) -> None:
        """worker: pay one-time setup costs (accessibility bus connection, caches) before the first capture."""

    def compositing(self) -> bool:
        """Can windows be translucent? (False: highlights must not cover the text.)"""
        return True


def get_platform() -> Platform:
    from .x11 import X11Platform
    return X11Platform()
