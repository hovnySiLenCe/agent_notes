"""Synthetic key presses via XTest."""
from __future__ import annotations

import time

from Xlib import X, XK
from Xlib.ext import xtest

from . import display as xd

MOD_KEYSYMS = {'shift': 'Shift_L', 'ctrl': 'Control_L', 'control': 'Control_L', 'alt': 'Alt_L', 'super': 'Super_L'}


def _keycode(name: str) -> int:
    ks = XK.string_to_keysym(name)
    if not ks and len(name) == 1:
        ks = ord(name)
    kc = xd.get().keysym_to_keycode(ks)
    if not kc:
        raise ValueError(f'unknown key: {name}')
    return kc


def send(combo: str) -> None:
    """send('ctrl+v'), send('shift+Insert'), send('Return')."""
    *mods, key = combo.split('+')
    codes = [_keycode(MOD_KEYSYMS[m.lower()]) for m in mods] + [_keycode(key)]
    d = xd.get()
    for c in codes:
        xtest.fake_input(d, X.KeyPress, c)
    for c in reversed(codes):
        xtest.fake_input(d, X.KeyRelease, c)
    d.sync()


def wait_keys_released(timeout: float = 2.0) -> bool:
    """Wait until the user lets go of the hotkey that triggered us, all of it.

    Modifiers still held would turn ctrl+v into ctrl+shift+alt+v. A held Return (Shift+Alt+Return fills) is
    worse: once the modifiers are up, its auto-repeat lands in the agent's input box as an extra newline (or, with
    Shift still down, Shift+Return = newline in most chat inputs).
    """
    d = xd.get()
    end = time.monotonic() + timeout
    while True:
        if not any(d.query_keymap()):
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.02)
