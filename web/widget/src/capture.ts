/**
 * "Capture this page": ask the browser to share this tab (or a window or screen), take one frame and let go.
 * Nothing leaves the browser here. The frame goes to the redact editor, and only what the visitor approves is sent.
 */

export type CaptureResult = { ok: true; frame: HTMLCanvasElement } | { ok: false; reason: "cancelled" | "failed" };

export interface CaptureHooks {
  /** Called once the stream is running and just before the frame is taken: hide the widget so it is not in the picture. */
  beforeGrab(): void;
  /** Called when the frame is taken (or the attempt failed): show the widget again. */
  afterGrab(): void;
}

/** True where the browser can share a screen (desktops, on secure pages); phones mostly cannot. */
export function canCapture(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getDisplayMedia === "function";
}

/** Wait until the stream has shown a frame without the widget. Never waits more than a second. */
function settle(video: HTMLVideoElement): Promise<void> {
  return new Promise((resolve) => {
    const giveUp = setTimeout(resolve, 1000);
    const done = () => {
      clearTimeout(giveUp);
      setTimeout(resolve, 50);
    };
    if ("requestVideoFrameCallback" in video) {
      // Two frames: the first may have been queued before the widget disappeared.
      video.requestVideoFrameCallback(() => video.requestVideoFrameCallback(done));
    } else {
      setTimeout(done, 300);
    }
  });
}

export async function captureFrame(hooks: CaptureHooks): Promise<CaptureResult> {
  let stream: MediaStream;
  try {
    // Without limits Chrome hands back a stream scaled down to about 800 pixels wide, and the screenshot comes out
    // small and soft. A `max` the size of this screen (never above 4K) keeps it sharp, and Chrome treats it as a
    // ceiling for what is shared. `preferCurrentTab` is Chrome's hint to offer "this tab" first; others ignore it.
    const scale = window.devicePixelRatio || 1;
    const ceiling = (screenSide: number | undefined, windowSide: number, limit: number) =>
      Math.min(limit, Math.round(Math.max(screenSide || 0, windowSide || 0, 800) * scale));
    const options = {
      video: {
        width: { max: ceiling(window.screen?.width, window.innerWidth, 3840) },
        height: { max: ceiling(window.screen?.height, window.innerHeight, 2160) },
        frameRate: { max: 5 },
      },
      audio: false,
      preferCurrentTab: true,
    } as DisplayMediaStreamOptions;
    stream = await navigator.mediaDevices.getDisplayMedia(options);
  } catch (err) {
    const name = (err as { name?: string })?.name;
    return { ok: false, reason: name === "NotAllowedError" || name === "AbortError" ? "cancelled" : "failed" };
  }
  try {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    hooks.beforeGrab();
    await settle(video);
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) return { ok: false, reason: "failed" };
    const frame = document.createElement("canvas");
    frame.width = width;
    frame.height = height;
    const ctx = frame.getContext("2d");
    if (!ctx) return { ok: false, reason: "failed" };
    ctx.drawImage(video, 0, 0, width, height);
    return { ok: true, frame };
  } catch {
    return { ok: false, reason: "failed" };
  } finally {
    for (const track of stream.getTracks()) track.stop(); // the browser's "sharing" indicator goes away at once
    hooks.afterGrab();
  }
}
