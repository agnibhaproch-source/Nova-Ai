"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { billingKeys, checkout, formatPrice, usePlans, useSubscription } from "@/features/billing/api";
import { PlanCards } from "@/features/billing/plan-cards";
import { useUser } from "@/features/user/user-context";
import { api, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Row, Section } from "./section";

interface Payment {
  id: string;
  amount_paise: number;
  currency: string;
  status: string;
  method: string | null;
  created_at: string;
}

export function BillingSettings() {
  const qc = useQueryClient();
  const user = useUser();
  const { data: plans } = usePlans();
  const { data: sub } = useSubscription();
  const [busy, setBusy] = useState<string | null>(null);
  const payments = useQuery({ queryKey: billingKeys.payments, queryFn: async () => (await api<ListEnvelope<Payment>>("/billing/payments")).data });

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["billing"] });
    window.location.reload(); // plan changes affect the session's limits everywhere
  };

  const upgrade = async (planKey: string) => {
    setBusy(planKey);
    try {
      if (await checkout(planKey)) {
        toast.success("Payment received — your plan is active.");
        await refresh();
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    if (!window.confirm("Cancel your subscription? You keep your plan until the end of the billing period.")) return;
    try {
      await api("/billing/subscription/cancel", { method: "POST", json: { at_period_end: true } });
      toast.success("Subscription will end at the period end.");
      await qc.invalidateQueries({ queryKey: billingKeys.sub });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const live = sub && ["active", "authenticated", "pending"].includes(sub.status);
  return (
    <div className="space-y-6">
      <Section title="Plan" description={`You're on the ${user.plan_key} plan.`}>
        {live ? (
          <Row
            label={`Nova ${sub.plan_key}`}
            description={
              sub.cancel_at_period_end
                ? `Ends ${sub.current_period_end ? new Date(sub.current_period_end).toLocaleDateString() : "at period end"}`
                : sub.current_period_end
                  ? `Renews ${new Date(sub.current_period_end).toLocaleDateString()}`
                  : `Status: ${sub.status}`
            }
          >
            {!sub.cancel_at_period_end ? <Button variant="outline" size="sm" onClick={() => void cancel()}>Cancel</Button> : null}
          </Row>
        ) : null}
        {plans && !plans.paymentsEnabled ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">Payments aren&apos;t enabled on this deployment yet.</p>
        ) : null}
      </Section>
      {plans ? (
        <PlanCards
          plans={plans.plans}
          current={user.plan_key}
          action={(p) =>
            p.purchasable && !live ? (
              <Button disabled={busy !== null} onClick={() => void upgrade(p.key)}>
                {busy === p.key ? "Opening…" : `Upgrade to ${p.name}`}
              </Button>
            ) : (
              <Button variant="outline" disabled>{p.price_paise ? "Unavailable" : "Included"}</Button>
            )
          }
        />
      ) : null}
      <Section title="Payment history">
        {payments.data?.length ? (
          payments.data.map((p) => (
            <Row key={p.id} label={formatPrice(p.amount_paise, p.currency)} description={`${new Date(p.created_at).toLocaleDateString()}${p.method ? ` · ${p.method}` : ""}`}>
              <span className="text-sm capitalize text-muted-foreground">{p.status}</span>
            </Row>
          ))
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">No payments yet.</p>
        )}
      </Section>
    </div>
  );
}
