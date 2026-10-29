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
  document?: { name: string; text: string };
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
    new TextEncoder().encode(JSON.stringify(v)).length <= 24576 &&
    v.agentId === agentId &&
    (!v.document ||
      (v.document.name === "AUTOMATION_AGENT.md" &&
        typeof v.document.text === "string" &&
        new TextEncoder().encode(v.document.text).length <= 16384)) &&
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
  setDocuments: Dispatch<SetStateAction<{ name: string; text: string }[]>>,
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
      const document = state.composerHandoff.document;
      if (document)
        setDocuments((previous) => [
          ...previous.filter((d) => d.name !== document.name),
          document,
        ]);
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
  }, [agentId, location, navigate, setInput, inputRef, setDocuments]);
}
