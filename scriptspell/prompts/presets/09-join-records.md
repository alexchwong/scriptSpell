# Join records

## Task

Left-join orders to customer names by customer ID. Preserve the original order of orders and use null for unmatched names.

Input

Two lists, one of orders with customer IDs and one of customer records with unique IDs and names.

Expected output

All order records in their original order, enriched with the corresponding customer name or null when the ID has no match.

## Medium guidance

Index customer names by ID, then visit the orders in their original order.

## Easy guidance

Retain each order even if its customer ID is absent from the lookup. Cover both matched and unmatched orders.
