const url = document.getElementById("url");
const status = document.getElementById("status");
window.novaSettings.get().then((c) => (url.value = c.baseUrl));
window.novaSettings.shortcuts().then((s) => {
  document.getElementById("t").textContent = s.toggle;
  document.getElementById("s").textContent = s.screenshot;
});
document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await window.novaSettings.setBaseUrl(url.value.trim());
    status.textContent = "Saved";
  } catch (err) {
    status.textContent = String(err.message || err).replace(/^Error invoking remote method '[^']+': (Error: )?/, "");
  }
});
