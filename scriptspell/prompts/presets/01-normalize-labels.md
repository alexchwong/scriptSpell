# Normalize labels

## Task

Trim and lowercase string labels, drop blanks, and retain order and duplicates.

Input

A list of text labels, which can be empty or contain blank strings and repeated labels.

Expected output

The trimmed, lowercased nonblank labels in original order. Keep duplicates, including labels that become identical after normalization.

## Medium guidance

Process one label at a time and test for emptiness after trimming.

## Easy guidance

Append each surviving label to a new list. Cover whitespace-only strings and labels that normalize to the same value.
