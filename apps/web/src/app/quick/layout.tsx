import { redirect } from "next/navigation";

import { UserProvider } from "@/features/user/user-context";
import { getServerUser } from "@/lib/auth/server-session";

export const metadata = { title: "Quick Chat" };

// Standalone Quick Chat window (opened via "Pop out"): no sidebar, just the chat.
export default async function QuickLayout({ children }: { children: React.ReactNode }) {
  const user = await getServerUser();
  if (!user) redirect("/login");
  return <UserProvider user={user}>{children}</UserProvider>;
}
