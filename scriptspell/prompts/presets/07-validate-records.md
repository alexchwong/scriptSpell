# Validate records

## Task

Report every order record error by index and field. IDs must be nonempty strings, quantities positive integers, and unit prices nonnegative integer cents. Reject booleans as numbers.

Input

An ordered list of order records. Fields may be missing or of the wrong type, including boolean values in numeric fields.

Expected output

A list of all errors with the zero-based record index and field name. Report missing fields and multiple violations independently.

## Medium guidance

Validate fields independently and exclude booleans before checking integer bounds.

## Easy guidance

Keep collecting errors when a record has several invalid fields. Cover zero price (valid), zero quantity (invalid), and boolean quantity (invalid).
