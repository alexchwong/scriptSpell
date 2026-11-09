# Compare inventories

## Task

Compare two SKU-to-quantity objects. Return sorted added, removed and changed SKU lists, including old and new quantities for changes.

## Medium guidance

Compare key membership first, then compare quantities only for shared keys.

## Easy guidance

Traverse sorted keys for deterministic output. Cover a SKU with quantity zero and a shared SKU whose quantity did not change.
