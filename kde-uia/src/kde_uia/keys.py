"""W3C UI Events ``KeyboardEvent.key`` values, mapped to X11 keysyms.

AT-SPI hands us keysym *names* (``Control_L``, ``a``, ``F5``, ``BackSpace``)
and X11 tools such as ``xdotool`` want the same names, so the only work here
is mapping portable key spellings (``Enter``, ``ArrowUp``, ``PageDown``,
``CTRL+Shift+t``) onto them.  Everything is pure data and unit-testable
without a display.
"""

from __future__ import annotations

from .errors import UsageError

#: Portable key name -> X keysym name (case-insensitive lookup).
KEYSYMS: dict[str, str] = {
    # whitespace / control
    "enter": "Return",
    "return": "Return",
    "numpadenter": "KP_Enter",
    "tab": "Tab",
    "space": "space",
    "spacebar": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "ins": "Insert",
    "escape": "Escape",
    "esc": "Escape",
    "menu": "Menu",
    "contextmenu": "Menu",
    "pause": "Pause",
    "printscreen": "Print",
    "capslock": "Caps_Lock",
    "numlock": "Num_Lock",
    "scrolllock": "Scroll_Lock",
    # navigation
    "arrowleft": "Left",
    "left": "Left",
    "arrowright": "Right",
    "right": "Right",
    "arrowup": "Up",
    "up": "Up",
    "arrowdown": "Down",
    "down": "Down",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    # function keys
    **{f"f{i}": f"F{i}" for i in range(1, 36)},
    # editing / application keys
    "clear": "Clear",
    "help": "Help",
    "undo": "Undo",
    "redo": "Redo",
    "cut": "XF86Cut",
    "copy": "XF86Copy",
    "paste": "XF86Paste",
    "find": "XF86Search",
    "open": "XF86Open",
    "save": "XF86Save",
    "close": "XF86Close",
    "print": "XF86Print",
    "new": "XF86New",
    # punctuation with layout-independent names
    "minus": "minus",
    "plus": "plus",
    "equals": "equal",
    "comma": "comma",
    "period": "period",
    "slash": "slash",
    "backslash": "backslash",
    "semicolon": "semicolon",
    "apostrophe": "apostrophe",
    "quote": "apostrophe",
    "grave": "grave",
    "leftbracket": "bracketleft",
    "rightbracket": "bracketright",
    "backquote": "grave",
    "backtick": "grave",
    "tab_char": "Tab",
    "enter_char": "Return",
    "arrowleft_char": "Left",
    "arrowright_char": "Right",
    "arrowup_char": "Up",
    "arrowdown_char": "Down",
    "home_char": "Home",
    "end_char": "End",
    "pageup_char": "Prior",
    "pagedown_char": "Next",
    "delete_char": "Delete",
    "backspace_char": "BackSpace",
    "escape_char": "Escape",
    "insert_char": "Insert",
    "f1_char": "F1",
    "f2_char": "F2",
    "f3_char": "F3",
    "f4_char": "F4",
    "f5_char": "F5",
    "f6_char": "F6",
    "f7_char": "F7",
    "f8_char": "F8",
    "f9_char": "F9",
    "f10_char": "F10",
    "f11_char": "F11",
    "f12_char": "F12",
}

#: Named characters a keyboard cannot synthesise portably; fed through clipboard paste.
UNICODE_ONLY_SYMBOLS = {
    "\u00a0": " ",  # non-breaking space behaves as a space for typing
}

#: Modifier alias -> canonical name used in combinations.
MODIFIERS: dict[str, str] = {
    "ctrl": "CTRL",
    "control": "CTRL",
    "shift": "SHIFT",
    "alt": "ALT",
    "opt": "ALT",
    "option": "ALT",
    "super": "SUPER",
    "meta": "SUPER",
    "win": "SUPER",
    "logo": "SUPER",
    "hyper": "HYPER",
}


def normalize_key_name(name: str) -> str:
    """Map a portable key spelling to the X keysym name.

    Single characters pass through unchanged (``"a"`` -> ``"a"``); known
    portable names map through :data:`KEYSYMS`; anything else is returned
    verbatim so an expert can feed a raw X keysym name.
    """
    if len(name) == 1:
        return name
    lowered = name.strip().lower()
    if lowered in KEYSYMS:
        return KEYSYMS[lowered]
    return name.strip()


def parse_combo(combo: str) -> tuple[list[str], str]:
    """Split ``CTRL+Shift+t`` into ``(['CTRL', 'SHIFT'], 't')``.

    ``+`` itself is written as the final key (``CTRL++``) or as ``plus``.
    """
    if not isinstance(combo, str) or not combo.strip():
        raise UsageError("a key combination must be a non-empty string")
    text = combo.strip()
    if text.endswith("++"):
        head, key = text[:-2], "+"
    else:
        head, _, key = text.rpartition("+")
    if not key:
        raise UsageError(f"key combination {combo!r} names no final key", hint="Example: CTRL+Shift+t or ALT+F4.")
    modifiers: list[str] = []
    for part in head.split("+") if head else []:
        if not part:
            raise UsageError(f"key combination {combo!r} has an empty modifier")
        canonical = MODIFIERS.get(part.strip().lower())
        if canonical is None:
            raise UsageError(
                f"unknown modifier {part!r} in {combo!r}",
                hint=f"Modifiers: {', '.join(sorted(set(MODIFIERS.values())))} (aliases: {', '.join(sorted(MODIFIERS))}).",
            )
        if canonical not in modifiers:
            modifiers.append(canonical)
    return modifiers, normalize_key_name(key)


def format_combo(modifiers: list[str], key: str) -> str:
    return "+".join([*modifiers, key])
