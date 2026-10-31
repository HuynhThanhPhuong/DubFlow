"""Conservative OCR/ASR agreement gate for newly analyzed Chinese videos."""
import re
import math
from difflib import SequenceMatcher


def source_chunks(result, duration):
    """Keep ASR segments independent; neither pitch nor punctuation identifies a person."""
    output=[]
    for index,chunk in enumerate(result.get('chunks',[])):
        start,end=chunk.get('timestamp',[None,None])
        start=0 if start is None else float(start)
        end=duration if end is None else min(duration,float(end))
        text=chunk.get('text','').strip()
        if not text:continue
        if not all(math.isfinite(v) for v in (start,end)) or not 0<=start<end<=duration:
            raise ValueError('ASR trả mốc câu không hợp lệ. Cần đối chiếu nguồn.')
        cid=f'asr-{index+1:06}'
        output.append(dict(id=cid,start=start,end=end,speaker='unconfirmed',original=text,text='',
                           source_ids=[cid],status='needs_review',speaker_hint=True))
    return output


def chinese(text):
    return ''.join(re.findall(r'[\u3400-\u9fff]',text))


def align_ocr_cues(cues, regions):
    """Use on-screen sentence boundaries only when they cover the ASR content.

    Incomplete OCR must never discard uncaptioned dialogue. Caller only invokes
    this before any translation/editor changes, and retains the raw ASR cues.
    """
    rows=[]
    for region in sorted(regions,key=lambda r:(r['start'],r['end'])):
        if not region.get('enabled') or region.get('kind')!='subtitle' or not chinese(region.get('text','')):
            continue
        row=dict(region)
        match=next((r for r in reversed(rows) if chinese(r['text'])==chinese(row['text']) and row['start']<=r['end']+.26),None)
        if match:
            match['end']=max(match['end'],row['end'])
        else:
            rows.append(row)
    source=chinese(''.join(c.get('original','') for c in cues))
    target=chinese(''.join(r['text'] for r in rows))
    if not source or not target:
        return None
    matched=sum(block.size for block in SequenceMatcher(None,source,target,autojunk=False).get_matching_blocks())
    # A clip may end mid-utterance while its final complete caption is already visible.
    caption_extends_clip = target.startswith(source) and len(target)-len(source)<=10
    if matched/len(source)<.95 or (matched/len(target)<.95 and not caption_extends_clip):
        return None
    output=[]
    for index,r in enumerate(rows):
        # Conflicting simultaneous subtitles need manual review, not flattening.
        if index and r['start']<rows[index-1]['end']-.05:
            return None
        overlaps=[c for c in cues if c['start']<r['end'] and c['end']>r['start']]
        speaker=max(overlaps,key=lambda c:min(c['end'],r['end'])-max(c['start'],r['start'])).get('speaker','speaker-1') if overlaps else 'speaker-1'
        output.append(dict(id=f'ocr-c{index+1}',start=r['start'],end=r['end'],speaker=speaker,
                           original=r['text'],text='',status='needs_review',speaker_hint=True))
    return output or None
