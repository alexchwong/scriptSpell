# Validate report fields

## Task

Select configured lab-record fields and report missing fields separately. Preserve zero, false, and explicit null.

Input

A record and an ordered list of requested field names. A present field may contain zero, false or null.

Expected output

A mapping of requested fields that are present and a list of missing field names in request order. Preserve the values of present fields exactly.

## Medium guidance

Use key membership to detect missing fields instead of testing truthiness.

## Easy guidance

Report missing fields separately from selected values. Cover a missing key, a present null, zero, and false.
