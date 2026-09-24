const form = document.getElementById("f");
const key = document.getElementById("key");
const status = document.getElementById("status");
const buttons = document.querySelectorAll("button");

if (new URLSearchParams(location.search).has("locked")) {
  document.title = "Nova is locked";
  document.querySelector("h1").textContent = "Nova is locked on this device";
  document.querySelector("p").textContent = "The wrong passkey was entered 3 times, so Nova can no longer be opened here.";
  key.remove();
  document.getElementById("unlock").remove();
  document.getElementById("quit").textContent = "Close";
}

document.getElementById("quit").addEventListener("click", () => window.novaPasskey.cancel());
document.addEventListener("keydown", (e) => e.key === "Escape" && window.novaPasskey.cancel());

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!key.value.trim()) return;
  buttons.forEach((b) => (b.disabled = true));
  key.disabled = true;
  status.className = "";
  status.textContent = "Checking…";
  const r = await window.novaPasskey.submit(key.value);
  if (r.ok) {
    status.textContent = "Unlocked";
    return;
  }
  status.className = "error";
  status.textContent = r.locked
    ? "Wrong passkey. Nova is now locked on this device."
    : `Wrong passkey. ${r.left} ${r.left === 1 ? "try" : "tries"} left. Nova will close.`;
});
