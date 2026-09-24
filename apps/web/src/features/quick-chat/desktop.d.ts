/** Bridge exposed by the Nova desktop app's preload script (apps/desktop). Absent in browsers. */
interface NovaDesktop {
  platform: string;
  /** PNG data URL of the whole screen; the Nova window is excluded from the capture. */
  captureScreen: () => Promise<string>;
  setOpacity: (value: number) => void;
  getOpacity: () => Promise<number>;
  shortcuts: () => Promise<{ toggle: string; screenshot: string; kill: string }>;
  /** Screenshots taken by the global shortcut while the window was hidden. */
  onScreenshot: (cb: (dataUrl: string) => void) => () => void;
  hide: () => void;
  minimize: () => void;
}

interface Window {
  novaDesktop?: NovaDesktop;
}
