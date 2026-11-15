# Reconcile payments

## Task

Reconcile invoice balances with payments by invoice ID. Report unpaid, partial, settled and overpaid invoices and unmatched payments in integer cents.

Input

Invoice records with unique IDs and positive balances in integer cents, plus payments with invoice IDs and amounts in integer cents.

Expected output

Separate unpaid, partial, settled and overpaid invoice lists, plus unmatched payments. An invoice with zero paid is unpaid. Compare summed payments with its balance for the other categories. Keep invoices in invoice input order within each list. List each unmatched payment record individually in payment input order.

## Medium guidance

Sum payments by invoice ID and compare totals with balances. Track payments whose IDs have no invoice.

## Easy guidance

Keep cent values as integers. Cover multiple payments for one invoice, an overpayment, and a payment for an unknown invoice.
