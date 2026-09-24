// electron-builder afterSign hook: without a real certificate, sign the macOS app with the local
// identity from scripts/signing-identity.sh so its identity (and Screen Recording permission)
// survives restarts and updates. Real Developer ID builds (CSC_LINK/CSC_NAME) are left alone.
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

exports.default = async function afterSign({ electronPlatformName, appOutDir, packager }) {
  if (electronPlatformName !== "darwin" || process.env.CSC_LINK || process.env.CSC_NAME) return;
  const dir = path.join(__dirname, "..", ".signing");
  const keychain = path.join(dir, "nova-signing.keychain-db");
  if (!fs.existsSync(keychain)) {
    console.warn("  • no local signing identity (run scripts/signing-identity.sh); macOS will re-ask for Screen Recording after every update");
    return;
  }
  const app = path.join(appOutDir, `${packager.appInfo.productFilename}.app`);
  execFileSync("security", ["unlock-keychain", "-p", fs.readFileSync(path.join(dir, "keychain.pass"), "utf8"), keychain]);
  execFileSync("codesign", ["--force", "--deep", "--keychain", keychain, "-s", "Nova Local Signing", "-i", packager.appInfo.id, app], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
  console.log(`  • signed with local identity  app=${app}`);
};
