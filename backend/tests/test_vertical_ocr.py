import unittest


class DimGoldVerticalTests(unittest.TestCase):
    def test_a_small_gold_background_patch_does_not_hide_white_vertical_text(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import unfold_vertical
        image=np.full((180,60,3),50,np.uint8)
        for y in (40,90,140):
            cv2.putText(image,'E',(25,y),cv2.FONT_HERSHEY_SIMPLEX,.8,(240,240,240),2,cv2.LINE_AA)
        cv2.rectangle(image,(3,5),(10,12),(20,120,160),-1)
        strip,height,boxes=unfold_vertical(image,return_boxes=True)
        self.assertEqual(len(boxes),3)
        self.assertTrue(all(box[0]>=25 for box in boxes))
        self.assertEqual(strip.shape,(56,168,3))

    def test_dim_gold_glyphs_are_unfolded_without_waiting_for_full_brightness(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import unfold_vertical
        image=np.full((180,60,3),50,np.uint8)
        for y in (40,90,140):
            cv2.putText(image,'E',(20,y),cv2.FONT_HERSHEY_SIMPLEX,.8,(20,120,160),2,cv2.LINE_AA)
        strip,height,boxes=unfold_vertical(image,return_boxes=True)
        self.assertEqual(len(boxes),3)
        self.assertEqual(strip.shape,(56,168,3))
        self.assertGreater(height,10)

class VerticalOCRTests(unittest.TestCase):
    def test_staggered_columns_do_not_merge_when_their_row_projections_touch(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from dubflow.vertical_ocr import unfold_vertical
        image = np.zeros((100, 80, 3), np.uint8)
        for x, y, color in [(5, 5, 240), (5, 35, 250), (35, 20, 220), (35, 50, 230)]:
            cv2.rectangle(image, (x, y), (x+19, y+19), (color, color, color), -1)
        strip, _ = unfold_vertical(image)
        self.assertEqual(strip.shape[1], 4*56)
        self.assertEqual([int(c.max()) for c in np.array_split(strip, 4, axis=1)], [220, 230, 240, 250])

    def test_chuan_disconnected_radicals_are_not_split_into_columns(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OCR environment required')
        from pathlib import Path
        from dubflow.vertical_ocr import unfold_vertical
        image = cv2.imread(str(Path(__file__).parent/'fixtures'/'vertical-chuan.png'))
        strip, _ = unfold_vertical(image)
        self.assertEqual(strip.shape[1], 2*56)
        # Two real columns of the same disconnected character retain their order.
        left = (image.astype(float)*(250/255)).astype(np.uint8)
        right = (image.astype(float)*(220/255)).astype(np.uint8)
        strip, _ = unfold_vertical(np.concatenate([left, right], axis=1))
        self.assertEqual(strip.shape[1], 4*56)
        self.assertEqual([int(c.max()) for c in np.array_split(strip, 4, axis=1)], [220, 220, 250, 250])

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

