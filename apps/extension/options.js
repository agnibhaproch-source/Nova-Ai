const input = document.getElementById("baseUrl");
const status = document.getElementById("status");

chrome.storage.sync.get({ baseUrl: "http://localhost:3000" }).then(({ baseUrl }) => {
  input.value = baseUrl;
});

chrome.commands.getAll().then((cmds) => {
  const c = cmds.find((x) => x.name === "toggle-quick-chat");
  if (c?.shortcut) document.getElementById("shortcut").textContent = c.shortcut;
});

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  let url;
  try {
    url = new URL(input.value.trim());
  } catch {
    status.textContent = "Enter a full address, like https://nova.example.com";
    return;
  }
  if (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
    status.textContent = "Use https (http is only allowed for localhost).";
    return;
  }
  await chrome.storage.sync.set({ baseUrl: url.origin });
  await chrome.storage.local.set({ windowId: null });
  status.textContent = "Saved";
});
