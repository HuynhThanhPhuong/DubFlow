"""Unfold upright vertical Chinese glyphs without rotating their strokes."""
import cv2
import numpy as np


def _runs(values, gap=0):
    indexes = np.flatnonzero(values)
    out = []
    for i in indexes:
        if out and i - out[-1][1] <= gap:
            out[-1][1] = int(i)+1
        else:
            out.append([int(i), int(i)+1])
    return out


def unfold_vertical(image):
    """Return a horizontal glyph strip and measured glyph height, right column first.

    Projection separates columns and character rows. Both white outlined captions
    and gold title lettering are supported; each glyph remains upright.
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bright = ((hsv[:, :, 2] > 175) & ((hsv[:, :, 1] < 95) | ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 42))))
    # Require local contrast to avoid turning flat highlights into characters.
    low = cv2.erode(gray, np.ones((7, 7), np.uint8))
    mask = bright & (gray.astype(np.int16)-low.astype(np.int16) > 20)
    cols = [(a, b) for a, b in _runs(mask.sum(axis=0) >= max(2, h*.012), max(2, round(w*.045))) if b-a >= 4]
    tiles, heights = [], []
    for x0, x1 in reversed(cols):
        cw = x1-x0
        rows = [(a, b) for a, b in _runs(mask[:, x0:x1].sum(axis=1) >= max(2, cw*.12), max(1, round(cw*.16))) if b-a >= max(4, cw*.22)]
        for y0, y1 in rows:
            count = max(1, round((y1-y0)/cw)) if y1-y0 > cw*1.7 else 1
            for i in range(count):
                a, b = round(y0+(y1-y0)*i/count), round(y0+(y1-y0)*(i+1)/count)
                crop = image[max(0, a-2):min(h, b+2), max(0, x0-2):min(w, x1+2)]
                tile = np.zeros((56, 56, 3), np.uint8)
                scale = min(48/crop.shape[0], 48/crop.shape[1])
                patch = cv2.resize(crop, (max(1, round(crop.shape[1]*scale)), max(1, round(crop.shape[0]*scale))))
                py, px = (56-patch.shape[0])//2, (56-patch.shape[1])//2
                tile[py:py+patch.shape[0], px:px+patch.shape[1]] = patch
                tiles.append(tile)
                heights.append(b-a)
    if not tiles:
        return image, min(w, h)
    return np.concatenate(tiles, axis=1), float(np.median(heights))
