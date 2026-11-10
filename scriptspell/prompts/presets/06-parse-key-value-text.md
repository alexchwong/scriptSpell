# Parse key-value text

## Task

Parse text lines at the first equals sign. Ignore blanks and hash comments after trimming, keep the last value per key, and report malformed line numbers starting at one.

## Medium guidance

Enumerate original lines before skipping anything. Split valid lines at most once.

## Easy guidance

Keep embedded equals signs in the value. Cover an indented comment, a repeated key, and a malformed line after a skipped line.
