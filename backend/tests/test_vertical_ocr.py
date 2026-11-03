import unittest

class VerticalOCRTests(unittest.TestCase):
    def test_gold_vertical_strokes_are_detected_below_white_threshold(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import vertical_strokes
        from dubflow.subtitle_erase import glyph_mask
        image=np.full((160,100,3),30,np.uint8)
        cv2.putText(image,'88',(15,80),cv2.FONT_HERSHEY_SIMPLEX,1.3,(40,155,220),3)
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        self.assertEqual(glyph_mask(gray,1).sum(),0)
        mask=vertical_strokes(image,1)
        gold=(image[:,:,2]>200)&(image[:,:,1]>100)
        self.assertGreater(mask[gold].mean(),.95)
        self.assertFalse(mask[:10].any())
    def test_sparse_strokes_of_one_character_are_not_dropped(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import unfold_vertical
        image=np.zeros((150,40,3),np.uint8)
        cv2.rectangle(image,(8,8),(30,30),(220,220,220),-1)
        cv2.line(image,(10,50),(29,50),(230,230,230),2)
        cv2.line(image,(10,70),(29,70),(230,230,230),2)
        cv2.rectangle(image,(8,95),(30,117),(240,240,240),-1)
        strip,_=unfold_vertical(image)
        self.assertEqual(strip.shape[1],3*56)

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

