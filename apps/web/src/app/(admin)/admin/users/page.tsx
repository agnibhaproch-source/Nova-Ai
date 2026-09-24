import { UsersTable } from "@/features/admin/users-table";

export const metadata = { title: "Users · Admin" };

export default function Page() {
  return (<div className="space-y-4"><h1 className="text-xl font-semibold">Users</h1><UsersTable /></div>);
}
