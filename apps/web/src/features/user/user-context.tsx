"use client";

import { createContext, useContext } from "react";

import type { User } from "@/lib/types";

const UserContext = createContext<User | null>(null);

export function UserProvider({ user, children }: { user: User; children: React.ReactNode }) {
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function useUser(): User {
  const u = useContext(UserContext);
  if (!u) throw new Error("useUser must be used inside UserProvider");
  return u;
}
