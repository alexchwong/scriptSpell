Example interface and examples for doubling an integer with two requested pairs:

interface:
  inputs:
    number: int
  outputs:
    result: int
examples:
  - inputs:
      number: 3
    # 3 doubled is 3 + 3 = 6.
    outputs:
      result: 6
  - inputs:
      number: -2
    # -2 doubled is -2 + -2 = -4.
    outputs:
      result: -4
