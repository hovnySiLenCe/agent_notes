import unittest
from unittest import mock

from marginalia.platform.atspi import geometry as G


class Node:
    def __init__(self, role, rect, parent=None):
        self.role, self.rect, self.parent = role, rect, parent

    def get_role_name(self):
        return self.role

    def get_parent(self):
        return self.parent


def chain(*spec):
    n = None
    for role, rect in spec:
        n = Node(role, rect, n)
    return n


class VisibleAreaTest(unittest.TestCase):
    def area(self, leaf):
        with mock.patch.object(G, 'node_rect', lambda n: n.rect):
            return G.visible_area(leaf)

    def test_scrolled_out_of_its_pane(self):
        leaf = chain(('frame', (0, 0, 1000, 800)), ('document web', (0, 100, 1000, 700)),
                     ('section', (0, 100, 500, 300)), ('paragraph', (0, 600, 500, 30)), ('static', (0, 600, 500, 30)))
        self.assertEqual(self.area(leaf), G.EMPTY)

    def test_electron_native_views_in_logical_pixels(self):
        # VS Code at 2x: the window's native views report logical pixels, its web content physical ones
        leaf = chain(('frame', (70, 27, 3322, 1404)), ('panel', (70, 27, 3322, 1404)),
                     ('document web', (140, 54, 6644, 2808)), ('document web', (4800, 194, 1984, 2624)),
                     ('section', (4802, 281, 1982, 2537)), ('paragraph', (4902, 900, 1812, 40)),
                     ('static', (4902, 900, 1399, 31)))
        self.assertEqual(self.area(leaf), (4902, 900, 1812, 40))      # was EMPTY: never highlighted


if __name__ == '__main__':
    unittest.main()
