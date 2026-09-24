"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

type AdminUser = {
  id: string; email: string; display_name: string; role: string; status: string; plan_key: string;
  created_at: string; last_login_at: string | null;
};

export function UsersTable() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const key = ["admin", "users", q, page];
  const { data, error, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<ListEnvelope<AdminUser>>(`/admin/users?page=${page}&page_size=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });
  const total = Number(data?.meta?.total ?? 0);

  const setStatus = async (u: AdminUser, status: "active" | "suspended") => {
    const reason = window.prompt(`Reason for ${status === "suspended" ? "suspending" : "reactivating"} ${u.email}:`);
    if (!reason || reason.trim().length < 3) return;
    try {
      await api(`/admin/users/${u.id}`, { method: "PATCH", json: { status, reason } });
      toast.success(`User ${status}`);
      await qc.invalidateQueries({ queryKey: ["admin", "users"] });
    } catch (err) { toast.error(errorMessage(err)); }
  };

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div className="space-y-3">
      <Input placeholder="Search email, name or id…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-sm" />
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted-foreground">
            <tr>{["Email", "Name", "Role", "Status", "Plan", "Created", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data?.data.map((u) => (
              <tr key={u.id} className="h-10">
                <td className="px-3">{u.email}</td>
                <td className="px-3">{u.display_name}</td>
                <td className="px-3 capitalize">{u.role}</td>
                <td className="px-3 capitalize">{u.status}</td>
                <td className="px-3 capitalize">{u.plan_key}</td>
                <td className="px-3">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="px-3 text-right">
                  {u.status === "active"
                    ? <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setStatus(u, "suspended")}>Suspend</Button>
                    : <Button size="sm" variant="ghost" onClick={() => setStatus(u, "active")}>Reactivate</Button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{total} users</span>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <Button size="sm" variant="outline" disabled={page * 25 >= total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
}
