import {
  useEffect,
  useRef,
  useState,
  type RefObject,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { IconArrowsMaximize } from "@tabler/icons-react";
import { useAutoGrowComposer } from "./hooks/useAutoGrowComposer";
import "./composer-input.css";

interface Props extends Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  "value"
> {
  value: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
}

export function ComposerInput({ inputRef, value, ...props }: Props) {
  const bindInput = useAutoGrowComposer(inputRef, value);
  const [expanded, setExpanded] = useState(false);
  const editor = useRef<HTMLTextAreaElement>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!expanded) return;
    const source = inputRef.current;
    const target = editor.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    target?.focus();
    target?.setSelectionRange(
      source?.selectionStart || 0,
      source?.selectionEnd || 0,
    );
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setExpanded(false);
      }
      if (event.key === "Tab" && panel.current) {
        const controls = Array.from(
          panel.current.querySelectorAll<HTMLElement>("button, textarea"),
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keyboard);
      source?.focus({ preventScroll: true });
      source?.setSelectionRange(
        target?.selectionStart || 0,
        target?.selectionEnd || 0,
      );
    };
  }, [expanded, inputRef]);
  return (
    <>
      <div className="chat-composer-text">
        <textarea {...props} ref={bindInput} value={value} />
        <button
          type="button"
          className="chat-composer-expand"
          aria-label="放大编辑"
          title="放大编辑"
          disabled={props.disabled}
          onClick={() => setExpanded(true)}
        >
          <IconArrowsMaximize size={16} />
        </button>
      </div>
      {expanded &&
        createPortal(
          <div className="chat-editor-backdrop">
            <section
              ref={panel}
              className="chat-editor-dialog"
              role="dialog"
              aria-modal="true"
              aria-label="编辑消息"
            >
              <header>
                <strong>编辑消息</strong>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => setExpanded(false)}
                >
                  完成
                </button>
              </header>
              <textarea
                ref={editor}
                className="chat-editor-input"
                aria-label="消息内容"
                value={value}
                onChange={props.onChange}
                onPaste={props.onPaste}
                disabled={props.disabled}
                placeholder={props.placeholder}
              />
              <small>
                Enter 换行，Esc 返回聊天。内容自动保留，完成后可在聊天中发送。
              </small>
            </section>
          </div>,
          document.body,
        )}
    </>
  );
}
