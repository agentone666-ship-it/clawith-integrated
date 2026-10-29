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
    const area = el.closest<HTMLElement>(".chat-input-area");
    const panel = area?.parentElement;
    if (area && panel) {
      const viewport = window.visualViewport;
      const bottom = viewport
        ? viewport.offsetTop + viewport.height
        : window.innerHeight;
      const bounds = panel.getBoundingClientRect();
      const room =
        Math.min(bounds.bottom, bottom) -
        Math.max(bounds.top, viewport?.offsetTop || 0);
      const chrome = area.offsetHeight - el.offsetHeight;
      const history = Math.min(96, room * 0.15);
      el.style.setProperty(
        "--chat-composer-room",
        `${Math.max(50, room - chrome - history)}px`,
      );
    }
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
      observer.current = new ResizeObserver(schedule);
      observer.current.observe(el);
      const area = el.closest<HTMLElement>(".chat-input-area");
      if (area) {
        observer.current.observe(area);
        if (area.parentElement) observer.current.observe(area.parentElement);
      }
    },
    [ref, measure, schedule],
  );
  useLayoutEffect(() => {
    measure();
  }, [value, measure]);
  useEffect(() => {
    const el = ref.current;
    if (el && observer.current) {
      observer.current.observe(el);
      const area = el.closest<HTMLElement>(".chat-input-area");
      if (area) {
        observer.current.observe(area);
        if (area.parentElement) observer.current.observe(area.parentElement);
      }
    }
    window.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("resize", schedule);
    document.fonts?.addEventListener("loadingdone", schedule);
    return () => {
      window.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("resize", schedule);
      document.fonts?.removeEventListener("loadingdone", schedule);
      observer.current?.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [ref, schedule]);
  return bindInput;
}
