#!/usr/bin/env bash
# Fails if a built web bundle contains server secrets or key-shaped strings (docs/35 §6).
set -euo pipefail
cd "$(dirname "$0")/../apps/web"
[ -d .next ] || { echo "build first: pnpm build"; exit 1; }
PATTERN='gsk_[A-Za-z0-9]{20,}|nova_sk_[A-Za-z0-9]{20,}|rzp_(live|test)_[A-Za-z0-9]{10,}|API_PROXY_SHARED_SECRET|AUTH_SECRET|S3_SECRET_KEY|RAZORPAY_KEY_SECRET|RAZORPAY_WEBHOOK_SECRET|SANDBOX_RUNNER_TOKEN'
if grep -rEl "$PATTERN" .next/static 2>/dev/null; then
  echo "check_bundle_secrets: FAILED — secret-like strings found in client bundles"; exit 1
fi
echo "check_bundle_secrets: OK"
