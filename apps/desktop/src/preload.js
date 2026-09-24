// Exposes a minimal, origin-checked bridge to the Nova web app (window.novaDesktop).
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("novaDesktop", {
  platform: process.platform,
  captureScreen: () => ipcRenderer.invoke("nova:capture"),
  setOpacity: (v) => ipcRenderer.send("nova:set-opacity", Number(v)),
  getOpacity: () => ipcRenderer.invoke("nova:get-opacity"),
  shortcuts: () => ipcRenderer.invoke("nova:shortcuts"),
  hide: () => ipcRenderer.send("nova:hide"),
  minimize: () => ipcRenderer.send("nova:minimize"),
  onScreenshot: (cb) => {
    const handler = (_e, dataUrl) => cb(String(dataUrl));
    ipcRenderer.on("nova:screenshot", handler);
    return () => ipcRenderer.removeListener("nova:screenshot", handler);
  },
});
