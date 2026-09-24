import { QuickWindow } from "@/features/quick-chat/quick-window";

export default async function QuickPage(props: PageProps<"/quick">) {
  const { c } = await props.searchParams;
  return <QuickWindow initialConversationId={typeof c === "string" ? c : null} />;
}
