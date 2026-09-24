"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/errors";

import { authApi } from "./api";
import { FormAlert } from "./form-alert";
import { PasswordStrength } from "./password-strength";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [alert, setAlert] = useState<string | null>(null);
  if (sent)
    return (
      <div className="space-y-3 text-center">
        <h1 className="text-2xl font-semibold">Check your email</h1>
        <p className="text-sm text-muted-foreground">If an account exists for {email}, we&apos;ve sent a reset link.</p>
        <Link href="/login" className="text-sm text-primary hover:underline">Back to log in</Link>
      </div>
    );
  return (
    <form
      method="post"
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setAlert(null);
        try {
          await authApi.forgot(email.trim());
          setSent(true);
        } catch (err) {
          setAlert(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold">Reset your password</h1>
        <p className="text-sm text-muted-foreground">We&apos;ll email you a link to set a new one.</p>
      </div>
      <FormAlert message={alert} />
      <Field id="email" label="Email">
        <Input id="email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={busy}>Send reset link</Button>
      <p className="text-center text-sm"><Link href="/login" className="text-primary hover:underline">Back to log in</Link></p>
    </form>
  );
}

export function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [alert, setAlert] = useState<string | null>(null);
  return (
    <form
      method="post"
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (pw !== confirm) return setAlert("Passwords don't match.");
        setBusy(true);
        setAlert(null);
        try {
          await authApi.reset(token, pw);
          toast.success("Password updated. Log in with your new password.");
          router.replace("/login");
        } catch (err) {
          setAlert(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1 className="text-center text-2xl font-semibold">Choose a new password</h1>
      <FormAlert message={alert} />
      <Field id="password" label="New password">
        <Input id="password" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
        <PasswordStrength value={pw} />
      </Field>
      <Field id="confirm" label="Confirm password">
        <Input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={busy} disabled={!token}>Update password</Button>
    </form>
  );
}
