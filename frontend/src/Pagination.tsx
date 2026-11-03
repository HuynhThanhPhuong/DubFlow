import { useEffect, useLayoutEffect, useState } from "react";
import { Button } from "./ui";
import type { RefObject } from "react";
export interface PageRange {
  start: number;
  end: number;
}
interface CapacityOptions {
  measureRef: RefObject<HTMLElement | null>;
  count: number;
  revision: string;
}
export function packCapacity(heights: number[], height: number): PageRange[] {
  const pages: PageRange[] = [];
  let start = 0,
    used = 0;
  heights.forEach((h, i) => {
    if (i > start && used + h > height + 0.5) {
      pages.push({ start, end: i });
      start = i;
      used = 0;
    }
    used += h;
  });
  if (heights.length) pages.push({ start, end: heights.length });
  return pages.length ? pages : [{ start: 0, end: 0 }];
}
export function useCapacity(
  ref: RefObject<HTMLElement | null>,
  options: CapacityOptions,
): PageRange[];
export function useCapacity(
  ref: RefObject<HTMLElement | null>,
  rowHeight?: number,
  fallback?: number,
): number;
export function useCapacity(
  ref: RefObject<HTMLElement | null>,
  rowHeight: number | CapacityOptions = 110,
  fallback = 3,
): number | PageRange[] {
  const options = typeof rowHeight === "number" ? null : rowHeight;
  const [size, setSize] = useState(fallback);
  const [pages, setPages] = useState<PageRange[]>([
    { start: 0, end: options?.count ?? 0 },
  ]);
  useLayoutEffect(() => {
    if (!options) return;
    const el = ref.current,
      probe = options.measureRef.current;
    if (!el || !probe || typeof ResizeObserver === "undefined") {
      const ranges = packCapacity(Array(options.count).fill(1), 8);
      setPages(ranges);
      return;
    }
    let frame = 0;
    const measure = () => {
      probe.style.width = el.clientWidth + "px";
      const heights = Array.from(probe.children).map(
        (row) => row.getBoundingClientRect().height,
      );
      if (!el.clientHeight || heights.some((h) => !h)) return;
      const next = packCapacity(heights, el.clientHeight);
      setPages((old) =>
        JSON.stringify(old) === JSON.stringify(next) ? old : next,
      );
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(el);
    observer.observe(probe);
    measure();
    window.addEventListener("resize", schedule);
    document.addEventListener("fullscreenchange", schedule);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("fullscreenchange", schedule);
    };
  }, [ref, options?.measureRef, options?.count, options?.revision]);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    if (typeof rowHeight !== "number") return;
    const measure = () =>
      setSize(Math.max(1, Math.floor(el.clientHeight / rowHeight)));
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    // Khi vao/thoat toan man hinh, kich thuoc do duoc luc dang toan man hinh co the sai; do lai sau khi layout on dinh.
    let frame = 0;
    const remeasure = () => {
      measure();
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    document.addEventListener("fullscreenchange", remeasure);
    window.addEventListener("resize", remeasure);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      document.removeEventListener("fullscreenchange", remeasure);
      window.removeEventListener("resize", remeasure);
    };
  }, [ref, rowHeight]);
  return options ? pages : size;
}
export function Pagination({
  total,
  page,
  size,
  onChange,
  ranges,
}: {
  total: number;
  page: number;
  size: number;
  onChange: (page: number) => void;
  ranges?: PageRange[];
}) {
  const pages = ranges?.length ?? Math.max(1, Math.ceil(total / size));
  const current = Math.min(Math.max(0, page), pages - 1);
  const [draft, setDraft] = useState(String(current + 1));
  useEffect(() => setDraft(String(current + 1)), [current]);
  const commit = () => {
    const n = Number(draft.trim());
    if (!draft.trim() || !Number.isInteger(n)) {
      setDraft(String(current + 1));
      return;
    }
    const next = Math.min(pages, Math.max(1, n));
    setDraft(String(next));
    if (next - 1 !== current) onChange(next - 1);
  };
  return (
    <nav className="studio-pagination" aria-label="Phân trang">
      <span>
        {total
          ? `${(ranges?.[current].start ?? current * size) + 1}–${ranges?.[current].end ?? Math.min((current + 1) * size, total)}`
          : "0"}{" "}
        / {total}
      </span>
      <div className="page-controls">
        <Button disabled={current === 0} onClick={() => onChange(current - 1)}>
          ‹ Trước
        </Button>
        <span className="page-jump">
          <input
            type="text"
            inputMode="numeric"
            aria-label="Trang"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commit();
              }
            }}
          />{" "}
          / {pages}
        </span>
        <Button
          disabled={current + 1 >= pages}
          onClick={() => onChange(current + 1)}
        >
          Sau ›
        </Button>
      </div>
    </nav>
  );
}
