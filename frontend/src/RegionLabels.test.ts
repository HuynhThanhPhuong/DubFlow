import {expect,it} from 'vitest';
import {placeRegionLabel} from './regionGeometry';
import type {VideoRect} from './regionGeometry';
it('keeps narrow vertical and adjacent horizontal labels readable inside letterboxing',()=>{
  const rect={left:0,top:3,width:331,height:186};
  const used:VideoRect[]=[];
  const labels=[{left:7,top:173},{left:97,top:173},{left:286,top:38}].map(box=>placeRegionLabel(box,rect,used));
  for(const a of labels) {
    expect(a.width).toBe(112);
    expect(a.left).toBeGreaterThanOrEqual(0);expect(a.left+a.width).toBeLessThanOrEqual(331);
    expect(a.top).toBeGreaterThanOrEqual(3);expect(a.top+a.height).toBeLessThanOrEqual(189);
    for(const b of labels)if(a!==b)expect(a.left<b.left+b.width&&a.left+a.width>b.left&&a.top<b.top+b.height&&a.top+a.height>b.top).toBe(false);
  }
});
