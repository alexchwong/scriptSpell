# Resolve configuration

## Task

Overlay configuration objects in order. Recursively merge two objects at the same key, otherwise replace with the later value, including null.

## Medium guidance

Use a recursive helper only when both values at a key are objects.

## Easy guidance

Copy retained fields and replace lists as a whole. Cover nested sibling keys, replacement by a list, and replacement by null.
