import { useRef,useState } from "react";
export function EditableTitle({value,disabled,onSave}:{value:string;disabled:boolean;onSave:(value:string)=>Promise<void>}) {
 const [editing,setEditing]=useState(false),[draft,setDraft]=useState(value);const committing=useRef(false);
 const finish=async()=>{if(committing.current)return;const name=draft.trim();if(!name){setDraft(value);setEditing(false);return}committing.current=true;setEditing(false);try{if(name!==value)await onSave(name)}finally{committing.current=false}};
 return editing?<input className="editable-title" aria-label="Tên video và tên file xuất" autoFocus value={draft} maxLength={200} onChange={e=>setDraft(e.target.value)} onBlur={()=>void finish()} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();void finish()}if(e.key==="Escape"){committing.current=true;setEditing(false);setDraft(value);queueMicrotask(()=>committing.current=false)}}}/>:<button disabled={disabled} className="title-edit-button" title="Bấm để đổi tên video và tên file xuất" onClick={()=>{setDraft(value);setEditing(true)}}><h1>{value}</h1></button>;
}
