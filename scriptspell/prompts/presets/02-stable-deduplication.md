# Stable deduplication

## Task

Deduplicate records by ID, keeping the first record for each ID in input order.

## Medium guidance

Track IDs already encountered while traversing the records.

## Easy guidance

Copy the full first record, including its payload. Cover a repeated ID with a different payload.
