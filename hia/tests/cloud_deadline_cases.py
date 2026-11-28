"""Complete existing date/std-duration inputs for the actual cloud deadline caller."""
from duration_units_cases import duration_cases
from test_datetime_calendar import constructor_cases

MASK = (1 << 64) - 1
FIRST, LAST = -8334601228800, 8210266876799


def deadline_cases():
    # Keep every original calendar input, including inputs outside DateTime's
    # typed domain. The Rust observer records those without constructing a fake
    # DateTime. All representable inputs execute both real calculation fragments.
    cases = [(0, seconds & MASK, nanos, 3600, 0)
             for seconds, nanos in constructor_cases()]
    for center in [FIRST, FIRST + 59, -3601, -1, 0, 59, LAST - 3600, LAST]:
        for delta in range(-3, 4):
            for nanos in [0, 1, 999999999, 1000000000, 1999999999]:
                cases.append((0, (center + delta) & MASK, nanos, 3600, 0))
    contexts = [(FIRST, 0), (FIRST + 59, 1500000000), (-86401, 1999999999),
                (0, 0), (59, 1000000000), (59, 1999999999),
                (LAST - 3600, 999999999), (LAST, 1999999999)]
    for operation, seconds, nanos in duration_cases():
        if operation == 9:
            for timestamp, fraction in contexts:
                cases.append((1, timestamp & MASK, fraction, seconds, nanos))
    return cases
