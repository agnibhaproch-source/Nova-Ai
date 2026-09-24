"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUser } from "@/features/user/user-context";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Row, Section } from "./section";

export function ProfileSettings() {
  const user = useUser();
  const router = useRouter();
  const [name, setName] = useState(user.display_name);
  const [busy, setBusy] = useState(false);
  return (
    <Section title="Profile">
      <Row label="Display name">
        <form className="flex gap-2" onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api("/users/me", { method: "PATCH", json: { display_name: name.trim() } });
            toast.success("Profile updated");
            router.refresh();
          } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
        }}>
          <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} className="w-56" aria-label="Display name" />
          <Button type="submit" variant="outline" loading={busy} disabled={!name.trim() || name.trim() === user.display_name}>Save</Button>
        </form>
      </Row>
      <Row label="Email" description={user.email}>{null}</Row>
    </Section>
  );
}
