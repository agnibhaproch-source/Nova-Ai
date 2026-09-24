# Razorpay webhooks / plans

## Webhook failures
**Check:** Admin → Billing → Webhook events with `processing_error`.
**Fix:** fix the cause (usually an unknown subscription id or a deploy bug), then press **Reprocess**
(audited). Events are idempotent by event id, so replays are safe.
**Verify:** event shows `processed`; the user's plan matches Razorpay's dashboard.

## Create Razorpay plans (one-time per environment)
1. Razorpay dashboard → Subscriptions → Plans: create **Plus** (₹499/month) and **Pro** (₹1,499/month), INR, monthly — in test mode and live mode.
2. Store the ids: `cd apps/api && uv run python -m scripts.set_razorpay_plan_ids --plus plan_XXX --pro plan_YYY`.
3. Webhook URL `https://<domain>/api/v1/webhooks/razorpay`, set the secret as `RAZORPAY_WEBHOOK_SECRET`, subscribe to subscription.* and payment.* events (docs/31 §12).
4. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `NEXT_PUBLIC_RAZORPAY_KEY_ID`; restart. `/billing/plans` now shows `purchasable: true`.
