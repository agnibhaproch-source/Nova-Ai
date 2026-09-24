import { Onboarding } from "@/features/settings/onboarding";

export const metadata = { title: "Welcome" };

export default function Page() {
  return (
    <div className="flex flex-1 items-center justify-center overflow-y-auto p-4">
      <Onboarding />
    </div>
  );
}
