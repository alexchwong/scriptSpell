# Validate records

## Task

Report every order record error by index and field. IDs must be nonempty strings, quantities positive integers, and unit prices nonnegative integer cents. Reject booleans as numbers.

## Medium guidance

Validate fields independently and exclude booleans before checking integer bounds.

## Easy guidance

Keep collecting errors when a record has several invalid fields. Cover zero price, zero quantity, and boolean quantity.
