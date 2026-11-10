# Reconcile payments

## Task

Reconcile invoice balances with payments by invoice ID. Report unpaid, partial, settled and overpaid invoices and unmatched payments in integer cents.

## Medium guidance

Sum payments by invoice ID and compare totals with balances. Track payments whose IDs have no invoice.

## Easy guidance

Keep cent values as integers. Cover multiple payments for one invoice, an overpayment, and a payment for an unknown invoice.
