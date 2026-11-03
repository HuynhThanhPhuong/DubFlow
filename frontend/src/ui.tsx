import * as Dialog from "@radix-ui/react-dialog";
import { Slot } from "@radix-ui/react-slot";
import { useEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
export function Toast({message, kind, onClose, durationMs}: {message:string; kind:"success"|"error"; onClose:()=>void; durationMs?:number}) {
  const duration = durationMs ?? (kind === "error" ? 5000 : 3000);
  const close = useRef(onClose);
  const dismiss = useRef<() => void>(() => {});
  const [remaining, setRemaining] = useState(duration);
  const [closing, setClosing] = useState(false);
  close.current = onClose;
  useEffect(() => {
    let ended=false;
    let exitTimer: ReturnType<typeof setTimeout> | undefined;
    const deadline=Date.now()+duration;
    setRemaining(duration); setClosing(false);
    const ticker=window.setInterval(() => setRemaining(Math.max(0,deadline-Date.now())),250);
    const finish=() => {
      if(ended) return;
      ended=true;
      window.clearInterval(ticker); window.clearTimeout(timer);
      setClosing(true);
      exitTimer=window.setTimeout(() => close.current(),240);
    };
    const timer=window.setTimeout(finish,duration);
    dismiss.current=finish;
    return () => { window.clearInterval(ticker); window.clearTimeout(timer); window.clearTimeout(exitTimer); };
  }, [message, duration]);
  return <div className={`toast ${kind}${closing ? " toast-closing" : ""}`} role={kind === "error" ? "alert" : "status"}>
    <div className="toast-copy"><span>{message}</span></div>
    <button type="button" className="toast-close" aria-label="Đóng thông báo" onClick={() => dismiss.current()}>Đóng</button>
    <div className="toast-countdown" aria-hidden="true"><i style={{width:`${remaining/duration*100}%`}}/></div>
  </div>;
}
export function Button({
  variant = "secondary",
  asChild = false,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "save";
  asChild?: boolean;
}) {
  const Component = asChild ? Slot : "button";
  return <Component className={`button ${variant} ${className}`} {...props} />;
}
export function Modal({
  title,
  description,
  children,
  onClose,
  className = "",
}: {
  className?: string;
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={`dialog-content ${className}`.trim()}
          aria-describedby={description ? "dialog-description" : undefined}
        >
          <div className="dialog-head">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" aria-label="Đóng hộp thoại">
                Đóng
              </Button>
            </Dialog.Close>
          </div>
          {description && (
            <Dialog.Description id="dialog-description">
              {description}
            </Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
