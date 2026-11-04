"""Regenerate fixtures/layout-dot13.json (from backend/: set PYTHONPATH=. then python tests/gen_layout_fixture.py).

The same scenarios are checked by tests/test_layout_dot13.py (Python) and frontend/src/LayoutParity.test.tsx (browser mirror),
so ASS export and web preview cannot drift apart."""
import json
from pathlib import Path
from dubflow import subtitle_style as style
from dubflow.font_catalog import font_metrics

LONG = 'Cổ Tấn bái kiến sư tôn, bái kiến hai vị sư huynh đã lâu không gặp, ta nhớ mọi người lắm vô cùng'
BAND0 = [0, 661, 1280, 711]


def cue(i, start, end, text, box, text_height, region=0, band=BAND0, **extra):
    return dict(id=f'c{i}', start=start, end=end, speaker='s', original='原', text=text, box=box, band=band, region=region,
                text_height=text_height, **extra)


def scenarios():
    return {
        'bottom_two_lines': dict(cues=[
            cue(0, 0, 3, 'Xin chào các bạn', [369, 664, 873, 702], 30),
            cue(1, 4, 7, LONG, [369, 664, 873, 702], 36),
            cue(2, 8, 10, 'Cổ Tấn bái kiến sư tôn, bái kiến hai vị sư huynh', [447, 665, 835, 700], 33),
            cue(3, 11, 13, 'Một câu cực kỳ dài ' * 12, [369, 664, 873, 702], 33)], times=[1, 5, 9, 12]),
        'two_regions_stacked': dict(cues=[
            cue(0, 0, 4, 'Dòng trên của vùng hai', [500, 610, 780, 640], 33, region=1, band=[0, 601, 1280, 653]),
            cue(1, 0, 4, LONG, [369, 664, 873, 702], 33)], times=[1]),
        'auxiliary_and_dialogue': dict(cues=[
            cue(0, 0, 4, 'Gió cuốn bay', [1100, 100, 1190, 400], 30, region=2, band=[1000, 100, 1280, 400], orientation='v'),
            cue(1, 1, 3, 'Xin chào', [400, 664, 800, 702], 28)], times=[0.5, 2]),
        'legacy_box_without_band': dict(cues=[
            dict(id='a', start=0, end=3, speaker='s', original='原', text='Xin chào', box=[45, 657, 360, 709], text_height=38, region=0),
            dict(id='b', start=0, end=3, speaker='s', original='原', text=LONG, box=[100, 500, 400, 570], text_height=40, region=1)], times=[1]),
        'box_touching_bottom_edge': dict(cues=[
            cue(0, 0, 3, LONG, [300, 680, 900, 716], 36, band=[0, 670, 1280, 720])], times=[1]),
    }


def layouts(font_id='public-sans', width=1280, height=720):
    st = style.style_for(width, height, font_id)
    out = {}
    for name, sc in scenarios().items():
        rows = []
        for t in sc['times']:
            for i, c in enumerate(sc['cues']):
                if c['start'] <= t < c['end']:
                    fit = style.cue_layout(sc['cues'], i, width, height, t, st)
                    rows.append(dict(index=i, t=t, x=round(fit['x'], 6), y=round(fit['y'], 6), size=round(fit['size'], 6),
                                     align=fit['align'], lines=fit['lines'], overflow=bool(fit['overflow'])))
        out[name] = dict(cues=sc['cues'], rows=rows)
    return dict(font_id=font_id, width=width, height=height, style=st, advances=font_metrics(font_id), scenarios=out)


if __name__ == '__main__':
    path = Path(__file__).parent / 'fixtures' / 'layout-dot13.json'
    path.write_text(json.dumps(layouts(), ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote', path)
