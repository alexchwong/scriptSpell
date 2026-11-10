# Summarize events

## Task

Within a supplied half-open integer timestamp window, report each event category’s count and highest severity under a supplied severity order.

Input

Event records with categories, integer timestamps and severities, start and end timestamps, and a severity list ordered highest first. Every event severity is in that list.

Expected output

Per-category event counts and the highest-ranked severity present. Include timestamps at the start and exclude those at the end.

## Medium guidance

Filter on the timestamp first, then group by category and rank severities by the supplied ordering.

## Easy guidance

Include the start timestamp and exclude the end timestamp. Cover a category whose highest-ranked severity is lexically earlier than another severity.
