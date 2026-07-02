# Runbook: Payment Webhook 5xx / Null Pointer

**Applies to alerts:** `payment_webhook_5xx_rate` spike, orders stuck in `pending_payment`.

## Diagnosis

1. Pull the stack trace from the error tracker for the webhook handler — a `NoneType` / `KeyError` on a `charge` field is the signature of a missing null/None guard, typically triggered by refund or dispute events whose payload omits the `charge` object.
2. Diff recent commits to the webhook handler for removed `if charge is None` (or equivalent) guards — refactors that "simplify" a handler are a common way this regression ships.
3. Confirm the affected event types (refunds/disputes typically, not standard charge.succeeded events) to size the blast radius.

## Mitigation

1. Hotfix: reinstate the null guard and redeploy immediately — this is payment-path-blocking and should be treated as high urgency even if overall traffic volume is low.
2. Once the guard is back, replay/reprocess the failed webhook deliveries from the payment provider's retry queue (or trigger a manual reconciliation job) to unstick orders left in `pending_payment`.
3. Confirm `payment_webhook_5xx_rate` returns to baseline and pending order count stops climbing.

## Prevention

- Add a webhook test fixture covering refund/dispute payloads with no `charge` object, not just the happy path.
