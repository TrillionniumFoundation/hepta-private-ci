"""Cache-duration inputs; expected decisions come from original Chrono APIs."""
from datetime_arithmetic_cases import arithmetic_cases
from duration_units_cases import duration_cases

MASK = (1 << 64) - 1
FIRST, LAST = -8334601228800, 8210266876799
MAX_DURATION_SECONDS = 9223372036854775


def cache_cases():
    cases = []
    # Preserve every std-duration constructor input from the qualified units corpus.
    for operation, seconds, nanos in duration_cases():
        if operation == 9:
            cases.append((0, 0, 0, 0, 0, seconds, nanos))
    choices = [(0, 0), (0, 1), (1, 0), (60, 1), (10800, 0),
               (MAX_DURATION_SECONDS, 807000000),
               (MAX_DURATION_SECONDS, 807000001), (MASK, 999999999)]
    index = 0
    # Preserve every original difference operand, including invalid dates and leap pairs.
    for operation, now, now_nanos, fetched, fetched_nanos, _, _ in arithmetic_cases():
        if operation == 2:
            ttl_seconds, ttl_nanos = choices[index % len(choices)]
            for policy in (1, 2):
                cases.append((policy, fetched, fetched_nanos, now, now_nanos, ttl_seconds, ttl_nanos))
            index += 1
    seconds = [FIRST, FIRST + 59, -86401, -1, 0, 58, 59, 60, 86399, 86400, LAST - 59, LAST]
    fractions = [0, 1, 999999999, 1000000000, 1500000000, 1999999999]
    for now in seconds:
        for fetched in seconds:
            for now_nanos in fractions:
                for fetched_nanos in fractions:
                    # These are test inputs around a nominal elapsed value, not expected outputs.
                    nominal = abs((now - fetched) * 1000000000 + now_nanos - fetched_nanos)
                    limits = [0, 1, 10800 * 1000000000]
                    limits += [nominal + delta for delta in [-1000000001, -1000000000, -1, 0, 1,
                                                             1000000000, 1000000001]]
                    for limit in limits:
                        if limit < 0:
                            continue
                        ttl_seconds, ttl_nanos = divmod(limit, 1000000000)
                        for policy in (1, 2):
                            cases.append((policy, fetched & MASK, fetched_nanos, now & MASK,
                                          now_nanos, ttl_seconds, ttl_nanos))
    return cases
