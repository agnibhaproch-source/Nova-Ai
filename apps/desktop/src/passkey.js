// Passkey gate: Nova asks for a passkey every time it starts. Wrong or missing → it doesn't open.
// After MAX_TRIES wrong passkeys (counted across launches) Nova stays locked on this device for good.
//
// - Only a salted scrypt hash of the passkey is shipped; the check is constant-time.
// - The failure count lives in two places (the app's data folder and a hidden file elsewhere in
//   the user's profile) so reinstalling or deleting one of them doesn't reset it. Each record carries
//   an HMAC; a record that was edited counts as locked.
// This is a local gate. Someone with full control of the machine can still remove its files, and a
// 5-digit passkey can be brute-forced offline from the hash; it stops casual use, not a determined
// attacker.
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const MAX_TRIES = 3;
const SALT = Buffer.from("abfd8e8ccd8fe5e9c3ea6cd9fc93478a", "hex");
const HASH = Buffer.from("3b2abfa85244b15d3a57f6b93ce436637aac6bee84cf00fb37efa8c93d7351ba", "hex");
const HMAC_KEY = Buffer.from("7a4a10188039995e4eac146485f9e50de7d7e4887ead92c5d45b2c6f46c38f19", "hex");
const SCRYPT = { N: 16384, r: 8, p: 1 };

function checkPasskey(input) {
  const candidate = crypto.scryptSync(String(input ?? "").trim(), SALT, HASH.length, SCRYPT);
  return crypto.timingSafeEqual(candidate, HASH);
}

/** Where the failure count is kept: the app's data folder plus a second, OS-specific spot. */
function guardFiles(app) {
  const primary = path.join(app.getPath("userData"), ".guard");
  // Unpackaged runs (development, tests) keep everything inside their own data folder, so they
  // can never lock the real installed app.
  if (!app.isPackaged) return [primary, path.join(app.getPath("userData"), ".guard2")];
  const home = os.homedir();
  const second =
    process.platform === "win32"
      ? path.join(process.env.LOCALAPPDATA || path.join(home, "AppData", "Local"), ".ai.nova.quickchat")
      : process.platform === "darwin"
        ? path.join(home, "Library", "Application Support", ".ai.nova.quickchat")
        : path.join(process.env.XDG_STATE_HOME || path.join(home, ".local", "state"), ".ai.nova.quickchat");
  return [primary, second];
}

const sign = (body) => crypto.createHmac("sha256", HMAC_KEY).update(body).digest("hex");

function readOne(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    return { fails: 0, locked: false }; // never written yet
  }
  try {
    const { body, mac } = JSON.parse(raw);
    const a = Buffer.from(sign(body), "hex");
    const b = Buffer.from(String(mac), "hex");
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) throw new Error("tampered");
    const s = JSON.parse(body);
    return { fails: Math.max(0, Number(s.fails) || 0), locked: !!s.locked };
  } catch {
    return { fails: MAX_TRIES, locked: true }; // edited or corrupted: treat as locked
  }
}

/** Combined state: the worst of both records. */
function readState(app) {
  const states = guardFiles(app).map(readOne);
  const fails = Math.max(...states.map((s) => s.fails));
  return { fails, locked: states.some((s) => s.locked) || fails >= MAX_TRIES, left: Math.max(0, MAX_TRIES - fails) };
}

function writeState(app, fails) {
  const body = JSON.stringify({ fails, locked: fails >= MAX_TRIES, at: new Date().toISOString() });
  const data = JSON.stringify({ body, mac: sign(body) });
  for (const file of guardFiles(app)) {
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, data, { mode: 0o600 });
    } catch {
      // one location unwritable: the other still holds the count
    }
  }
}

/** Checks one attempt and records the outcome. Returns { ok, left, locked }. */
function attempt(app, input) {
  const state = readState(app);
  if (state.locked) return { ok: false, left: 0, locked: true };
  if (checkPasskey(input)) {
    if (state.fails) writeState(app, 0);
    return { ok: true, left: MAX_TRIES, locked: false };
  }
  const fails = state.fails + 1;
  writeState(app, fails);
  return { ok: false, left: Math.max(0, MAX_TRIES - fails), locked: fails >= MAX_TRIES };
}

module.exports = { MAX_TRIES, attempt, readState, checkPasskey };
