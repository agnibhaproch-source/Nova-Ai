import "server-only";

import fs from "node:fs";
import path from "node:path";

export type Platform = "mac" | "windows" | "linux";

const FILES: Record<Platform, { file: string; env: string }> = {
  mac: { file: "Nova-mac.dmg", env: "DESKTOP_MAC_DOWNLOAD_URL" },
  windows: { file: "Nova-win.exe", env: "DESKTOP_WINDOWS_DOWNLOAD_URL" },
  linux: { file: "Nova-linux.AppImage", env: "DESKTOP_LINUX_DOWNLOAD_URL" },
};

export const isPlatform = (p: string): p is Platform => p in FILES;

/**
 * Where a desktop installer is downloaded from: DESKTOP_<OS>_DOWNLOAD_URL (release/CDN) if set,
 * else the file published into public/downloads by `make desktop-release`.
 */
export function release(p: Platform): { url: string; sizeMb: number | null } | null {
  const { file, env } = FILES[p];
  const external = process.env[env];
  if (external) return { url: external, sizeMb: null };
  try {
    const { size } = fs.statSync(path.join(process.cwd(), "public", "downloads", file));
    return { url: `/downloads/${file}`, sizeMb: Math.round(size / 1024 / 1024) };
  } catch {
    return null;
  }
}

export const macRelease = () => release("mac");
