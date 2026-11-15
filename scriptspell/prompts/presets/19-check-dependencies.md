# Check dependencies

## Task

Report ready tasks given completed IDs and separately report unknown dependency IDs. Preserve task order.

Input

An ordered list of tasks with unique IDs and dependency IDs, plus the IDs of completed tasks.

Expected output

Ready task IDs in task order, excluding completed tasks. A task is ready if every dependency is known and completed. Report unknown dependency IDs separately, once each in first-seen order.

## Medium guidance

Build lookups for known task IDs and completed IDs, then inspect each task’s dependencies.

## Easy guidance

A task can start when all dependencies are satisfied. Cover a task with no dependencies, one with an unfinished dependency and one referencing an unknown ID.
