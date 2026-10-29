import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
interface Props {
  image: string;
  caption: string;
  steps: ReactNode;
  onClose: () => void;
  onFollow: () => void;
}
export function DesktopViewer({
  image,
  caption,
  steps,
  onClose,
  onFollow,
}: Props) {
  const [actualSize, setActualSize] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Tab" && panel.current) {
        const items = Array.from(
          panel.current.querySelectorAll<HTMLElement>(
            'button:not(:disabled),[tabindex="0"]',
          ),
        );
        const first = items[0],
          last = items[items.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === panel.current)
        ) {
          e.preventDefault();
          last?.focus();
        } else if (
          !e.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === panel.current)
        ) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [onClose]);
  return createPortal(
    <div className="auto-viewer-backdrop" onClick={onClose}>
      <section
        ref={panel}
        tabIndex={-1}
        className="auto-viewer"
        role="dialog"
        aria-modal="true"
        aria-label="桌面操作画面"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <strong>桌面操作画面</strong>
          <span>{caption}</span>
          <div className="auto-viewer-actions">
            <button
              className="btn btn-secondary"
              aria-pressed={!actualSize}
              onClick={() => setActualSize(false)}
            >
              适应窗口
            </button>
            <button
              className="btn btn-secondary"
              aria-pressed={actualSize}
              onClick={() => setActualSize(true)}
            >
              原始大小
            </button>
            <button className="btn btn-secondary" onClick={onFollow}>
              跟随最新
            </button>
            <button className="btn btn-secondary" onClick={onClose}>
              关闭
            </button>
          </div>
        </header>
        <div
          className={"auto-viewer-stage" + (actualSize ? " actual-size" : "")}
          tabIndex={0}
          aria-label="桌面画面查看区"
        >
          <img src={image} alt={caption} />
        </div>
        <footer>
          {steps}
          <small>可切换步骤核对操作路径；原始大小支持滚动查看细节。</small>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
