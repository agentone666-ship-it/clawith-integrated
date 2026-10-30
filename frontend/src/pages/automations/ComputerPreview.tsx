import { useCallback, useEffect, useState } from "react";
import { automationApi } from "./api";
import { DesktopViewer } from "./DesktopViewer";
export function ComputerPreview({
  runId,
  active,
}: {
  runId: string;
  active: boolean;
}) {
  const [frame, setFrame] = useState<{
    image: string;
    mime: string;
    captured_at: string;
  } | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const closeViewer = useCallback(() => setOpen(false), []);
  const refresh = async () => {
    try {
      setFrame(await automationApi.computerFrame(runId));
      setError("");
    } catch {
      setError("画面暂未更新，请核对截图时间");
    }
  };
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await automationApi.computerFrame(runId);
        if (!stopped) {
          setFrame(value);
          setError("");
        }
      } catch {
        if (!stopped) setError("画面暂未更新，请核对截图时间");
      }
      if (!stopped && active) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId, active]);
  const image = frame ? `data:${frame.mime};base64,${frame.image}` : "";
  const caption = `Computer Use · ${active ? "执行中" : "最后画面"} · ${frame ? new Date(frame.captured_at).toLocaleTimeString() : "等待画面"}`;
  return (
    <div className="auto-playback">
      <p>{caption}</p>
      {error && <p role="alert">{error}</p>}
      {image && (
        <>
          <button className="btn btn-secondary" onClick={() => setOpen(true)}>
            放大画面
          </button>
          <img
            alt="Computer Use 云电脑画面"
            src={image}
            style={{
              width: "100%",
              height: "auto",
              maxHeight: "65vh",
              objectFit: "contain",
            }}
            onClick={() => setOpen(true)}
          />
        </>
      )}
      {open && image && (
        <DesktopViewer
          image={image}
          caption={caption}
          steps={
            <p>
              {active
                ? "Agent 正在直接操作云电脑。"
                : "任务已结束，保留最后画面。"}
              画面按截图时间更新。
            </p>
          }
          onClose={closeViewer}
          onFollow={() => void refresh()}
        />
      )}
    </div>
  );
}
