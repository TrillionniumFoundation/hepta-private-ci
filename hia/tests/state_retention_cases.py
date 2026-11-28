"""Complete existing date and day/hour constructor inputs at retention callers."""
from duration_units_cases import duration_cases
from test_datetime_calendar import constructor_cases

MASK = (1 << 64) - 1
FIRST, LAST = -8334601228800, 8210266876799


def retention_cases():
    # Preserve every raw original date input at all four actual call sites.
    # The observer records unrepresentable dates without inventing a DateTime.
    for seconds, nanos in constructor_cases():
        for operation in range(4):
            yield operation, seconds & MASK, nanos, 10, 12
    # Each original day/hour constructor input is retained, including values
    # that the production max(0) clamps and values that panic before a date
    # subtraction. Both date limits, negative leap seconds and the epoch run.
    contexts = [(FIRST, 0), (-86401, 1999999999), (0, 0), (LAST, 1999999999)]
    for operation, amount, nanos in duration_cases():
        if operation not in (2, 3):
            continue
        assert nanos == 0
        for seconds, fraction in contexts:
            if operation == 2:
                for caller in (1, 2, 3):
                    yield caller, seconds & MASK, fraction, amount, 12
            else:
                yield 1, seconds & MASK, fraction, 0, amount
