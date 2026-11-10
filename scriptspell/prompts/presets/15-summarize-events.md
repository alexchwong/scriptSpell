# Summarize events

## Task

Within a supplied half-open integer timestamp window, report each event category’s count and highest severity under a supplied severity order.

## Medium guidance

Filter on the timestamp first, then group by category and rank severities by the supplied ordering.

## Easy guidance

Include the start timestamp and exclude the end timestamp. Cover a category whose highest-ranked severity is lexically earlier than another severity.
