import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SubtitlePreview, assignLanes, fitVideoRect, regionLayout } from './SubtitlePreview';
import type { Cue } from './types';
afterEach(cleanup);
const a: Cue = {id:'a',start:1,end:5,speaker:'s',original:'你好',text:'Bình an nhé',region:0,orientation:'v',box:[1100,100,1190,400]};
it('mirrors vertical ASS layout and warns when minimum size overflows', () => {
  const fit=regionLayout(a,1280,720);
  expect(fit.lines).toEqual(['Bình','an','nhé']);
  expect([fit.x,fit.y]).toEqual([1145,250]);
  expect(fit.overflow).toBe(false);
  expect(regionLayout({...a,box:[1100,100,1120,140]},1280,720).overflow).toBe(true);
});
it('gives simultaneous regions independent positions and renders one word per line', () => {
  const b={...a,id:'b',region:1,box:[100,500,500,570],orientation:'h' as const,text:'Chúng ta cùng nhau trở về nhà',text_height:28};
  expect(assignLanes([a,b])).toEqual([0,0]);
  render(<SubtitlePreview cues={[a,b]} now={2} regions={[]} width={1280} height={720} rect={fitVideoRect(1280,720,1280,720)} blurOriginal={false}/>);
  const nodes=screen.getAllByLabelText('Phụ đề Việt xem trước');
  expect(nodes[0].textContent).toBe('Bình\nan\nnhé');
  expect(nodes[0].style.top).toBe(`${250/720*100}%`);
  expect(nodes[1].style.left).toBe(`${300/1280*100}%`);
  expect(regionLayout(b,1280,720).size).toBeLessThanOrEqual(28);
});
