import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { KeyboardEvent } from "react";
import { newStep } from "./contracts";
import type { Frame, Step } from "./contracts";

interface Props {
  frame: Frame;
  busy: boolean;
  blocked: boolean;
  resetToken: number;
  onInput: (step: Step) => void;
  onNotice: (text: string) => void;
}
const keys: Record<string, string> = {
  Enter: "return",
  Escape: "escape",
  Tab: "tab",
  Backspace: "backspace",
  Delete: "delete",
  ArrowDown: "down",
  ArrowUp: "up",
  ArrowLeft: "left",
  ArrowRight: "right",
  Home: "home",
  End: "end",
  PageUp: "pageup",
  PageDown: "pagedown",
  Insert: "insert",
  " ": "space",
};

export function DesktopSurface({
  frame,
  busy,
  blocked,
  resetToken,
  onInput,
  onNotice,
}: Props) {
  const keyboard = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const compositionEpoch = useRef(resetToken);
  const guestCopy = useRef(false);
  const text = useRef("");
  const textTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const click = useRef<{
    step: Step;
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  const [caret, setCaret] = useState({ x: 8, y: 8 });
  const flushText = useCallback(() => {
    clearTimeout(textTimer.current);
    if (text.current) onInput(newStep("type_text", { text: text.current }));
    text.current = "";
  }, [onInput]);
  const flushClick = useCallback(() => {
    if (!click.current) return;
    clearTimeout(click.current.timer);
    onInput(click.current.step);
    click.current = null;
  }, [onInput]);
  const type = (value: string, commit = false) => {
    if (blocked) return;
    flushClick();
    if (text.current.length + value.length > 8000) {
      onNotice("输入内容过长，请分段输入。");
      return;
    }
    text.current += value;
    clearTimeout(textTimer.current);
    if (commit) flushText();
    else textTimer.current = setTimeout(flushText, 80);
  };
  const send = useCallback(
    (step: Step) => {
      if (blocked) return;
      flushClick();
      flushText();
      onInput(step);
    },
    [flushClick, flushText, onInput, blocked],
  );
  useLayoutEffect(() => {
    clearTimeout(textTimer.current);
    if (click.current) clearTimeout(click.current.timer);
    click.current = null;
    text.current = "";
    composing.current = false;
    if (keyboard.current) keyboard.current.value = "";
  }, [resetToken]);
  useEffect(() => {
    const hostFocus = () => {
      guestCopy.current = false;
    };
    window.addEventListener("blur", hostFocus);
    const copied = (event: Event) => {
      if (event.target !== keyboard.current) guestCopy.current = false;
    };
    document.addEventListener("copy", copied);
    document.addEventListener("cut", copied);
    return () => {
      clearTimeout(textTimer.current);
      if (click.current) clearTimeout(click.current.timer);
      window.removeEventListener("blur", hostFocus);
      document.removeEventListener("copy", copied);
      document.removeEventListener("cut", copied);
    };
  }, []);
  useEffect(() => {
    const node = root.current;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      if (Math.abs(event.deltaY) + Math.abs(event.deltaX) < 1) return;
      keyboard.current?.focus({ preventScroll: true });
      const vertical = Math.abs(event.deltaY) >= Math.abs(event.deltaX);
      send(
        newStep("scroll", {
          direction: vertical
            ? event.deltaY > 0
              ? "down"
              : "up"
            : event.deltaX > 0
              ? "right"
              : "left",
          amount: 3,
        }),
      );
    };
    node?.addEventListener("wheel", wheel, { passive: false });
    return () => node?.removeEventListener("wheel", wheel);
  }, [send]);
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (blocked) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (
      composing.current ||
      event.nativeEvent.isComposing ||
      event.keyCode === 229
    )
      return;
    const key = event.key;
    if (event.getModifierState("AltGraph") && key.length === 1) return;
    if (
      [
        "Control",
        "Shift",
        "Alt",
        "Meta",
        "AltGraph",
        "Dead",
        "Process",
        "Unidentified",
      ].includes(key)
    )
      return;
    // Text and IME commits belong to the textarea input event, never keydown.
    if (!event.ctrlKey && !event.metaKey && !event.altKey && key.length === 1)
      return;
    const letter = key.toLowerCase();
    const shortcut = event.ctrlKey || event.metaKey;
    if (shortcut && !event.altKey && letter === "v" && !guestCopy.current)
      return;
    event.preventDefault();
    event.stopPropagation();
    const modifiers: Step["modifiers"] = [];
    if (event.ctrlKey) modifiers.push("ctrl");
    if (event.metaKey)
      modifiers.push("acvxzys".includes(letter) ? "ctrl" : "win");
    if (event.altKey) modifiers.push("alt");
    if (event.shiftKey) modifiers.push("shift");
    if (shortcut && ["c", "x"].includes(letter)) guestCopy.current = true;
    if (
      !keys[key] &&
      !/^[a-z0-9]$/i.test(key) &&
      !/^F([1-9]|1[0-2])$/.test(key)
    ) {
      onNotice("这个快捷键暂不支持，请使用云电脑内的菜单操作。");
      return;
    }
    send(
      newStep(modifiers.length ? "hotkey" : "press_key", {
        key: keys[key] || letter,
        modifiers: [...new Set(modifiers)],
      }),
    );
  };
  const point = (event: {
    clientX: number;
    clientY: number;
    currentTarget: HTMLImageElement;
  }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(
        frame.width - 1,
        Math.max(
          0,
          Math.floor(((event.clientX - rect.left) * frame.width) / rect.width),
        ),
      ),
      y: Math.min(
        frame.height - 1,
        Math.max(
          0,
          Math.floor(((event.clientY - rect.top) * frame.height) / rect.height),
        ),
      ),
    };
  };
  return (
    <div
      ref={root}
      className={"auto-desktop auto-direct-desktop " + (busy ? "busy" : "")}
      role="application"
      aria-label="独立 Windows 桌面"
    >
      <img
        alt="Windows 桌面实时画面"
        draggable={false}
        src={`data:${frame.mime};base64,${frame.image}`}
        onPointerDown={(event) => {
          const rect = root.current!.getBoundingClientRect();
          setCaret({
            x: Math.max(
              0,
              Math.min(rect.width - 24, event.clientX - rect.left),
            ),
            y: Math.max(
              0,
              Math.min(rect.height - 24, event.clientY - rect.top),
            ),
          });
          keyboard.current?.focus({ preventScroll: true });
          event.preventDefault();
        }}
        onClick={(event) => {
          if (blocked || event.detail > 1) return;
          flushClick();
          flushText();
          const step = newStep("click", point(event));
          click.current = { step, timer: setTimeout(flushClick, 250) };
        }}
        onDoubleClick={(event) => {
          if (blocked) return;
          const pending = click.current;
          if (pending) {
            clearTimeout(pending.timer);
            click.current = null;
          }
          flushText();
          onInput(newStep(pending ? "double_click" : "click", point(event)));
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          keyboard.current?.focus({ preventScroll: true });
          send(newStep("right_click", point(event)));
        }}
      />
      <textarea
        ref={keyboard}
        className="auto-desktop-keyboard"
        aria-label="云电脑键盘输入"
        style={{ left: caret.x, top: caret.y }}
        autoCapitalize="off"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        onKeyDown={handleKeyDown}
        onCompositionStart={() => {
          flushClick();
          flushText();
          composing.current = !blocked;
          compositionEpoch.current = resetToken;
        }}
        onCompositionEnd={(event) => {
          composing.current = false;
          const value = event.data || event.currentTarget.value;
          event.currentTarget.value = "";
          if (value && !blocked && compositionEpoch.current === resetToken)
            type(value, true);
        }}
        onInput={(event) => {
          if (blocked) {
            event.currentTarget.value = "";
            return;
          }
          if (
            composing.current ||
            (event.nativeEvent as InputEvent).isComposing
          )
            return;
          const value = event.currentTarget.value;
          event.currentTarget.value = "";
          if (value) type(value);
        }}
        onPaste={(event) => {
          event.preventDefault();
          const value = event.clipboardData.getData("text");
          if (value) type(value, true);
        }}
        onBlur={() => {
          flushClick();
          flushText();
        }}
      />
    </div>
  );
}
