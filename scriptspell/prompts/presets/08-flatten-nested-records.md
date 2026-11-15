# Flatten nested records

## Task

Flatten departments, teams and staff to one record per person with all three identifiers, in traversal order. Skip empty groups.

Input

A hierarchy of departments, teams and staff, each with an identifier. Groups may be empty.

Expected output

A flat list containing the three identifiers for each staff member, in traversal order. Empty groups contribute no rows.

## Medium guidance

Traverse departments, then teams, then staff, carrying the two parent IDs.

## Easy guidance

Append output only when visiting a person. Cover empty departments and teams alongside populated ones.
