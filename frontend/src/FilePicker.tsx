import { useRef, useState } from "react";
import type { InputHTMLAttributes } from "react";
import { Button } from "./ui";
export function FilePicker({onChange,disabled,...props}:Omit<InputHTMLAttributes<HTMLInputElement>,"type">) {
  const input=useRef<HTMLInputElement>(null);
  const [name,setName]=useState("");
  return <div className="file-picker"><input {...props} ref={input} type="file" hidden disabled={disabled} onChange={e=>{setName(Array.from(e.target.files||[]).map(f=>f.name).join(", "));onChange?.(e)}}/>
    <Button type="button" disabled={disabled} onClick={()=>input.current?.click()}>Chọn file</Button><span title={name}>{name||"Chưa chọn file"}</span>
  </div>;
}
