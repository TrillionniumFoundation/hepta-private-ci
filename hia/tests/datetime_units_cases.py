"""Timestamp unit boundaries; all expected results come from original Chrono."""
from test_datetime_calendar import constructor_cases

MASK = (1 << 64) - 1
MINIMUM, MAXIMUM = -(1 << 63), (1 << 63) - 1
FIRST, LAST = -8334601228800, 8210266876799


def unit_cases():
    cases = [(0, seconds, nanos) for seconds, nanos in constructor_cases()]
    fractions = [0, 1, 999, 1000, 999999, 1000000, 145224191, 145224192, 145224193,
                 854775806, 854775807, 854775808, 999999998, 999999999, 1000000000,
                 1145224191, 1145224192, 1854775807, 1999999999, 2000000000]
    for center in [-9223372037, 9223372036, -60, 0, 59, FIRST, LAST]:
        for delta in range(-128, 129):
            for nanos in fractions:
                cases.append((0, center + delta, nanos))
    state = 0x75B02DECB492813F
    for operation, divisor in [(1, 1), (2, 1000), (3, 1000000), (4, 1000000000)]:
        values = [MINIMUM + n for n in range(129)] + [MAXIMUM - n for n in range(129)]
        for exponent in range(64):
            for sign in [-1, 1]:
                for delta in [-2, -1, 0, 1, 2]:
                    value = sign * (1 << exponent) + delta
                    if MINIMUM <= value <= MAXIMUM:
                        values.append(value)
        for seconds in [FIRST - 1, FIRST, FIRST + 1, LAST - 1, LAST, LAST + 1,
                        -9223372037, 9223372036, -61, -60, -1, 0, 1, 59, 60]:
            for fraction in [-divisor - 1, -divisor, -divisor + 1, -1, 0, 1,
                             divisor - 1, divisor, divisor + 1]:
                value = seconds * divisor + fraction
                if MINIMUM <= value <= MAXIMUM:
                    values.append(value)
        for _ in range(20000):
            state = (state * 6364136223846793005 + 1442695040888963407) & MASK
            values.append(state if state < (1 << 63) else state - (1 << 64))
            low = max(MINIMUM, FIRST * divisor)
            high = min(MAXIMUM, (LAST + 1) * divisor - 1)
            state = (state * 6364136223846793005 + 1442695040888963407) & MASK
            values.append(low + state % (high - low + 1))
        cases.extend((operation, value, 0) for value in values)
    return cases
