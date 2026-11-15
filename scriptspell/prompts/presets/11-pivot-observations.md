# Pivot observations

## Task

Pivot measurements into one object per subject keyed by analyte. Keep the last duplicate measurement and the first-seen subject order.

Input

An ordered list of measurements with a subject ID, analyte name and measured value.

Expected output

A list in first-seen subject order. Each entry contains the subject ID and a mapping of analytes to values. A repeated subject/analyte pair keeps the last value.

## Medium guidance

Accumulate one analyte map per subject and track subject order as subjects first appear.

## Easy guidance

Assign each measurement to its analyte key, replacing any previous value there. Cover interleaved subjects and a repeated subject/analyte pair.
