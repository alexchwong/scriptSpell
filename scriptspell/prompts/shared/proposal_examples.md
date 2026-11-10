Complete proposal examples:
[
  {
    "source": "def transform(inputs):\n    return {\"out\": inputs[\"text\"].strip()}",
    "summary": "Trim whitespace.",
    "assumptions": [],
    "unmet_requirements": [],
    "example_input": {
      "text": " example "
    },
    "expected_output": {
      "out": "example"
    }
  },
  {
    "source": "def transform(inputs):\n    return {\"out\": [x for x in inputs[\"items\"] if x]}",
    "summary": "Discard empty strings.",
    "assumptions": [],
    "unmet_requirements": [],
    "example_input": {
      "items": [
        "",
        "a",
        "b"
      ]
    },
    "expected_output": {
      "out": [
        "a",
        "b"
      ]
    }
  },
  {
    "source": "from decimal import Decimal\ndef transform(inputs):\n    return {\"out\": Decimal(inputs[\"vaf_text\"]) >= Decimal(\"0.05\")}",
    "summary": "Apply an exact threshold.",
    "assumptions": [],
    "unmet_requirements": [],
    "example_input": {
      "vaf_text": "0.05"
    },
    "expected_output": {
      "out": true
    }
  }
]
