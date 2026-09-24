"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";

export interface PlanInfo {
  key: "free" | "plus" | "pro";
  name: string;
  description: string | null;
  price_paise: number;
  currency: string;
  purchasable: boolean;
  limits_summary: Record<string, number | boolean | null>;
}

export interface Subscription {
  id: string;
  plan_key: string;
  status: string;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export const billingKeys = { plans: ["billing", "plans"] as const, sub: ["billing", "sub"] as const, payments: ["billing", "payments"] as const };

export function usePlans() {
  return useQuery({
    queryKey: billingKeys.plans,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const r = await api<ListEnvelope<PlanInfo> & { meta: { payments_enabled: boolean } }>("/billing/plans");
      return { plans: r.data, paymentsEnabled: r.meta.payments_enabled };
    },
  });
}

export function useSubscription() {
  return useQuery({
    queryKey: billingKeys.sub,
    queryFn: async () => (await api<Envelope<Subscription | null>>("/billing/subscription")).data,
  });
}

export function formatPrice(paise: number, currency = "INR") {
  if (!paise) return "Free";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(paise / 100);
}

export const LIMIT_LABELS: [string, (v: number | boolean | null) => string | null][] = [
  ["messages_per_day", (v) => (typeof v === "number" ? `${v.toLocaleString()} messages / day` : null)],
  ["monthly_token_quota", (v) => (typeof v === "number" ? `${(v / 1_000_000).toFixed(1)}M tokens / month` : null)],
  ["max_document_mb", (v) => (typeof v === "number" ? `Documents up to ${v} MB` : null)],
  ["storage_mb", (v) => (typeof v === "number" ? `${v >= 1024 ? `${v / 1024} GB` : `${v} MB`} file storage` : null)],
  ["web_search_per_day", (v) => (typeof v === "number" && v > 0 ? `${v} web searches / day` : null)],
  ["code_executions_per_day", (v) => (typeof v === "number" && v > 0 ? `${v} code runs / day` : null)],
  ["api_access", (v) => (v ? "API access" : null)],
];

interface CheckoutOrder {
  subscription_id: string;
  razorpay_subscription_id: string;
  razorpay_key_id: string;
  prefill: { name: string; email: string };
}

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void };
  }
}

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Couldn't load the payment window. Check your connection."));
    document.body.appendChild(s);
  });
}

/** Razorpay subscription checkout; the server verifies the signature (docs/31 §12). */
export async function checkout(planKey: string): Promise<boolean> {
  const order = (await api<Envelope<CheckoutOrder>>("/billing/subscriptions", { method: "POST", json: { plan_key: planKey } })).data;
  await loadCheckout();
  return new Promise((resolve, reject) => {
    const rz = new window.Razorpay!({
      key: order.razorpay_key_id,
      subscription_id: order.razorpay_subscription_id,
      name: "Nova",
      description: `Nova ${planKey} plan`,
      prefill: order.prefill,
      theme: { color: "#5b5bd6" },
      modal: { ondismiss: () => resolve(false) },
      handler: async (resp: Record<string, string>) => {
        try {
          await api("/billing/subscriptions/verify", {
            method: "POST",
            json: {
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_subscription_id: resp.razorpay_subscription_id,
              razorpay_signature: resp.razorpay_signature,
            },
          });
          resolve(true);
        } catch (err) {
          reject(err);
        }
      },
    });
    rz.open();
  });
}
