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


def _held(d) -> set[int]:
    return {i * 8 + b for i, byte in enumerate(d.query_keymap()) for b in range(8) if byte >> b & 1}


def _clearable(d) -> set[int]:
    """Keycodes of Shift, Ctrl and Alt: modifiers we may release on the user's behalf. (Not Super: releasing it
    could look like a Super tap to the desktop, which opens its overview.)"""
    mm = d.get_modifier_mapping()
    return {kc for i in (X.ShiftMapIndex, X.ControlMapIndex, X.Mod1MapIndex) for kc in mm[i] if kc}


def wait_keys_released(timeout: float = 2.0) -> bool:
    """Wait until the user lets go of the hotkey that triggered us.

    The hotkey's own key (Return …) has to come up: until then our grab gets every key event, our paste included,
    and its auto-repeat would land in the agent's input box as newlines. Modifiers still held would turn ctrl+v
    into ctrl+shift+alt+v, but people let go of them a good 200 ms later than of the key, so instead of waiting
    we release them ourselves (XTest). The server treats them as up from then on and drops the physical release
    that follows. Super, or any other key still down, is waited for.
    """
    d = xd.get()
    mods = _clearable(d)
    alt = set(d.get_modifier_mapping()[X.Mod1MapIndex])
    end = time.monotonic() + timeout
    while True:
        held = _held(d)
        if not held:
            return True
        if held <= mods:
            ctrl = _keycode('Control_L')
            if held & alt:                              # a lone Alt release opens the app's menu bar: tap Ctrl first
                xtest.fake_input(d, X.KeyPress, ctrl)
                xtest.fake_input(d, X.KeyRelease, ctrl)
            for c in sorted(held):
                xtest.fake_input(d, X.KeyRelease, c)
            d.sync()
            if not _held(d):
                return True
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
