"""Pure-logic tests that need no desktop (run: python3 -m unittest discover -s tests)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kde_uia import keys  # noqa: E402
from kde_uia.errors import AmbiguousError, InvalidRefError, KdeUiaError, UsageError  # noqa: E402
from kde_uia.refs import ElementRef, make_ref, parse_ref  # noqa: E402
from kde_uia.screens import Screen, ScreenMap, infer_scale, map_from_outputs, map_single  # noqa: E402
from kde_uia.selector import Selector, normalize_role, role_matches  # noqa: E402
from kde_uia.wait import wait_for  # noqa: E402


class RefTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        ref = make_ref("dolphin", [1, 0, 3], None)
        self.assertEqual(ref, "uia:1:dolphin:1/0/3")
        parsed = parse_ref(ref)
        self.assertEqual(parsed, ElementRef("dolphin", (1, 0, 3), None))
        self.assertEqual(str(parsed), ref)

    def test_root_and_instance(self) -> None:
        ref = make_ref("kwrite", [], "12.34")
        self.assertEqual(ref, "uia:1:kwrite:/:12.34")
        self.assertEqual(parse_ref(ref).instance, "12.34")

    def test_invalid(self) -> None:
        for bad in ("", "foo", "uia:1:", "uia:2:kwrite:1", "uia:1::1", "uia:1:kwrite:1//2"):
            with self.subTest(bad=bad), self.assertRaises(InvalidRefError):
                parse_ref(bad)

    def test_ref_has_hint(self) -> None:
        with self.assertRaises(KdeUiaError) as ctx:
            parse_ref("nope")
        self.assertTrue(ctx.exception.hint)


class SelectorTests(unittest.TestCase):
    def test_defaults_contains_case_insensitive(self) -> None:
        sel = Selector(name="save")
        self.assertTrue(sel.matches_name("Save File"))
        self.assertTrue(sel.matches_name("SAVE"))
        # `name` alone does not constrain values; `text` does.
        self.assertTrue(sel.matches_text("something"))
        self.assertFalse(Selector(text="save").matches_text("something"))

    def test_exact(self) -> None:
        sel = Selector(name="Save", match="exact")
        self.assertTrue(sel.matches_name("Save"))
        self.assertFalse(sel.matches_name("Save As"))

    def test_regex(self) -> None:
        sel = Selector(text=r"^open\b", match="regex")
        self.assertTrue(sel.matches_text("Open File"))
        self.assertFalse(sel.matches_text("Reopen"))

    def test_bad_regex_is_usage_error(self) -> None:
        with self.assertRaises(UsageError):
            Selector(text="(", match="regex").matches_text("x")

    def test_unknown_keys(self) -> None:
        with self.assertRaises(UsageError):
            Selector.from_dict({"rol": "button"})

    def test_from_dict_aliases(self) -> None:
        sel = Selector.from_dict({"case_sensitive": True, "visibleOnly": False, "windowId": "0x1"})
        self.assertTrue(sel.case)
        self.assertFalse(sel.visible_only)
        self.assertEqual(sel.window_id, "0x1")

    def test_role_normalisation(self) -> None:
        for spelling in ("push button", "PUSH_BUTTON", "PushButton", "push-button"):
            self.assertEqual(normalize_role(spelling), "push button")
        self.assertTrue(role_matches("Push Button", "push-button"))
        self.assertFalse(role_matches("entry", "push button"))

    def test_states(self) -> None:
        sel = Selector(states={"showing": True, "enabled": False})
        states = {"showing"}
        self.assertTrue(sel.matches_states(lambda s: s in states))

    def test_to_dict_roundtrip(self) -> None:
        sel = Selector(role="entry", name="Search", match="regex", states={"focused": True}, window="Dolphin")
        self.assertEqual(Selector.from_dict(sel.to_dict()), sel)

    def test_describe(self) -> None:
        self.assertEqual(Selector(text="Save").describe(), "text~='Save'")
        self.assertEqual(Selector(name="Save", match="exact").describe(), "name=='Save'")
        self.assertEqual(Selector(role="entry", states={"focused": True, "enabled": False}).describe(),
                         "role=entry and focused and not enabled")
        self.assertEqual(Selector().describe(), "*")


class KeyTests(unittest.TestCase):
    def test_parse_combo(self) -> None:
        self.assertEqual(keys.parse_combo("Ctrl+Shift+t"), (["CTRL", "SHIFT"], "t"))
        self.assertEqual(keys.parse_combo("alt+F4"), (["ALT"], "F4"))
        self.assertEqual(keys.parse_combo("Return"), ([], "Return"))
        self.assertEqual(keys.parse_combo("enter"), ([], "Return"))
        self.assertEqual(keys.parse_combo("CTRL++"), (["CTRL"], "+"))
        self.assertEqual(keys.parse_combo("super+x"), (["SUPER"], "x"))
        self.assertEqual(keys.parse_combo("super"), ([], "super"))

    def test_unknown_modifier(self) -> None:
        with self.assertRaises(UsageError):
            keys.parse_combo("hyperreal+x")

    def test_keysym_names(self) -> None:
        self.assertEqual(keys.normalize_key_name("PageDown"), "Next")
        self.assertEqual(keys.normalize_key_name("arrowup"), "Up")
        self.assertEqual(keys.normalize_key_name("a"), "a")
        self.assertEqual(keys.normalize_key_name("KP_5"), "KP_5")


class ScreenTests(unittest.TestCase):
    def test_logical_device_roundtrip(self) -> None:
        layout = map_single(1920, 1080, scale=1.5)
        self.assertEqual(layout.logical_to_capture(100, 50), (150, 75))
        self.assertEqual(layout.capture_to_logical(150, 75), (100, 50))

    def test_element_center(self) -> None:
        layout = map_single(1920, 1080)
        self.assertEqual(layout.element_center({"x": 10, "y": 20, "width": 100, "height": 40}), (60, 40))

    def test_infer_scale(self) -> None:
        layout = map_single(1600, 900)
        self.assertEqual(infer_scale((2400, 1350), layout), 1.5)
        self.assertEqual(infer_scale((1600, 900), layout), 1.0)

    def test_from_outputs_multi_screen(self) -> None:
        layout = map_from_outputs([
            {"name": "eDP-1", "x": 0, "y": 0, "width": 1280, "height": 720, "scale": 1.0},
            {"name": "DP-1", "x": 1280, "y": 0, "width": 2560, "height": 1440, "scale": 2.0},
        ])
        self.assertEqual(layout.logical_extent(), {"x": 0, "y": 0, "width": 3840, "height": 1440})
        self.assertEqual(layout.screen_for(1400, 10).name, "DP-1")
        self.assertEqual(layout.logical_to_capture(1400, 10), (2800, 20))
        self.assertEqual(layout.capture_to_logical(2800, 20), (1400, 10))


class SegmentMapTests(unittest.TestCase):
    def test_single_screen_contains(self) -> None:
        screen = Screen("HDMI-1", 0, 0, 1920, 1080)
        self.assertTrue(screen.contains(1919, 1079))
        self.assertFalse(screen.contains(1920, 0))
        self.assertFalse(ScreenMap().screens)


class WaitTests(unittest.TestCase):
    def test_immediate(self) -> None:
        self.assertEqual(wait_for(lambda: "value", timeout=0.5), "value")

    def test_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        def probe() -> bool:
            calls["n"] += 1
            return calls["n"] >= 3

        self.assertTrue(wait_for(probe, timeout=2.0, interval=0.01))
        self.assertGreaterEqual(calls["n"], 3)

    def test_timeout_details(self) -> None:
        with self.assertRaises(KdeUiaError) as ctx:
            wait_for(lambda: False, timeout=0.05, interval=0.01, what="a window", state=lambda: ["x"])
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertEqual(ctx.exception.details["lastState"], ["x"])


class OpsProtocolTests(unittest.TestCase):
    def test_env_op_is_json_and_codes_stable(self) -> None:
        from kde_uia import ops_cli
        from kde_uia.errors import ERROR_CODES

        self.assertIn("ATSPI_UNAVAILABLE", ERROR_CODES)
        self.assertTrue(hasattr(ops_cli, "main"))

    def test_unknown_op_exits_usage(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        from kde_uia.ops_cli import main

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["no-such-op"])
        self.assertEqual(code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "USAGE")

    def test_bad_json_args(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        from kde_uia.ops_cli import main

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["windows", "--args", "{not json"])
        self.assertEqual(code, 2)
        self.assertIn("invalid JSON", json.loads(buffer.getvalue())["error"]["message"])


class ErrorShapeTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        error = AmbiguousError("two", hint="pick one", details={"count": 2})
        self.assertEqual(error.to_dict(), {"code": "AMBIGUOUS", "message": "two", "hint": "pick one",
                                           "details": {"count": 2}})


class EnvTests(unittest.TestCase):
    def test_detect_environment_never_raises(self) -> None:
        from kde_uia.env import detect_environment

        env = detect_environment(probe_atspi=False)
        payload = env.to_dict()
        self.assertIn("platform", payload)
        self.assertIn("tools", payload)
        self.assertIsInstance(payload["tools"], dict)
        self.assertIn(payload["sessionType"], ("wayland", "x11", "unknown"))

    def test_require_display_context(self) -> None:
        from kde_uia.env import require_display_context

        saved = {k: os.environ.pop(k, None) for k in ("DISPLAY", "WAYLAND_DISPLAY")}
        try:
            with self.assertRaises(KdeUiaError) as ctx:
                require_display_context()
            self.assertIn(ctx.exception.code, ("NO_DISPLAY", "NO_GUI_CONTEXT"))
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


test_pure_last_surface: dict = {}


def _fake_surface():
    """A tiny in-memory imitation of the Atspi calls TreeSession/Element use."""

    class Rect:
        def __init__(self, x, y, w, h):
            self.x, self.y, self.width, self.height = x, y, w, h

    class Node:
        def __init__(self, role, name, *, showing=True, focused=False, actions=(), value=None, kids=()):
            self.role, self._name = role, name
            self.showing, self.focused = showing, focused
            self._actions, self._value = list(actions), value
            self.parent = None
            self.index_in_parent = None
            self.kids = []
            for kid in kids:
                self.add(kid)

        def add(self, kid):
            kid.parent = self
            kid.index_in_parent = len(self.kids)
            self.kids.append(kid)

        # --- Atspi.Accessible surface used by kde_uia.element
        def get_role_name(self):
            return self.role

        def get_role(self):
            return 0

        def get_name(self):
            return self._name

        def get_description(self):
            return ""

        def path_suffix(self):
            return None

        def get_accessible_object_path(self):
            return "/org/a11y/atspi/accessible/" + self._name

        def get_state_set(self):
            node = self

            class StateSet:
                def contains(self, bit):
                    return {
                        "STATE_SHOWING": node.showing,
                        "STATE_FOCUSED": node.focused,
                        "STATE_SENSITIVE": True,
                    }.get(bit.split(".")[-1], False)

            return StateSet()

        def get_child_count(self):
            return len(self.kids)

        def get_child_at_index(self, index):
            return self.kids[index] if 0 <= index < len(self.kids) else None

        def get_extents(self, coord):
            return Rect(self.x, self.y, self.w, self.h) if hasattr(self, "x") else Rect(0, 0, 0, 0)

        def get_action_count(self):
            return len(self._actions)

        def get_action_name(self, index):
            return self._actions[index]

        def do_action(self, index, name):
            self.last_action = name
            return name in self._actions

        def get_text(self):
            raise RuntimeError("no text interface")

        def get_character_count(self):
            raise RuntimeError("no text interface")

        def get_current_value(self):
            raise RuntimeError("no value interface")

        def grab_focus(self):
            return True

        def get_attributes(self):
            return {}

    class AtspiNs:
        class StateType:
            STATE_SHOWING = "Atspi.StateType.STATE_SHOWING"
            STATE_FOCUSED = "Atspi.StateType.STATE_FOCUSED"
            STATE_SENSITIVE = "Atspi.StateType.STATE_SENSITIVE"

        class CoordType:
            SCREEN = "Atspi.CoordType.SCREEN"
            WINDOW = "Atspi.CoordType.WINDOW"

    class Conn:
        atspi = AtspiNs

        def __init__(self, roots):
            self.desktop = Node("desktop frame", "", kids=roots)
            self.dispatch = lambda: self.desktop

    save = Node("push button", "Save", actions=("click",))
    cancel = Node("push button", "Cancel", actions=("click",))
    hidden = Node("push button", "Hidden", showing=False)
    entry = Node("entry", "Filter", focused=True)
    toolbar = Node("tool bar", "mainToolBar", kids=(save, cancel, hidden))
    frame = Node("frame", "Dolphin", kids=(toolbar, entry))
    frame.x, frame.y, frame.w, frame.h = 100, 100, 800, 600
    save.x, save.y, save.w, save.h = 120, 140, 60, 24
    app = Node("application", "dolphin", kids=(frame,))
    # A second application whose frame is wrapped by a KWin "titlebar" bridge.
    inner = Node("frame", "Konsole", kids=())
    bridge = Node("frame", "Konsole", kids=(Node("titlebar", "", kids=(inner,)),))
    konsole = Node("application", "konsole", kids=(bridge,))
    conn = Conn([app, konsole])
    test_pure_last_surface.clear()
    test_pure_last_surface["conn"] = conn
    test_pure_last_surface["desktop"] = conn.desktop
    return conn, conn.desktop


class TreeSessionTests(unittest.TestCase):
    """Exercise enumeration, finding, refs and rendering against a fake tree."""

    def setUp(self) -> None:
        from kde_uia.tree import TreeSession

        self.conn, self.desktop = _fake_surface()
        self.session = TreeSession(self.conn)

    def test_windows(self) -> None:
        windows = self.session.windows()
        self.assertEqual([w.title for w in windows], ["Dolphin", "Konsole"])
        self.assertEqual([w.app for w in windows], ["dolphin", "konsole"])
        self.assertEqual(windows[0].ref, "uia:1:dolphin:0")
        # The KWin titlebar bridge is unwrapped to the real toplevel frame.
        self.assertEqual(windows[1].ref, "uia:1:konsole:0/0/0")

    def test_hidden_windows_excluded(self) -> None:
        self.desktop.kids[0].kids[0].showing = False
        self.assertEqual([w.title for w in self.session.windows()], ["Konsole"])
        self.assertEqual(len(self.session.windows(include_hidden=True)), 2)

    def test_find_by_role_and_name(self) -> None:
        from kde_uia.selector import Selector

        found = self.session.find(Selector(role="push-button", name="save"))
        self.assertEqual([e.name() for e in found], ["Save"])
        self.assertEqual(found[0].ref(), "uia:1:dolphin:0/0/0")

    def test_find_skips_invisible(self) -> None:
        from kde_uia.selector import Selector

        self.assertEqual(self.session.find(Selector(name="Hidden")), [])
        self.assertEqual(len(self.session.find(Selector(name="Hidden", visible_only=False))), 1)

    def test_find_normalises_role_spelling(self) -> None:
        from kde_uia.selector import Selector

        for spelling in ("push-button", "PUSH_BUTTON", "push button"):
            self.assertEqual(len(self.session.find(Selector(role=spelling, name="Save"))), 1, spelling)

    def test_resolve_ref_roundtrip(self) -> None:
        element = self.session.resolve_ref("uia:1:dolphin:0/0/1")
        self.assertEqual(element.name(), "Cancel")

    def test_resolve_stale_ref(self) -> None:
        with self.assertRaises(KdeUiaError) as ctx:
            self.session.resolve_ref("uia:1:dolphin:0/0/9")
        self.assertEqual(ctx.exception.code, "INVALID_REF")
        with self.assertRaises(KdeUiaError):
            self.session.resolve_ref("uia:1:konsole:0/0/7")

    def test_focused_and_active_window(self) -> None:
        self.assertEqual(self.session.focused().name(), "Filter")
        self.assertEqual(self.session.active_window().title, "Dolphin")

    def test_find_roots_scoping(self) -> None:
        from kde_uia.selector import Selector

        scoped = Selector(name="Save", window="Dolp")
        self.assertEqual(len(self.session.find(scoped)), 1)
        matching = self.session.find(Selector(name="Save", window="Konsole"))
        self.assertEqual(matching, [])
        with self.assertRaises(KdeUiaError) as ctx:
            self.session.find(Selector(name="Save", window="NoSuchWindow"))
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_ambiguity_is_explicit(self) -> None:
        from kde_uia.selector import Selector

        self.desktop.kids[0].kids[0].kids[0].kids[1]._name = "Save"
        with self.assertRaises(KdeUiaError) as ctx:
            self.session.resolve_element(selector=Selector(name="Save", role="push button"))
        self.assertEqual(ctx.exception.code, "AMBIGUOUS")
        self.assertIn("uia:1:dolphin", str(ctx.exception))

    def test_windows_matching_reports_candidates(self) -> None:
        from kde_uia.selector import Selector

        with self.assertRaises(KdeUiaError) as ctx:
            self.session.resolve_window(Selector(window="Dolphin", app="kwrite"))
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertIn("Dolphin", ctx.exception.hint)

    def test_render_tree_text(self) -> None:
        from kde_uia.tree import TreeRenderOptions, render_tree

        rendered = render_tree(self.session, self.session.windows()[0].element, TreeRenderOptions(max_depth=4))
        self.assertIn("frame 'Dolphin'", rendered.text)
        self.assertIn("push button 'Save'", rendered.text)
        self.assertNotIn("Hidden", rendered.text)
        self.assertIn("uia:1:dolphin:0/0/0", rendered.text)
        self.assertIn("actions=click", rendered.text)

    def test_render_tree_depth_limit(self) -> None:
        from kde_uia.tree import TreeRenderOptions, render_tree

        rendered = render_tree(self.session, self.session.windows()[0].element, TreeRenderOptions(max_depth=1))
        self.assertTrue(rendered.truncated)
        self.assertIn("max-depth reached", rendered.text)


class OpsTargetTests(unittest.TestCase):
    def test_resolve_target_prefers_ref(self) -> None:
        from kde_uia import ops
        from kde_uia.session import DesktopSession

        cache: dict[str, object] = {}

        class FakeTree:
            def resolve_ref(self, ref):
                cache["ref"] = ref
                return "element"

        class Session:
            tree = FakeTree()

        element, _ = ops._resolve_target(Session(), {"ref": "uia:1:a:1"})  # type: ignore[arg-type]
        self.assertEqual(element, "element")
        self.assertEqual(cache["ref"], "uia:1:a:1")
        _ = DesktopSession

    def test_resolve_target_requires_something(self) -> None:
        from kde_uia import ops

        class Session:
            tree = None

        with self.assertRaises(KdeUiaError) as ctx:
            ops._resolve_target(Session(), {})  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "USAGE")
        self.assertIn("ref", ctx.exception.hint)


class DistroHintTests(unittest.TestCase):
    """Arch Linux is the primary target: hints must be correct there, not just plausible."""

    def test_arch_package_names(self) -> None:
        from kde_uia.atspi_client import PACKAGE_HINTS

        # Checked against archlinux.org package files / AUR RPC.
        expected = {
            "qdbus6": "qt6-tools",          # /usr/bin/qdbus6 ships in qt6-tools
            "kwriteconfig6": "kconfig",     # kreadconfig6/kwriteconfig6 ship in kconfig
            "xdotool": "xdotool",
            "wtmctrl": "wtmctrl",
        }
        self.assertIn("qt6-tools", PACKAGE_HINTS["qdbus6"])
        self.assertIn("kconfig", PACKAGE_HINTS["kwriteconfig6"])
        # kdotool is *not* in the official repos (archlinux.org search: 0 results);
        # it is AUR-only, and saying otherwise makes users install the wrong thing.
        self.assertIn("AUR", PACKAGE_HINTS["kdotool"])
        _ = expected

    def test_atspi_hint_names_the_right_arch_package(self) -> None:
        from kde_uia.atspi_client import AT_SPI_IMPORT_HINT

        self.assertIn("python-gobject at-spi2-core", AT_SPI_IMPORT_HINT)
        self.assertIn("Atspi-2.0.typelib", AT_SPI_IMPORT_HINT)
        # Arch has no gir1.2-atspi-2.0 package; that spelling must stay Debian-only.
        self.assertNotIn("Arch: sudo pacman -S gir1.2-atspi-2.0", AT_SPI_IMPORT_HINT)

    def test_kwin_bridge_reports_missing_config_writer_early(self) -> None:
        """busctl/gdbus cannot write KWin config: fail at construction, with a hint."""
        from kde_uia import window_backends as wb

        class FakeWhich:
            def __init__(self, available: set[str]) -> None:
                self.available = available

            def __call__(self, name: str):
                return f"/usr/bin/{name}" if name in self.available else None

        original = wb.shutil.which
        try:
            # busctl exists, no kwriteconfig6: must fail in __init__, not later.
            wb.shutil.which = FakeWhich({"busctl"})
            with self.assertRaises(KdeUiaError) as ctx:
                wb.DbusCli()
            self.assertEqual(ctx.exception.code, "BACKEND_UNAVAILABLE")
            self.assertIn("kconfig", ctx.exception.hint.lower())
            self.assertIn("Arch", ctx.exception.hint)

            # With kwriteconfig6 present the bridge can hand commands over.
            wb.shutil.which = FakeWhich({"busctl", "kwriteconfig6"})
            self.assertEqual(wb.DbusCli().kind, "busctl")

            # qdbus6 always works (it can write entry itself).
            wb.shutil.which = FakeWhich({"qdbus6"})
            self.assertEqual(wb.DbusCli().kind, "qdbus6")
        finally:
            wb.shutil.which = original

    def test_no_hint_tells_arch_users_to_install_a_debian_package(self) -> None:
        """A Debian-only package name must never be the only suggestion."""
        import glob
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src" / "kde_uia"
        debian_only = ("gir1.2-atspi-2.0", "qdbus-qt6", "kconfig-cli")
        for path in glob.glob(str(src / "*.py")):
            text = Path(path).read_text(encoding="utf-8")
            for token in debian_only:
                if token in text:
                    # it may appear, but only next to an Arch suggestion
                    index = text.index(token)
                    window = text[max(0, index - 400): index + 400]
                    self.assertIn(
                        "Arch",
                        window,
                        f"{Path(path).name} suggests Debian package {token!r} without an Arch equivalent nearby",
                    )


if __name__ == "__main__":
    unittest.main()
