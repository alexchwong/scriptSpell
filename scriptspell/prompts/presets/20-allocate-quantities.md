# Allocate quantities

## Task

Allocate integer stock by descending request priority, breaking ties by input order. Allow partial fills and report filled and remaining quantities in original request order.

## Medium guidance

Allocate against remaining stock in priority order and retain each request’s original position.

## Easy guidance

Fill the smaller of available stock and requested quantity, then reduce available stock. Cover a priority tie, a partial fill and an exhausted stock case.
