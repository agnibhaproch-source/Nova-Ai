export type Theme = "system" | "light" | "dark";

export function applyTheme(theme: Theme) {
  try {
    localStorage.setItem("nova-theme", theme);
  } catch {
    /* storage unavailable */
  }
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}
