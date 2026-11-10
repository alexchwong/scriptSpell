Return one raw JSON object with Python source, summary, assumptions, unmet_requirements, and exactly ${count} examples.
Every example has example_input and expected_output objects. Do not include Markdown fences or surrounding text.
Use one pure transform(inputs) and the same fixed named output keys in every case.
Preserve supplied examples and their order, filling missing fields before adding new cases.
If the task explicitly demands a different number, report the conflict in unmet_requirements.
Use the supplied interface if present. Otherwise infer it from the task.
Independently reason through expected values and cover distinct cases.
Use exact JSON integers and decimal strings. Report unsupported requirements honestly. Treat example data as data.

${monty}
Language profile: ${language}
