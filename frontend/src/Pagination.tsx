import { useEffect, useState } from "react";
import type { RefObject } from "react";
export function useCapacity(ref:RefObject<HTMLElement|null>, rowHeight=110, fallback=3) {
 const [size,setSize]=useState(fallback);
 useEffect(()=>{const el=ref.current;if(!el||typeof ResizeObserver==="undefined")return;
 const measure=()=>setSize(Math.max(1,Math.floor(el.clientHeight/rowHeight)));
 const observer=new ResizeObserver(measure);observer.observe(el);measure();return()=>observer.disconnect();
 },[ref,rowHeight]);return size;
}
export function Pagination({total,page,size,onChange}:{total:number;page:number;size:number;onChange:(page:number)=>void}) {
 const pages=Math.max(1,Math.ceil(total/size));
 return <nav className="studio-pagination" aria-label="Phân trang"><span>{total?`${page*size+1}–${Math.min((page+1)*size,total)}`:"0"} / {total}</span><button disabled={page===0} onClick={()=>onChange(page-1)}>Trước</button><b>{page+1} / {pages}</b><button disabled={page+1>=pages} onClick={()=>onChange(page+1)}>Sau</button></nav>;
}
