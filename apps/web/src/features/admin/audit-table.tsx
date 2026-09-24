"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorState } from "@/components/common/states";
import { Input } from "@/components/ui/input";
import { api, type ListEnvelope } from "@/lib/api/client";

type Audit = { id: string; actor_user_id: string | null; actor_type: string; action: string; target_type: string | null; target_id: string | null; reason: string | null; created_at: string };

export function AuditTable() {
  const [action, setAction] = useState("");
  const { data, error, refetch } = useQuery({
    queryKey: ["admin", "audit", action],
    queryFn: () => api<ListEnvelope<Audit>>(`/admin/audit-logs?limit=100${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div className="space-y-3">
      <Input placeholder="Filter by action prefix, e.g. admin." value={action} onChange={(e) => setAction(e.target.value)} className="max-w-sm" />
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted-foreground">
            <tr>{["Time", "Action", "Actor", "Target", "Reason"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data?.data.map((a) => (
              <tr key={a.id} className="h-10">
                <td className="whitespace-nowrap px-3">{new Date(a.created_at).toLocaleString()}</td>
                <td className="px-3 font-mono text-xs">{a.action}</td>
                <td className="px-3 text-xs">{a.actor_type} {a.actor_user_id?.slice(0, 8)}</td>
                <td className="px-3 text-xs">{a.target_type} {a.target_id?.slice(0, 8)}</td>
                <td className="px-3">{a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
