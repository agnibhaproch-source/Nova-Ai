"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";

import { authApi } from "./api";
import { FormAlert } from "./form-alert";
import { PasswordStrength } from "./password-strength";

const schema = z.object({
  display_name: z.string().trim().min(1, "Enter your name").max(80),
  email: z.string().trim().email("Enter a valid email address").max(254),
  password: z.string().min(12, "Use at least 12 characters").max(128),
  accept_terms: z.literal(true, { message: "Please accept the terms to continue" }),
});
type Values = z.infer<typeof schema>;

export function SignupForm() {
  const router = useRouter();
  const [alert, setAlert] = useState<React.ReactNode>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;
  const password = form.watch("password") ?? "";

  const onSubmit = form.handleSubmit(async (values) => {
    setAlert(null);
    try {
      await authApi.signup(values);
      router.replace("/onboarding");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_ALREADY_REGISTERED") {
        form.setError("email", { message: "An account with this email exists. Log in instead?" });
      } else if (err instanceof ApiError && err.code === "PASSWORD_POLICY") {
        form.setError("password", { message: err.message });
      } else if (err instanceof ApiError && err.details.length) {
        for (const d of err.details) {
          const field = d.field?.split(".").pop() as keyof Values | undefined;
          if (field && field in schema.shape) form.setError(field, { message: d.message ?? "Invalid" });
        }
      } else setAlert(errorMessage(err));
    }
  });

  return (
    <form method="post" onSubmit={onSubmit} className="space-y-4" noValidate>
      <div className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold">Create your account</h1>
        <p className="text-sm text-muted-foreground">Start chatting with Nova for free</p>
      </div>
      <FormAlert message={alert as string | null} />
      <Field id="display_name" label="Name" error={errors.display_name?.message}>
        <Input id="display_name" autoComplete="name" autoFocus {...form.register("display_name")} />
      </Field>
      <Field id="email" label="Email" error={errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
      </Field>
      <Field id="password" label="Password" error={errors.password?.message}>
        <Input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
        <PasswordStrength value={password} />
      </Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" {...form.register("accept_terms")} />
        <span>I agree to the <Link href="/terms" className="text-primary hover:underline">Terms</Link> and <Link href="/privacy" className="text-primary hover:underline">Privacy Policy</Link>.</span>
      </label>
      {errors.accept_terms ? <p className="text-xs text-destructive">{errors.accept_terms.message}</p> : null}
      <Button type="submit" className="w-full" size="lg" loading={isSubmitting}>Create account</Button>
      <p className="text-center text-sm text-muted-foreground">
        Already have an account? <Link href="/login" className="text-primary hover:underline">Log in</Link>
      </p>
    </form>
  );
}
