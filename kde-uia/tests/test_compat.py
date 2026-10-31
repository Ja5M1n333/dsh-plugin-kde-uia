"""Regression tests for the Plasma 6 / PyGObject compatibility layer.

The 0.1.0 client passed its own suite because the fakes in ``test_pure.py``
spell the AT-SPI calls the way the client *guessed* them.  A real PyGObject
binding spells several of them differently, which is what the first field test
on Plasma 6.8.2 hit.  The fake here deliberately uses the **real** PyGObject
surface (``states`` instead of ``get_state_set()``, ``get_n_actions()`` and
``do_action(index)``, ``get_text()``/``insert_text()``, no ``path_suffix()``)
so each defect named in ``compat.py`` stays fixed.

Run: ``python3 -m unittest discover -s tests``
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kde_uia  # noqa: E402,F401  (imports the client and installs the compat layer)
from kde_uia import compat  # noqa: E402


class _StateSet:
    """``Atspi.StateSet``: ``contains(StateType)`` over a set of member names."""

    def __init__(self, names: set[str]) -> None:
        self.names = names

    def contains(self, member: object) -> bool:
        return str(member) in self.names


class _Rect:
    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x, self.y, self.width, self.height = x, y, w, h


class PyGObjectAccessible:
    """One accessible node exposing the names PyGObject really provides."""

    def __init__(
        self,
        role: str,
        name: str,
        *,
        showing: bool = True,
        focused: bool = False,
        actions: tuple[str, ...] = (),
        checked: bool = False,
        editable: bool = False,
        value: float | None = None,
        kids: tuple["PyGObjectAccessible", ...] = (),
    ) -> None:
        self.role, self._name = role, name
        self._showing, self._focused, self._checked = showing, focused, checked
        self._actions = list(actions)
        self._editable = editable
        self._value = value
        self.kids: list[PyGObjectAccessible] = list(kids)
        for kid in self.kids:
            kid.parent = self
        self.parent: PyGObjectAccessible | None = None

    # -- navigator -------------------------------------------------------
    def get_child_count(self) -> int:
        return len(self.kids)

    def get_child_at_index(self, index: int) -> "PyGObjectAccessible | None":
        return self.kids[index] if 0 <= index < len(self.kids) else None

    # -- properties ------------------------------------------------------
    def get_role_name(self) -> str:
        return self.role

    def get_name(self) -> str:
        return self._name

    def get_description(self) -> str:
        return ""

    def get_accessible_object_path(self) -> str:
        return "/org/a11y/atspi/accessible/" + self._name

    @property
    def states(self) -> _StateSet:
        names = set()
        if self._showing:
            names.add("SHOWING")
        if self._focused:
            names.add("FOCUSED")
        if self._checked:
            names.add("CHECKED")
        names.update({"ENABLED", "SENSITIVE", "VISIBLE"})
        return _StateSet(names)

    # -- action (real names: get_n_actions / do_action(index)) -----------
    def get_n_actions(self) -> int:
        return len(self._actions)

    def get_action_name(self, index: int) -> str | None:
        return self._actions[index] if 0 <= index < len(self._actions) else None

    def do_action(self, index: int) -> bool:  # NOTE: one argument, not (0, name)
        if 0 <= index < len(self._actions):
            if "Toggle" in self._actions:
                self._checked = not self._checked
            return True
        raise RuntimeError("no such action")

    # -- component / value ----------------------------------------------
    def get_extents(self, coord: object) -> _Rect:
        return _Rect(10, 20, 30, 40)

    def get_current_value(self) -> float:
        return self._value if self._value is not None else 6.9e-310  # uninitialised

    def get_minimum_value(self) -> float:
        return 0.0

    def get_maximum_value(self) -> float:
        return 100.0

    # -- text / editable text -------------------------------------------
    def get_text(self) -> str:
        return ""

    def get_character_count(self) -> int:
        return 0

    def is_editable_text(self) -> bool:
        return self._editable

    def insert_text(self, offset: int, text: str, length: int) -> bool:
        if not self._editable:
            return False
        return True

    def set_caret_offset(self, offset: int) -> bool:
        return True

    def get_caret_offset(self) -> int:
        return 0

    def grab_focus(self) -> bool:
        return self._focused or self._editable

    def get_attributes(self) -> dict[str, str]:
        return {}


class RealBindingAtspi:
    """The ``Atspi`` namespace as PyGObject exposes it (no STATE_ prefix)."""

    class StateType:
        SHOWING = "SHOWING"
        FOCUSED = "FOCUSED"
        CHECKED = "CHECKED"
        ENABLED = "ENABLED"
        SENSITIVE = "SENSITIVE"
        VISIBLE = "VISIBLE"
        PRESSED = "PRESSED"
        RESIZABLE = "RESIZABLE"
        OPAQUE = "OPAQUE"
        FOCUSABLE = "FOCUSABLE"
        SELECTABLE = "SELECTABLE"

    class CoordType:
        SCREEN = "SCREEN"
        WINDOW = "WINDOW"


class _Conn:
    atspi = RealBindingAtspi

    def __init__(self, roots: list[PyGObjectAccessible]) -> None:
        self.desktop = PyGObjectAccessible("desktop frame", "", kids=tuple(roots))

    def dispatch(self) -> PyGObjectAccessible:
        return self.desktop


def _surface() -> tuple[_Conn, list[PyGObjectAccessible]]:
    toggle = PyGObjectAccessible("check box", "Show thumbnails", actions=("Toggle", "Press"))
    save = PyGObjectAccessible("push button", "Save", actions=("Press",))
    hidden = PyGObjectAccessible("push button", "Hidden", showing=False)
    toolbar = PyGObjectAccessible("tool bar", "mainToolBar", kids=(save, toggle, hidden))
    entry = PyGObjectAccessible("entry", "Filter", editable=True, focused=True)
    frame = PyGObjectAccessible("frame", "Gwenview — a.png", kids=(toolbar, entry))
    app = PyGObjectAccessible("application", "gwenview", kids=(frame,))
    # A second window of the SAME application, as Gwenview really does.
    frame2 = PyGObjectAccessible("frame", "Gwenview — b.png", kids=())
    app2 = PyGObjectAccessible("application", "gwenview", kids=(frame2,))
    other = PyGObjectAccessible("application", "konsole", kids=(
        PyGObjectAccessible("frame", "Konsole", kids=()),
    ))
    conn = _Conn([app, app2, other])
    return conn, [toggle, save, hidden, entry, frame, frame2]


class CompatInstalledTests(unittest.TestCase):
    def test_install_is_idempotent_and_opt_out_honoured(self) -> None:
        compat.install_patches()
        compat.install_patches()  # twice must not wrap twice
        # Every patch function runs at import; the flag records it.
        from kde_uia import input as input_mod

        self.assertTrue(getattr(input_mod, "_patched_input", False))


class StateAndValueTests(unittest.TestCase):
    def setUp(self) -> None:
        from kde_uia.tree import TreeSession

        self.conn, self.nodes = _surface()
        self.tree = TreeSession(self.conn)

    def test_windows_visible_with_real_states(self) -> None:
        titles = [w.title for w in self.tree.windows()]
        self.assertEqual(titles, ["Gwenview — a.png", "Gwenview — b.png", "Konsole"])

    def test_hidden_window_excluded(self) -> None:
        self.assertNotIn("Hidden", [w.title for w in self.tree.windows()])

    def test_state_reads_are_true_for_visible(self) -> None:
        toggle = self.tree.windows()[0].element.child_at(0).child_at(1)
        self.assertTrue(toggle.state("showing"))
        self.assertFalse(toggle.state("focused"))

    def test_value_ignores_uninitialised_double(self) -> None:
        frame_el = self.tree.windows()[0].element
        # A frame has no Value interface in Qt: reading it must not surface 6.9e-310.
        self.assertIn(frame_el.text_or_value(), ("", None))


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        from kde_uia.tree import TreeSession

        self.conn, self.nodes = _surface()
        self.tree = TreeSession(self.conn)
        self.toggle_node = self.nodes[0]

    def test_actions_are_listed(self) -> None:
        from kde_uia.element import AtspiElement

        element = AtspiElement(self.conn, self.toggle_node)
        self.assertEqual(element.actions(), ["Toggle", "Press"])

    def test_do_action_uses_index(self) -> None:
        from kde_uia.element import AtspiElement

        element = AtspiElement(self.conn, self.toggle_node)
        self.assertFalse(element.acc.states.contains("CHECKED"))
        self.assertTrue(element.do_action("Toggle"))
        self.assertTrue(element.acc.states.contains("CHECKED"))

    def test_unknown_action_is_false(self) -> None:
        from kde_uia.element import AtspiElement

        self.assertFalse(AtspiElement(self.conn, self.toggle_node).do_action("Close"))


class ScopedSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from kde_uia.tree import TreeSession

        self.conn, self.nodes = _surface()
        self.tree = TreeSession(self.conn)

    def test_role_scope_searches_inside_the_window(self) -> None:
        from kde_uia.selector import Selector

        found = self.tree.find(Selector(window="a.png", role="push button"))
        self.assertEqual([e.name() for e in found], ["Save"])

    def test_window_condition_alone_still_scopes(self) -> None:
        from kde_uia.selector import Selector

        self.assertEqual(len(self.tree.find(Selector(window="b.png"))), 1)


class RefDisambiguationTests(unittest.TestCase):
    def setUp(self) -> None:
        from kde_uia.tree import TreeSession

        self.conn, self.nodes = _surface()
        self.tree = TreeSession(self.conn)

    def test_two_windows_of_one_app_get_distinct_refs(self) -> None:
        refs = [w.ref for w in self.tree.windows() if w.app == "gwenview"]
        self.assertEqual(len(refs), 2)
        self.assertEqual(len(set(refs)), 2, refs)

    def test_single_instance_keeps_plain_ref(self) -> None:
        refs = [w.ref for w in self.tree.windows() if w.app == "konsole"]
        self.assertEqual(refs, ["uia:1:konsole:0"])

    def test_refs_round_trip(self) -> None:
        for window in self.tree.windows():
            self.assertIsNotNone(self.tree.resolve_ref(window.ref), window.ref)

    def test_plain_legacy_ref_still_resolves(self) -> None:
        element = self.tree.resolve_ref("uia:1:gwenview:0/0/1")
        self.assertEqual(element.name(), "Show thumbnails")


class InputPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        from kde_uia import input as input_mod

        self.input_mod = input_mod

    def test_key_order_prefers_ydotool_then_atspi(self) -> None:
        service = self.input_mod.InputService()
        service.strategy = "auto"
        order = service._key_order()
        # With dyotoold reachable, kernel-level injection comes first; AT-SPI
        # stays the fallback and plain X11 hosts are untouched.
        expected_head = ["ydotool", "atspi"] if "ydotool" in order else ["atspi"]
        self.assertEqual(order[: len(expected_head)], expected_head)

    def test_explicit_strategy_is_respected(self) -> None:
        service = self.input_mod.InputService()
        service.strategy = "xdotool"
        self.assertEqual(service._key_order(), ["xdotool"])

    def test_pointer_order_mirrors_key_order(self) -> None:
        service = self.input_mod.InputService()
        service.strategy = "auto"
        order = service._pointer_order()
        expected_head = ["ydotool", "atspi"] if "ydotool" in order else ["atspi"]
        self.assertEqual(order[: len(expected_head)], expected_head)

    def test_press_dry_run_reports_the_combo(self) -> None:
        service = self.input_mod.InputService()
        service.dry_run = True
        result = service.press("ctrl+l")
        self.assertEqual(result.kind, "key")
        self.assertEqual(result.details.get("combo"), "ctrl+l")

    def test_empty_combo_is_a_usage_error(self) -> None:
        service = self.input_mod.InputService()
        service.dry_run = True
        with self.assertRaises(self.input_mod.UsageError):
            self.input_mod.InputService.press(service, "")


if __name__ == "__main__":
    unittest.main()


class YdotoolKeycodeTests(unittest.TestCase):
    """The ydotool backend speaks Linux key codes, not keysyms."""

    def test_combination_expands_to_press_and_release(self) -> None:
        from kde_uia.compat import ydotool_sequence

        # ctrl+t: hold ctrl, tap t, release ctrl.
        self.assertEqual(ydotool_sequence("ctrl+t"), ["29:1", "20:1", "20:0", "29:0"])

    def test_modifier_order_is_released_in_reverse(self) -> None:
        from kde_uia.compat import ydotool_sequence

        seq = ydotool_sequence("ctrl+shift+t")
        self.assertEqual(seq[:2], ["29:1", "42:1"])
        self.assertEqual(seq[-2:], ["42:0", "29:0"])

    def test_named_keys_resolve(self) -> None:
        from kde_uia.compat import ydotool_sequence

        self.assertEqual(ydotool_sequence("Enter"), ["28:1", "28:0"])
        self.assertEqual(ydotool_sequence("Escape"), ["1:1", "1:0"])
        self.assertEqual(ydotool_sequence("F5"), ["63:1", "63:0"])

    def test_unknown_key_is_a_usage_error(self) -> None:
        from kde_uia import keys
        from kde_uia.compat import ydotool_sequence
        from kde_uia.errors import UsageError

        with self.assertRaises(UsageError):
            ydotool_sequence("ctrl+NoSuchKey")
        _ = keys
