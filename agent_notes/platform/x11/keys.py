"""Synthetic key presses via XTest."""
from __future__ import annotations

import time

from Xlib import X, XK
from Xlib.ext import xtest

from . import display as xd

MOD_KEYSYMS = {'shift': 'Shift_L', 'ctrl': 'Control_L', 'control': 'Control_L', 'alt': 'Alt_L', 'super': 'Super_L'}
_HELD_MODIFIERS = ('Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
                   'Super_L', 'Super_R', 'Meta_L', 'Meta_R', 'ISO_Level3_Shift')


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


def wait_modifiers_released(timeout: float = 1.5) -> bool:
    """The user is still holding Shift+Alt from the hotkey; injecting ctrl+v now would become ctrl+shift+alt+v."""
    d = xd.get()
    codes = [c for c in (d.keysym_to_keycode(XK.string_to_keysym(n)) for n in _HELD_MODIFIERS) if c]
    end = time.monotonic() + timeout
    while True:
        km = d.query_keymap()
        if not any(km[c // 8] & (1 << (c % 8)) for c in codes):
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.02)
