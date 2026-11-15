# Resolve configuration

## Task

Overlay configuration objects in order. Recursively merge two objects at the same key, otherwise replace with the later value, including null.

Input

Configuration mappings in overlay order, possibly containing nested mappings, lists and null values.

Expected output

The merged mapping. Keep earlier keys absent from later mappings. Recurse only when both values are mappings. A later list or null replaces the earlier value.

## Medium guidance

Use a recursive helper only when both values at a key are objects.

## Easy guidance

Copy retained fields and replace lists as a whole. Cover nested sibling keys, replacement by a list, and replacement by null.
