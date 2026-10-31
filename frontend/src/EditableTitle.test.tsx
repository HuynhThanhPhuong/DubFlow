import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {EditableTitle} from './EditableTitle';
afterEach(cleanup);
it('saves a trimmed title only once when Enter is followed by blur',async()=>{
 const save=vi.fn().mockResolvedValue(undefined);
 render(<EditableTitle value="Video" disabled={false} onSave={save}/>);
 fireEvent.click(screen.getByRole('button',{name:'Video'}));
 const input=screen.getByRole('textbox');fireEvent.change(input,{target:{value:'  Tập 2  '}});
 fireEvent.keyDown(input,{key:'Enter'});fireEvent.blur(input);
 expect(save).toHaveBeenCalledExactlyOnceWith('Tập 2');
});
it('Escape preserves the existing title without saving',()=>{
 const save=vi.fn();render(<EditableTitle value="Video" disabled={false} onSave={save}/>);
 fireEvent.click(screen.getByRole('button',{name:'Video'}));
 const input=screen.getByRole('textbox');fireEvent.change(input,{target:{value:'Khác'}});fireEvent.keyDown(input,{key:'Escape'});
 expect(save).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'Video'})).toBeTruthy();
});
