"""Run a synthetic installed-runtime demonstration, never send model requests."""
from decimal import Decimal
from scriptspell import profile, run

if __name__ == '__main__':
    result = run('def transform(inputs):\n    return {"out": inputs["number"]}',
                 {'number': Decimal('1.20')}, ['out'])
    print(profile())
    print(result['outcome'])
    assert result.get('values', {}).get('out').as_tuple() == Decimal('1.20').as_tuple()
