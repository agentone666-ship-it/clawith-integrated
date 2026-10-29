import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type RefObject,
} from "react";

// Measure after DOM mount and layout, including drafts populated before data loads.
export function useAutoGrowComposer(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
) {
  const observer = useRef<ResizeObserver | null>(null);
  const frame = useRef<number | null>(null);
  const measure = useCallback(() => {
    const el = ref.current;
    if (!el || !el.getBoundingClientRect().width) return;
    const style = getComputedStyle(el);
    const border =
      parseFloat(style.borderTopWidth || "0") +
      parseFloat(style.borderBottomWidth || "0");
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight + border}px`;
    el.style.overflowY =
      el.scrollHeight > el.clientHeight + 1 ? "auto" : "hidden";
  }, [ref]);
  const schedule = useCallback(() => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      measure();
    });
  }, [measure]);
  const bindInput = useCallback(
    (el: HTMLTextAreaElement | null) => {
      observer.current?.disconnect();
      ref.current = el;
      if (!el) return;
      measure();
      schedule();
      let width = el.getBoundingClientRect().width;
      observer.current = new ResizeObserver(() => {
        const next = el.getBoundingClientRect().width;
        if (next !== width) {
          width = next;
          schedule();
        }
      });
      observer.current.observe(el);
    },
    [ref, measure, schedule],
  );
  useLayoutEffect(() => {
    measure();
  }, [value, measure]);
  useEffect(() => {
    if (ref.current) observer.current?.observe(ref.current);
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("resize", schedule);
      observer.current?.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [ref, schedule]);
  return bindInput;
}
