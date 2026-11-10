# Flatten nested records

## Task

Flatten departments, teams and staff to one record per person with all three identifiers, in traversal order. Skip empty groups.

## Medium guidance

Traverse departments, then teams, then staff, carrying the two parent IDs.

## Easy guidance

Append output only when visiting a person. Cover empty departments and teams alongside populated ones.
