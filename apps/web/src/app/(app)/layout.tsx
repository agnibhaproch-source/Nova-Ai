import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { QuickChatLauncher } from "@/features/quick-chat/quick-chat";
import { UserProvider } from "@/features/user/user-context";
import { getServerUser } from "@/lib/auth/server-session";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await getServerUser();
  if (!user) redirect("/login");
  return (
    <UserProvider user={user}>
      <AppShell>{children}</AppShell>
      <QuickChatLauncher />
    </UserProvider>
  );
}
