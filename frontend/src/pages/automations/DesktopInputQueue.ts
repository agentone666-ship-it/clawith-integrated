import type { Step } from "./contracts";

/** Unsaved operator input only; the server remains the recording authority. */
export class DesktopInputQueue {
  private pending: Step[] = [];
  private running = false;
  private idle: (() => void)[] = [];

  private execute: (step: Step) => Promise<boolean>;
  private changed: (busy: boolean) => void;
  private rejected: (message: string) => void;
  constructor(
    execute: (step: Step) => Promise<boolean>,
    changed: (busy: boolean) => void,
    rejected: (message: string) => void,
  ) {
    this.execute = execute;
    this.changed = changed;
    this.rejected = rejected;
  }

  enqueue(step: Step) {
    if (
      this.pending.reduce((n, item) => n + item.text.length, 0) +
        step.text.length >
      8000
    ) {
      this.rejected("待发送文字过多，请等待操作完成后继续。");
      return false;
    }
    const last = this.pending[this.pending.length - 1];
    if (
      step.action === "type_text" &&
      last?.action === "type_text" &&
      last.text.length + step.text.length <= 8000
    ) {
      last.text += step.text;
    } else {
      if (this.pending.length >= 64) {
        this.rejected("待发送操作过多，请等待画面更新后继续。");
        return false;
      }
      this.pending.push(step);
    }
    if (!this.running) void this.run();
    return true;
  }

  clear() {
    this.pending = [];
  }

  settled() {
    if (!this.running) return Promise.resolve();
    return new Promise<void>((resolve) => this.idle.push(resolve));
  }

  private async run() {
    this.running = true;
    this.changed(true);
    try {
      while (this.pending.length) {
        const step = this.pending.shift()!;
        // A failed or uncertain write is never retried or followed by queued input.
        if (!(await this.execute(step))) {
          this.clear();
          break;
        }
      }
    } catch {
      this.clear();
      this.rejected("输入发送中断，后续操作未发送，请核对画面后继续。");
    } finally {
      this.running = false;
      this.changed(false);
      for (const resolve of this.idle.splice(0)) resolve();
    }
  }
}
