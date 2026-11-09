# Check dependencies

## Task

Report ready tasks given completed IDs and separately report unknown dependency IDs. Preserve task order.

## Medium guidance

Build lookups for known task IDs and completed IDs, then inspect each task’s dependencies.

## Easy guidance

A task can start when all dependencies are satisfied. Cover a task with no dependencies, one with an unfinished dependency and one referencing an unknown ID.
