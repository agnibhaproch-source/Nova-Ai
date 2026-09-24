"use client";

import { useQuickChat } from "./store";

const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

function dataUrlToFile(dataUrl: string, name: string): File {
  const [head, b64] = dataUrl.split(",");
  const mime = /data:(.*?);/.exec(head ?? "")?.[1] ?? "image/png";
  const bin = atob(b64 ?? "");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new File([bytes], name, { type: mime });
}

export function screenshotName() {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `screenshot-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.png`;
}

export function fileFromDataUrl(dataUrl: string) {
  return dataUrlToFile(dataUrl, screenshotName());
}

/**
 * Takes a screenshot of the whole screen, without the Quick Chat window in it.
 * - Desktop app: native capture; the Nova window is excluded from captures by the OS.
 * - Browser: Screen Capture API (the browser asks which screen to share); the in-page
 *   Quick Chat is hidden for the frame that's grabbed.
 */
export async function captureScreen(): Promise<File> {
  if (window.novaDesktop) return fileFromDataUrl(await window.novaDesktop.captureScreen());
  if (!navigator.mediaDevices?.getDisplayMedia) throw new Error("Screen capture isn't supported in this browser.");
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: "monitor", frameRate: 5 },
    audio: false,
    // Chrome-only hints (ignored elsewhere): prefer whole screens.
    ...({ monitorTypeSurfaces: "include", selfBrowserSurface: "include", surfaceSwitching: "exclude" } as object),
  });
  const { setCapturing } = useQuickChat.getState();
  try {
    setCapturing(true); // hide our window so it isn't in the shot
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await nextFrame();
    await new Promise((r) => setTimeout(r, 250)); // let the hidden window leave the captured frame
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (!blob) throw new Error("Couldn't capture the screen.");
    return new File([blob], screenshotName(), { type: "image/png" });
  } finally {
    stream.getTracks().forEach((t) => t.stop());
    setCapturing(false);
  }
}

/** "\\": screenshot → Quick Chat composer, without opening the window (docs/27 §17a). */
export async function queueScreenshot(): Promise<void> {
  const { toast } = await import("sonner");
  try {
    const file = await captureScreen();
    const st = useQuickChat.getState();
    st.addShot(file);
    const n = useQuickChat.getState().shots.length;
    if (!st.open)
      toast.success(`Screenshot added to Quick Chat${n > 1 ? ` (${n} waiting)` : ""}`, {
        action: { label: "Open", onClick: () => useQuickChat.getState().setOpen(true) },
      });
  } catch (err) {
    if (err instanceof DOMException && err.name === "NotAllowedError") return; // user cancelled
    toast.error(err instanceof Error ? err.message : "Couldn't take a screenshot.");
  }
}
