# Stable deduplication

## Task

Deduplicate records by ID, keeping the first record for each ID in input order.

Input

An ordered list of records, each with an ID and any associated fields.

Expected output

The whole first record for each ID, in input order. Keep its payload even if a later duplicate differs.

## Medium guidance

Track IDs already encountered while traversing the records.

## Easy guidance

Copy the full first record, including its payload. Cover a repeated ID with a different payload.
