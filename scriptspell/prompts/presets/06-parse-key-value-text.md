# Parse key-value text

## Task

Parse text lines at the first equals sign. Ignore blanks and hash comments after trimming, keep the last value per key, and report malformed line numbers starting at one.

Input

Text lines in their original order, possibly containing blanks, hash comments or extra equals signs.

Expected output

A mapping from key to its last value and a list of one-based line numbers for malformed lines. After trimming each whole line, skip blanks and lines whose first character is `#`. An interior `#` is not a comment marker. A non-comment line without an equals sign is malformed. Split each remaining line at only its first `=`. Trim the key and value independently. For repeated trimmed keys, retain the last value.

## Medium guidance

Enumerate original lines before skipping anything. Split valid lines at most once.

## Easy guidance

Keep embedded equals signs in the value. Cover an indented comment, a repeated key, and a malformed line after a skipped line.
