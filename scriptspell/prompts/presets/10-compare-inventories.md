# Compare inventories

## Task

Compare two SKU-to-quantity objects. Return sorted added, removed and changed SKU lists, including old and new quantities for changes.

Input

An old and a new mapping from SKU to integer stock quantity. A quantity of zero still means the SKU is present.

Expected output

Separate sorted lists of added, removed and changed SKUs. Each changed entry includes the old and new quantities in that order.

## Medium guidance

Compare key membership first, then compare quantities only for shared keys.

## Easy guidance

Traverse sorted keys for deterministic output. Cover a SKU with quantity zero and a shared SKU whose quantity did not change.
