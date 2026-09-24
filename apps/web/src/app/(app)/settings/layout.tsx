import { TopBar } from "@/components/layout/top-bar";
import { SettingsNav } from "@/features/settings/nav";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <TopBar title="Settings" />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 md:flex-row">
          <SettingsNav />
          <div className="min-w-0 max-w-[720px] flex-1 space-y-6">{children}</div>
        </div>
      </div>
    </>
  );
}
