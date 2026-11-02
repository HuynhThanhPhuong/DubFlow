import { useEffect, useState } from "react";
import { Button } from "./ui";
import type { RefObject } from "react";
export function useCapacity(ref:RefObject<HTMLElement|null>, rowHeight=110, fallback=3) {
 const [size,setSize]=useState(fallback);
 useEffect(()=>{const el=ref.current;if(!el||typeof ResizeObserver==="undefined")return;
 const measure=()=>setSize(Math.max(1,Math.floor(el.clientHeight/rowHeight)));
 const observer=new ResizeObserver(measure);observer.observe(el);measure();
 // Khi vao/thoat toan man hinh, kich thuoc do duoc luc dang toan man hinh co the sai; do lai sau khi layout on dinh.
 let frame=0;
 const remeasure=()=>{measure();cancelAnimationFrame(frame);frame=requestAnimationFrame(measure);};
 document.addEventListener("fullscreenchange",remeasure);window.addEventListener("resize",remeasure);
 return()=>{observer.disconnect();cancelAnimationFrame(frame);document.removeEventListener("fullscreenchange",remeasure);window.removeEventListener("resize",remeasure);};
 },[ref,rowHeight]);return size;
}
export function Pagination({total,page,size,onChange}:{total:number;page:number;size:number;onChange:(page:number)=>void}) {
 const pages=Math.max(1,Math.ceil(total/size));
 const current=Math.min(Math.max(0,page),pages-1);
 const [draft,setDraft]=useState(String(current+1));
 useEffect(()=>setDraft(String(current+1)),[current]);
 const commit=()=>{
  const n=Number(draft.trim());
  if(!draft.trim()||!Number.isInteger(n)){setDraft(String(current+1));return;}
  const next=Math.min(pages,Math.max(1,n));
  setDraft(String(next));
  if(next-1!==current)onChange(next-1);
 };
 return <nav className="studio-pagination" aria-label="Phân trang"><span>{total?`${current*size+1}–${Math.min((current+1)*size,total)}`:"0"} / {total}</span>
  <div className="page-controls"><Button disabled={current===0} onClick={()=>onChange(current-1)}>‹ Trước</Button>
  <span className="page-jump"><input type="text" inputMode="numeric" aria-label="Trang" value={draft} onChange={e=>setDraft(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();commit();}}}/> / {pages}</span>
  <Button disabled={current+1>=pages} onClick={()=>onChange(current+1)}>Sau ›</Button></div></nav>;
}
