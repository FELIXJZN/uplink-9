"""Touchscreen detection + touch UI tests. The GUI tests run headless (SDL dummy
driver) and simulate finger taps; they are skipped if pygame isn't installed."""
import os
import unittest

from uplink import touch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame

    from uplink import config, gui
except ImportError:  # pragma: no cover
    pygame = None

DEVICES = """\
I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="Goodix Capacitive TouchScreen"
H: Handlers=mouse0 event1
B: PROP=2
B: EV=b
B: KEY=400 0 0 0 0 0
B: ABS=2658000 3

I: Bus=0018 Vendor=06cb Product=7e7e Version=0100
N: Name="SYNA2B31:00 06CB:7E7E Touchpad"
H: Handlers=mouse1 event2
B: PROP=5
B: EV=1b
B: ABS=2e0800000000003

I: Bus=0011 Vendor=0001 Product=0001 Version=ab41
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: PROP=0
B: EV=120013
"""


class DetectTests(unittest.TestCase):
    def test_finds_only_the_touchscreen(self):
        found = [d["name"] for d in touch.parse_devices(DEVICES) if touch.is_touchscreen(d, 64)]
        self.assertEqual(found, ["Goodix Capacitive TouchScreen"])

    def test_32bit_bitmask_words(self):
        # ABS_MT_POSITION_X (bit 53) lands in the second word on 32-bit kernels
        dev = {"name": "ts", "prop": "2", "ev": "b", "abs": "200000 0"}
        self.assertTrue(touch.is_touchscreen(dev, 32))

    def test_missing_file(self):
        self.assertEqual(touch.detect("/nonexistent"), [])


@unittest.skipIf(pygame is None, "pygame not installed")
class TouchGuiTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        surface = pygame.display.set_mode((720, 720))
        cfg = config.load(path=__import__("pathlib").Path("/nonexistent/cfg.json"))
        cfg["effects"]["typing"] = False
        self.scr = gui.GuiScreen(surface, cfg, touch=True)
        pygame.event.clear()

    def tearDown(self):
        pygame.quit()

    def tap(self, rect):
        pos = rect.center
        for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            pygame.event.post(pygame.event.Event(kind, pos=pos, button=1, touch=True))

    def test_tap_menu_item(self):
        rects = self.scr._menu_rects(5, 0)
        self.tap(rects[2][0])
        self.assertEqual(self.scr.menu("T", ["a", "b", "c", "d", "e"]), 2)

    def test_back_button(self):
        self.scr.frame("T")
        self.tap(self.scr._back_rect)
        self.assertIsNone(self.scr.menu("T", ["a", "b"]))

    def test_swipe_is_not_a_tap(self):
        rect = self.scr._menu_rects(30, 0)[0][0]
        post = pygame.event.post
        post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
        post(pygame.event.Event(pygame.MOUSEMOTION, pos=(rect.centerx, rect.centery - 200),
                                rel=(0, -200), buttons=(1, 0, 0)))
        post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(rect.centerx, rect.centery - 200), button=1))
        post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="\x1b"))
        self.assertIsNone(self.scr.menu("T", [str(i) for i in range(30)]))

    def test_on_screen_keyboard(self):
        keys = {label: rect for rect, _, label in self.scr._keyboard_layout("abc")}
        for label in ("h", "i", "SPACE", "Aa"):
            self.tap(keys[label])
        upper = {label: rect for rect, _, label in self.scr._keyboard_layout("ABC")}
        self.tap(upper["X"])
        self.tap(keys["x"])   # shift was one-shot, back to lowercase
        self.tap(keys["DEL"])
        self.tap(keys["OK"])
        self.assertEqual(self.scr.prompt("T", "TYPE:"), "hi X")

    def test_confirm_buttons(self):
        yes, no = self.scr._confirm_rects()
        self.tap(yes)
        self.assertTrue(self.scr.confirm("T", "Sure?"))
        self.tap(no)
        self.assertFalse(self.scr.confirm("T", "Sure?"))

    def test_physical_keyboard_still_works(self):
        for key, ch in ((pygame.K_j, "j"), (pygame.K_j, "j"), (pygame.K_RETURN, "\r")):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=ch))
        self.assertEqual(self.scr.menu("T", ["a", "b", "c"]), 2)

    def test_touch_turns_on_when_detection_missed(self):
        self.scr.touch = False
        self.scr._layout()
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(5, 5), button=1, touch=True))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode=""))
        self.scr.menu("T", ["a"])
        self.assertTrue(self.scr.touch)


if __name__ == "__main__":
    unittest.main()
