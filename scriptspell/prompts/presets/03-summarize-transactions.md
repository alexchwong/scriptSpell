# Summarize transactions

## Task

Group transactions by account and return counts and signed integer-cent totals, sorted by account.

Input

A list of transactions with an account identifier and a signed integer amount already expressed in cents.

Expected output

One record per account, sorted by account, with transaction count and total in cents. Count zero amounts and include refunds in the sum.

## Medium guidance

Keep a running count and total per account before sorting the output.

## Easy guidance

Increment the count even for zero amounts. Cover a refund and accounts that appear out of order.
