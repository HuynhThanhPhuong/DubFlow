"""Bounded OCR of ambiguous names, using the existing reader and local frames only."""
from pathlib import Path
import subprocess
import hashlib

try:
    from .name_ocr import names_in, name_conflicts, reconcile_names
except ImportError:
    from name_ocr import names_in, name_conflicts, reconcile_names


def initial_name_readings(image, result, reader):
    """Use character confidence to isolate uncertain names during the first read.

    The recognizer sees the name at its measured word boxes before sentence
    grouping. Both readings enter the vote, so uncertainty survives consolidation.
    """
    import cv2

    readings = []
    for row in result:
        if len(row) < 6:
            continue
        original = row[1]
        text = original
        for position, name in names_in(original):
            if position + len(name) > len(row[3]):
                continue
            confidence = min(row[5][position:position + len(name)])
            if confidence >= .85:
                continue
            boxes = row[3][position:position + len(name)]
            x0 = max(0, min(int(p[0]) for box in boxes for p in box) - 2)
            y0 = max(0, min(int(p[1]) for box in boxes for p in box) - 2)
            x1 = min(image.shape[1], max(int(p[0]) for box in boxes for p in box) + 2)
            y1 = min(image.shape[0], max(int(p[1]) for box in boxes for p in box) + 2)
            crop = image[y0:y1, x0:x1]
            if not crop.size:
                continue
            big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            found, _ = reader(big, use_cls=False, use_det=False)
            valid = [(candidate, score) for candidate, score in found or []
                     if len(candidate) == len(name) and names_in(candidate) == [(0, candidate)] and score >= .6]
            if valid:
                candidate, score = max(valid, key=lambda x: x[1])
                if score > confidence:
                    text = text[:position] + candidate + text[position + len(name):]
        if text != original:
            readings.append(dict(line=original.strip(), text=text, weight=float(row[2]) ** 2))
    return readings


def refine_name_segments(segments, directory, request, reader):
    """Read at most three central frames per suspect line, never scan the video again.

    Word boxes isolate each occurrence, including two names on the same line.
    Recognition-only calls on the small crop avoid repeated full-band detection.
    Original readings remain intact for review and unanimous evidence stays intact.
    """
    import cv2
    import numpy as np

    directory = Path(directory)
    extra_reads = 0
    for index, segment in enumerate(segments):
        names = names_in(segment['text'])
        if not names or segment.get('orientation') == 'v':
            continue
        if not name_conflicts(segment):
            continue
        if (directory / 'cancel.request').exists():
            raise RuntimeError('cancelled')
        # Read the measured line, including a small margin, inside the user's band.
        bx, by, bw, bh = request['box']
        x0, x1 = int(bx), int(bx + bw)
        y0, y1 = int(by), int(by + bh)
        if x1 <= x0 or y1 <= y0:
            continue
        evidence = []
        frames = []
        for fraction in (.3, .5, .7):
            t = float(segment['s']) + (float(segment['e']) - float(segment['s'])) * fraction
            proc = subprocess.run([request['ffmpeg'], '-v', 'error', '-ss', str(t), '-i', request['source'],
                                   '-vf', f'crop={x1-x0}:{y1-y0}:{x0}:{y0}:exact=1', '-frames:v', '1',
                                   '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True, check=True)
            if len(proc.stdout) != (x1-x0) * (y1-y0) * 3:
                continue
            image = np.frombuffer(proc.stdout, np.uint8).reshape(y1-y0, x1-x0, 3)
            frames.append(image)
            result, _ = reader(image, use_cls=False, return_word_box=True)
            result = [row for row in result or []
                      if segment['x0'] - 8 <= bx + sum(p[0] for p in row[0]) / len(row[0]) <= segment['x1'] + 8]
            extra_reads += 1
            if sum(len(names_in(row[1])) for row in result or []) != len(names):
                continue  # a missing name cannot shift the following name into its position
            ordinal = 0
            for row in result or []:
                if len(row) < 6:
                    ordinal += len(names_in(row[1]))
                    continue
                text, boxes = row[1], row[3]
                for position, name in names_in(text):
                    current_ordinal = ordinal
                    ordinal += 1
                    if current_ordinal >= len(names) or position + len(name) > len(boxes):
                        continue
                    glyphs = boxes[position:position + len(name)]
                    cx0 = max(0, min(int(p[0]) for box in glyphs for p in box) - 2)
                    cy0 = max(0, min(int(p[1]) for box in glyphs for p in box) - 2)
                    cx1 = min(image.shape[1], max(int(p[0]) for box in glyphs for p in box) + 2)
                    cy1 = min(image.shape[0], max(int(p[1]) for box in glyphs for p in box) + 2)
                    crop = image[cy0:cy1, cx0:cx1]
                    if not crop.size:
                        continue
                    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
                    variants = [big,
                                cv2.cvtColor(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], cv2.COLOR_GRAY2BGR),
                                cv2.cvtColor(cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)[1], cv2.COLOR_GRAY2BGR)]
                    for enhanced in variants:
                        reread, _ = reader(enhanced, use_cls=False, use_det=False)
                        extra_reads += 1
                        for candidate, score in reread or []:
                            # An isolated name has an exact span. Garbage or partial glyphs cannot vote.
                            found = names_in(candidate)
                            if len(found) == 1 and found[0][1] == candidate and score >= .6:
                                evidence.append(dict(ordinal=current_ordinal, name=candidate, weight=float(score) ** 4,
                                                     text=candidate, t=round(t, 3)))
        if evidence:
            segment['name_readings'] = evidence
        if frames:
            crops = directory / 'name-crops'
            crops.mkdir(exist_ok=True)
            band_key = hashlib.sha1(str(request['box']).encode()).hexdigest()[:8]
            path = crops / f'{band_key}-{index:06}-{float(segment["s"]):.3f}.png'
            crop_x0 = max(0, int(segment['x0'] - bx) - 6)
            crop_x1 = min(int(bw), int(segment['x1'] - bx) + 6)
            cv2.imencode('.png', frames[len(frames)//2][:, crop_x0:crop_x1])[1].tofile(str(path))
            segment['name_crop'] = path.relative_to(directory).as_posix()
    reconcile_names(segments)
    # Unanimous but unusual names still need an image for a human decision.
    for index, segment in enumerate(segments):
        if not segment.get('name_review') or segment.get('name_crop'):
            continue
        if (directory / 'cancel.request').exists():
            raise RuntimeError('cancelled')
        bx, by, bw, bh = request['box']
        x0 = max(int(bx), int(segment['x0']) - 6)
        x1 = min(int(bx + bw), int(segment['x1']) + 6)
        if x1 <= x0:
            continue
        crops = directory / 'name-crops'
        crops.mkdir(exist_ok=True)
        band_key = hashlib.sha1(str(request['box']).encode()).hexdigest()[:8]
        path = crops / f'{band_key}-{index:06}-{float(segment["s"]):.3f}.png'
        subprocess.run([request['ffmpeg'], '-v', 'error', '-ss', str((segment['s'] + segment['e']) / 2),
                        '-i', request['source'], '-vf', f'crop={x1-x0}:{int(bh)}:{x0}:{int(by)}:exact=1',
                        '-frames:v', '1', '-y', str(path)], capture_output=True, check=True)
        segment['name_crop'] = path.relative_to(directory).as_posix()
    return extra_reads
