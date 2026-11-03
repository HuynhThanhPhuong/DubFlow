import unittest

class VerticalOCRTests(unittest.TestCase):
    def test_vertical_unfolding_orders_right_column_before_left(self):
        try:
            import numpy as np
            import cv2
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import unfold_vertical
        image = np.zeros((110, 60, 3), np.uint8)
        for x, y, color in [(38, 8, (220, 220, 220)), (38, 38, (230, 230, 230)), (5, 8, (240, 240, 240)), (5, 38, (250, 250, 250))]:
            cv2.rectangle(image, (x, y), (x+14, y+18), color, -1)
        row, height = unfold_vertical(image)
        self.assertGreater(row.shape[1], row.shape[0]*2)
        self.assertGreater(height, 10)
        cells = np.array_split(row, 4, axis=1)
        self.assertEqual([int(c.max()) for c in cells], [220, 230, 240, 250])

