# Merge intervals

## Task

Merge overlapping or touching integer half-open intervals into sorted disjoint intervals. Ignore empty intervals and report reversed intervals as invalid.

Input

A list of pairs of integer endpoints for half-open intervals. Empty and reversed intervals may occur.

Expected output

A list of sorted merged endpoint pairs and a separate list of reversed pairs in input order. Merge touching intervals and omit empty intervals.

## Medium guidance

Separate invalid and empty intervals before sorting by start and sweeping through the valid intervals.

## Easy guidance

Merge when the next start is at most the current end, keeping the larger end. Cover touching, contained, empty and reversed intervals.
