# Pivot observations

## Task

Pivot measurements into one object per subject keyed by analyte. Keep the last duplicate measurement and the first-seen subject order.

## Medium guidance

Accumulate one analyte map per subject and track subject order as subjects first appear.

## Easy guidance

Assign each measurement to its analyte key, replacing any previous value there. Cover interleaved subjects and a repeated subject/analyte pair.
