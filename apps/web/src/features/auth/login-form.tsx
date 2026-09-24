"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";

import { authApi, safeNext } from "./api";
import { FormAlert } from "./form-alert";

const schema = z.object({
  email: z.string().trim().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [show, setShow] = useState(false);
  const [alert, setAlert] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setAlert(null);
    try {
      const { data } = await authApi.login(values.email, values.password);
      router.replace(data.onboarding_completed ? safeNext(params.get("next")) : "/onboarding");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "ACCOUNT_LOCKED" && err.retryAfter) {
        setAlert(`Too many attempts. Try again in ${Math.ceil(err.retryAfter / 60)} minutes.`);
      } else setAlert(errorMessage(err));
    }
  });

  return (
    <form method="post" onSubmit={onSubmit} className="space-y-4" noValidate>
      <div className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold">Welcome back</h1>
        <p className="text-sm text-muted-foreground">Log in to continue to Nova</p>
      </div>
      <FormAlert message={alert} />
      <Field id="email" label="Email" error={errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" autoFocus aria-invalid={!!errors.email} {...form.register("email")} />
      </Field>
      <Field
        id="password"
        label="Password"
        error={errors.password?.message}
        hint={<Link href="/forgot-password" className="text-xs text-primary hover:underline">Forgot password?</Link>}
      >
        <div className="relative">
          <Input id="password" type={show ? "text" : "password"} autoComplete="current-password" aria-invalid={!!errors.password} {...form.register("password")} />
          <button type="button" onClick={() => setShow((s) => !s)} className="absolute inset-y-0 right-2 flex items-center px-1 text-muted-foreground" aria-label={show ? "Hide password" : "Show password"}>
            {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={isSubmitting}>Log in</Button>
      <p className="text-center text-sm text-muted-foreground">
        New to Nova? <Link href="/signup" className="text-primary hover:underline">Create an account</Link>
      </p>
    </form>
  );
}
