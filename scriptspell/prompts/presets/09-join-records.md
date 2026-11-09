# Join records

## Task

Left-join orders to customer names by customer ID. Preserve the original order of orders and use null for unmatched names.

## Medium guidance

Index customer names by ID, then visit the orders in their original order.

## Easy guidance

Retain each order even if its customer ID is absent from the lookup. Cover both matched and unmatched orders.
