# Classify thresholds

## Task

Classify readings against inclusive bounds as below, within, or above, with missing and null readings in a separate category.

Input

An ordered list of reading records with an optional numeric value, and inclusive lower and upper bounds. Use integers or consistently represented decimals.

Expected output

Separate lists for readings below, within or above the bounds, and readings with an absent or null value. Keep input order within each category.

## Medium guidance

Handle missing or null first, then use strict comparisons for below and above.

## Easy guidance

Cover both boundary values, a missing reading, and a zero reading. Use integers or exact decimal strings for numeric examples.
