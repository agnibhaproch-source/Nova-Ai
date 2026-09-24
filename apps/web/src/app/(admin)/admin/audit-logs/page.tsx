import { AuditTable } from "@/features/admin/audit-table";

export const metadata = { title: "Audit logs · Admin" };

export default function Page() {
  return (<div className="space-y-4"><h1 className="text-xl font-semibold">Audit logs</h1><AuditTable /></div>);
}
