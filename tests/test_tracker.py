from pathlib import Path

import cv2
import pytest

from roll_viewer.reader import Panel, StatLine
from roll_viewer.rolls import DAMAGE, WEAPON, Item
from roll_viewer.tracker import CHANGED, NOTHING_SHOWN, UNCHANGED, TooltipTracker

SCREENSHOTS = Path(__file__).parent / "screenshots"
# The "Current" staff in live_compare_weapon.png
STAFF = Panel(Item(WEAPON, 18, 86, True, {DAMAGE: 1805}), "Ominous Fire Staff",
              [StatLine(DAMAGE, 1805, 370, "- Damage: 1805 + 370", (617, 544, 771, 556))], 9.3, (617, 526, 655, 535))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def frame():
    return cv2.imread(str(SCREENSHOTS / "live_compare_weapon.png"))


def make(results):
    reads = []

    def read(frame, regions=None):
        reads.append(regions)
        return results.pop(0)

    clock = Clock()
    return TooltipTracker(read, refresh_every=1.5, clock=clock), reads, clock


def test_unchanged_tooltip_is_not_read_again(frame):
    tracker, reads, _ = make([[STAFF]])
    assert tracker.look(frame) == NOTHING_SHOWN
    tracker.read(frame)
    assert tracker.look(frame.copy()) == UNCHANGED
    assert tracker.shown == [STAFF] and len(reads) == 1


def test_closing_the_tooltip_drops_the_labels_at_once(frame):
    tracker, _, _ = make([[STAFF]])
    tracker.read(frame)
    closed = cv2.imread(str(SCREENSHOTS / "equipped_boots.png"))  # same game, other screen
    assert tracker.look(closed) == CHANGED
    assert tracker.shown == []


def test_a_single_changed_number_is_noticed(frame):
    tracker, _, _ = make([[STAFF]])
    tracker.read(frame)
    other = frame.copy()
    other[544:556, 690:700] = other[544:556, 680:690]  # one digit of "1805" replaced by its neighbour
    assert tracker.look(other) == CHANGED


def test_changes_elsewhere_are_ignored(frame):
    tracker, _, _ = make([[STAFF]])
    tracker.read(frame)
    other = frame.copy()
    other[600:800, 0:400] = 255 - other[600:800, 0:400]  # the character moving on the left
    other[280:340, 740:800] = 0  # the item icon sparkling
    assert tracker.look(other) == UNCHANGED


def test_refresh_never_hides_labels_on_a_missed_read(frame):
    tracker, _, clock = make([[STAFF], []])
    tracker.read(frame)
    assert not tracker.refresh_due()
    clock.now = 2.0
    assert tracker.refresh_due()
    tracker.read(frame, refresh=True)
    assert tracker.shown == [STAFF]


def test_after_a_change_the_old_place_is_read_first_then_everything(frame):
    tracker, reads, _ = make([[STAFF], [STAFF], [STAFF]])
    tracker.read(frame)
    changed = frame.copy()
    changed[544:556, 690:700] = 0
    assert tracker.look(changed) == CHANGED
    tracker.read(changed)
    assert reads[1] is not None and reads[1][0][0] < 617 < reads[1][0][2]  # around the old tooltip
    assert tracker.refresh_due()  # the whole frame comes next, for tooltips opened elsewhere
    tracker.read(changed, refresh=True)
    assert reads[2] is None


def test_falls_back_to_the_whole_frame(frame):
    tracker, reads, _ = make([[STAFF], [], []])
    tracker.read(frame)
    closed = frame.copy()
    closed[500:600, 600:900] = 0
    assert tracker.look(closed) == CHANGED
    assert tracker.read(closed) == []
    assert reads[1] is not None and reads[2] is None
