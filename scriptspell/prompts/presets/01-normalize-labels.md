# Normalize labels

## Task

Trim and lowercase string labels, drop blanks, and retain order and duplicates.

## Medium guidance

Process one label at a time and test for emptiness after trimming.

## Easy guidance

Append each surviving label to a new list. Cover whitespace-only strings and labels that normalize to the same value.
