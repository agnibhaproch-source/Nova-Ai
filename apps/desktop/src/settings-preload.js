const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("novaSettings", {
  get: () => ipcRenderer.invoke("nova:get-config"),
  setBaseUrl: (url) => ipcRenderer.invoke("nova:set-base-url", url),
  shortcuts: () => ipcRenderer.invoke("nova:shortcuts"),
});
