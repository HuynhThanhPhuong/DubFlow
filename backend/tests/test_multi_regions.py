import tempfile
import unittest
from pathlib import Path
from dubflow import pipeline as p
from dubflow.multi_regions import erase_regions, read_regions


class MultiRegionIntegrationTests(unittest.TestCase):
    def test_cleanup_records_a_fallback_from_any_region_and_chains_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/'source.mp4';source.write_bytes(b'source')
            p.write(folder/'subtrack.json',dict(version=3,regions=[dict(segments=[dict(s=0,e=2)])]*2))
            calls=[]
            def erase(target, request):
                calls.append(request)
                (target/'clean.mp4').write_bytes(Path(request['source']).read_bytes()+b'clean')
                p.write(target/'erase.json',dict(fill='lama' if len(calls)==1 else 'smooth',lama=len(calls)==1,seconds=1,warnings=[]))
            erase_regions(folder,dict(source=str(source),static_regions=[dict(id='logo')]),erase)
            self.assertEqual((folder/'clean.mp4').read_bytes(),b'sourcecleanclean')
            self.assertEqual(calls[1]['static_regions'],[])
            self.assertEqual(p.read(folder/'erase.json')['fill'],'lama+smooth')
            self.assertFalse(p.read(folder/'erase.json')['lama'])

    def test_ocr_retains_each_region_and_each_track_for_independent_erasure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            specs=[dict(box=[10,100,200,40],orientation='h'),dict(box=[500,20,40,300],orientation='v')]
            def read(target, request):
                x,y,w,h=request['box']
                p.write(target/'subtrack.json',dict(version=2,box=request['box'],segments=[dict(s=1,e=3,text='你好',x0=x,y0=y,x1=x+w,y1=y+h)]))
            read_regions(folder,dict(subtitles=specs),read)
            track=p.read(folder/'subtrack.json')
            self.assertEqual(track['version'],3)
            self.assertEqual([s['region'] for s in track['segments']],[0,1])
            self.assertEqual([s['box'] for s in track['segments']],[[10,100,210,140],[500,20,540,320]])
            self.assertEqual([r['box'] for r in track['regions']],[r['box'] for r in specs])
