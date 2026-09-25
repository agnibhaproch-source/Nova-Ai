"use client";

import { Gauge, Laptop, LogOut, Monitor, Moon, Settings, Shield, Sun } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { authApi } from "@/features/auth/api";
import { applyTheme } from "@/features/user/theme";
import { useUser } from "@/features/user/user-context";

export function UserMenu() {
  const user = useUser();
  const router = useRouter();
  const initials = user.display_name.slice(0, 1).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-2 rounded-md p-2 text-left hover:bg-accent">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary text-sm font-medium text-primary-foreground">
          {initials}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{user.display_name}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-60">
        <DropdownMenuLabel className="truncate">{user.email}</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => router.push("/settings/general")}><Settings /> Settings</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/settings/usage")}><Gauge /> Usage</DropdownMenuItem>
        {typeof window !== "undefined" && !window.novaDesktop ? (
          <DropdownMenuItem onSelect={() => router.push("/download")}><Laptop /> Get the Mac app</DropdownMenuItem>
        ) : null}
        {user.role !== "user" ? (
          <DropdownMenuItem onSelect={() => router.push("/admin")}><Shield /> Admin</DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => applyTheme("system")}><Monitor /> System</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => applyTheme("light")}><Sun /> Light</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => applyTheme("dark")}><Moon /> Dark</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            try {
              await authApi.logout();
            } finally {
              window.location.assign("/login");
            }
          }}
        >
          <LogOut /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
