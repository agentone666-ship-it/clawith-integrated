import {
  useEffect,
  useRef,
  type Dispatch,
  type SetStateAction,
  type RefObject,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

export interface ComposerHandoff {
  agentId: string;
  text: string;
  createdAt: number;
}
export function validComposerHandoff(
  value: unknown,
  agentId: string | undefined,
  now: number,
): value is ComposerHandoff {
  if (!agentId || !value || typeof value !== "object") return false;
  const v = value as Partial<ComposerHandoff>;
  return (
    v.agentId === agentId &&
    typeof v.text === "string" &&
    v.text.trim().length > 0 &&
    new TextEncoder().encode(v.text).length <= 24576 &&
    typeof v.createdAt === "number" &&
    v.createdAt <= now &&
    now - v.createdAt <= 300000
  );
}

// Route state carries a draft only: no credentials, persistence or auto-send.
export function useComposerHandoff(
  agentId: string | undefined,
  setInput: Dispatch<SetStateAction<string>>,
  inputRef: RefObject<HTMLTextAreaElement | null>,
) {
  const location = useLocation();
  const navigate = useNavigate();
  const consumed = useRef<string | null>(null);
  useEffect(() => {
    const state = location.state as { composerHandoff?: unknown } | null;
    if (!state?.composerHandoff || consumed.current === location.key) return;
    consumed.current = location.key;
    if (validComposerHandoff(state.composerHandoff, agentId, Date.now())) {
      const text = state.composerHandoff.text;
      setInput((previous) =>
        previous.trim() ? `${previous}\n\n${text}` : text,
      );
    }
    requestAnimationFrame(() => {
      const input = inputRef.current;
      if (input) {
        input.focus({ preventScroll: true });
        input.setSelectionRange(input.value.length, input.value.length);
      }
    });
    const remaining = { ...state };
    delete remaining.composerHandoff;
    void navigate(location.pathname + location.search + location.hash, {
      replace: true,
      state: remaining,
    });
  }, [agentId, location, navigate, setInput, inputRef]);
}
