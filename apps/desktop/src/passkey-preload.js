const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("novaPasskey", {
  submit: (value) => ipcRenderer.invoke("nova:passkey", String(value)),
  cancel: () => ipcRenderer.send("nova:passkey-cancel"),
});
