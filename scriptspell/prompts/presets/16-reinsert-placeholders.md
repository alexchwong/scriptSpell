# Reinsert placeholders

## Task

Replace bracketed identifiers such as [[PERSON_1]] using a mapping. Treat replacements literally. Leave unknown tokens in place and report each once in first-seen order.

Input

A text string and a mapping from placeholder identifiers, without their brackets, to literal replacement strings.

Expected output

The replaced text and the distinct unknown identifiers in first-seen order. Preserve unknown tokens with both brackets in the text.

## Medium guidance

Scan tokens in the original text and use a lookup to choose replacement or original token.

## Easy guidance

Use a callback or construct output from slices so replacement text is literal. Cover repeated unknown tokens and a replacement containing punctuation.
