import { notFound } from "next/navigation";

import { SETTINGS_PAGES } from "@/features/settings/registry";

export default async function Page(props: PageProps<"/settings/[section]">) {
  const { section } = await props.params;
  const Component = SETTINGS_PAGES[section];
  if (!Component) notFound();
  return <Component />;
}
