#!/usr/bin/env node
// Sets the desktop app's passkey: node scripts/set-passkey.js <passkey>
// Stores only a new random salt + scrypt hash in src/passkey.js (the passkey itself is never
// written anywhere). Rebuild the app afterwards (make desktop-release).
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const passkey = process.argv[2];
if (!passkey || passkey.trim().length < 4) {
  console.error("Usage: node scripts/set-passkey.js <passkey>   (at least 4 characters)");
  process.exit(1);
}

const file = path.join(__dirname, "..", "src", "passkey.js");
let src = fs.readFileSync(file, "utf8");
const salt = crypto.randomBytes(16);
const hash = crypto.scryptSync(passkey.trim(), salt, 32, { N: 16384, r: 8, p: 1 });
const hmacKey = crypto.randomBytes(32);

const set = (name, hex) => {
  const re = new RegExp(`const ${name} = Buffer\\.from\\("[0-9a-f]+", "hex"\\);`);
  if (!re.test(src)) throw new Error(`${name} not found in ${file}`);
  src = src.replace(re, `const ${name} = Buffer.from("${hex}", "hex");`);
};
set("SALT", salt.toString("hex"));
set("HASH", hash.toString("hex"));
// A new HMAC key also means lock records written by a previous build are treated as tampered
// (locked); to keep old installs working, rebuild only for fresh installs or keep the key.
if (process.argv.includes("--new-hmac-key")) set("HMAC_KEY", hmacKey.toString("hex"));
fs.writeFileSync(file, src);
console.log("Passkey updated in src/passkey.js. Rebuild the app (make desktop-release) to use it.");
