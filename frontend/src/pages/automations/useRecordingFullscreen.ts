import { useEffect, useRef, useState } from "react";

export function useRecordingFullscreen() {
  const panel = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const sync = () =>
      setExpanded(document.fullscreenElement === panel.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);
  const leave = async () => {
    if (document.fullscreenElement === panel.current) {
      await document.exitFullscreen();
    }
    setExpanded(false);
  };
  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [expanded]);
  const toggle = async () => {
    if (expanded) {
      await leave();
      return;
    }
    setExpanded(true);
    try {
      await panel.current?.requestFullscreen?.();
    } catch {
      // Keep an in-page maximized view when browser fullscreen is unavailable.
    }
  };
  return { panelRef: panel, expanded, toggle, leave };
}
