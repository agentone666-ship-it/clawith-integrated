import { useEffect, useRef, useState } from "react";

export function useRecordingFullscreen() {
  const panel = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const leave = async () => {
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
  };
  return { panelRef: panel, expanded, toggle, leave };
}
