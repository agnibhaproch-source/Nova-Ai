import { redirect } from "next/navigation";

import { ChatPage } from "@/features/chat/components/chat-page";
import { getServerUser } from "@/lib/auth/server-session";

export const metadata = { title: "New chat" };

export default async function Page() {
  const user = await getServerUser();
  if (user && !user.onboarding_completed) redirect("/onboarding");
  return <ChatPage conversationId={null} />;
}
