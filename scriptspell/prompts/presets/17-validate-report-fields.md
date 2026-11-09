# Validate report fields

## Task

Select configured lab-record fields and report missing fields separately. Preserve zero, false, and explicit null.

## Medium guidance

Use key membership to detect missing fields instead of testing truthiness.

## Easy guidance

Report missing fields separately from selected values. Cover a missing key, a present null, zero, and false.
