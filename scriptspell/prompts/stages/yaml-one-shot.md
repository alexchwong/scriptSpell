Return exactly one valid YAML document with exactly three top-level keys: interface, examples, and source.

${contract}

The illustration above shows the data sections. Add the required source key.
Put Python defining transform(inputs) under source as a YAML literal block (source: |).
The function receives an input dictionary keyed by the declared input names and returns a dictionary keyed by the declared output names. The YAML lists of single-entry mappings are only the document representation. Implement the general task. Do not hard-code the examples. Return lists for output sequences.

${monty}
Language profile: ${language}
