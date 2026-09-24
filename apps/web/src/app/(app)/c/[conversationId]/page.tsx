import { notFound } from "next/navigation";

import { ChatPage } from "@/features/chat/components/chat-page";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function Page(props: PageProps<"/c/[conversationId]">) {
  const { conversationId } = await props.params;
  if (!UUID.test(conversationId)) notFound();
  return <ChatPage conversationId={conversationId} />;
}
