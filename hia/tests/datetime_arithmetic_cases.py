"""Date arithmetic inputs; expected values are produced only by original Chrono."""
from test_datetime_calendar import constructor_cases

MASK = (1 << 64) - 1
FIRST, LAST = -8334601228800, 8210266876799
DELTA_FIRST, DELTA_LAST = -9223372036854776, 9223372036854775


def arithmetic_cases():
    cases = []

    def arithmetic(operation, seconds, nanos, other_seconds, other_nanos):
        cases.append((operation, seconds & MASK, nanos, other_seconds & MASK, other_nanos, 0, 0))

    # Preserve every constructor operand in each of the three DateTime operations.
    for seconds, nanos in constructor_cases():
        for operation in range(3):
            arithmetic(operation, seconds, nanos, 0, 0)
    # Enumerate every date of a full Gregorian cycle, including all invalid day 29..31 slots.
    for year in range(400):
        for month in range(1, 13):
            for day in range(1, 32):
                index = year * 372 + (month - 1) * 31 + day - 1
                cases.append((3, year, month, day, index % 24, index * 17 % 60, index * 43 % 60))
    fractions = [0, 1, 999999, 1000000, 499999999, 500000000, 999999998, 999999999,
                 1000000000, 1000000001, 1499999999, 1500000000, 1999999998, 1999999999,
                 2000000000, 4294967295, 1 << 32, MASK]
    delta_fractions = [0, 1, 999999, 1000000, 192999999, 193000000, 193000001,
                       499999999, 500000000, 806999999, 807000000, 807000001,
                       999999998, 999999999, 1000000000, 4294967295, 1 << 32, MASK]
    # Escape/stay/carry/borrow at leap seconds, minute/day edges, and calendar endpoints.
    for seconds in [FIRST, FIRST + 59, -86401, -86400, -61, -60, -1, 0, 58, 59, 60,
                    119, 120, 86398, 86399, 86400, 86459, LAST - 60, LAST - 1, LAST]:
        for nanos in fractions:
            for delta_seconds in [-86401, -86400, -61, -60, -2, -1, 0, 1, 2, 59, 60, 86400, 86401]:
                for delta_nanos in [0, 1, 499999999, 500000000, 999999998, 999999999]:
                    for operation in (0, 1):
                        arithmetic(operation, seconds, nanos, delta_seconds, delta_nanos)
    # TimeDelta::new's asymmetric canonical endpoints and wider-ABI argument rejection.
    for seconds in [FIRST, FIRST + 59, -61, -1, 0, 59, LAST - 60, LAST]:
        for nanos in [0, 999999999, 1000000000, 1999999999]:
            for delta_seconds in [-(1 << 63), DELTA_FIRST - 1, DELTA_FIRST, DELTA_FIRST + 1,
                                  -1, 0, 1, DELTA_LAST - 1, DELTA_LAST, DELTA_LAST + 1, (1 << 63) - 1]:
                for delta_nanos in delta_fractions:
                    for operation in (0, 1):
                        arithmetic(operation, seconds, nanos, delta_seconds, delta_nanos)
    # Original difference leap adjustment depends on seconds within the day, even across days.
    seconds_in_day = [0, 58, 59, 60, 119, 120, 86398, 86399]
    for left_day, right_day in [(-2, -2), (-2, -1), (-1, -2), (0, 0), (0, 1), (1, 0),
                                (FIRST // 86400, LAST // 86400), (LAST // 86400, FIRST // 86400)]:
        for left_second in seconds_in_day:
            for right_second in seconds_in_day:
                for left_nanos in [0, 1, 999999999, 1000000000, 1500000000, 1999999999]:
                    for right_nanos in [0, 1, 999999999, 1000000000, 1500000000, 1999999999]:
                        arithmetic(2, left_day * 86400 + left_second, left_nanos,
                                   right_day * 86400 + right_second, right_nanos)
    years = [-(1 << 63), -(1 << 31) - 1, -(1 << 31), -262144, -262143, -262142,
             -400, -100, -4, -1, 0, 1, 4, 100, 400, 1900, 2000, 2100,
             262141, 262142, 262143, (1 << 31) - 1, 1 << 31, (1 << 63) - 1]
    for year in years:
        for month in [0, 1, 2, 4, 12, 13, 4294967295, 1 << 32, MASK]:
            for day in [0, 1, 28, 29, 30, 31, 32, 4294967295, 1 << 32, MASK]:
                cases.append((3, year & MASK, month, day, 0, 0, 0))
    for position, maximum in [(4, 24), (5, 60), (6, 60)]:
        for value in list(range(maximum + 2)) + [4294967295, 1 << 32, MASK]:
            row = [3, 2000, 2, 29, 23, 59, 59]
            row[position] = value
            cases.append(tuple(row))
    state = 0x39A7164CD258E0BF

    def random_word():
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) & MASK
        return state

    # Full-range operand pairs plus ordinary and invalid fractions; small and extreme durations.
    for _ in range(20000):
        left = FIRST + random_word() % (LAST - FIRST + 1)
        right = FIRST + random_word() % (LAST - FIRST + 1)
        left_nanos = fractions[random_word() % len(fractions)]
        right_nanos = fractions[random_word() % len(fractions)]
        arithmetic(2, left, left_nanos, right, right_nanos)
        delta = random_word() % 172801 - 86400
        delta_nanos = random_word() % 1000000000
        for operation in (0, 1):
            arithmetic(operation, left, left_nanos, delta, delta_nanos)
        wide_delta = random_word()
        for operation in (0, 1):
            arithmetic(operation, left, left_nanos, wide_delta, delta_fractions[random_word() % len(delta_fractions)])
        cases.append((3, (random_word() % 524290 - 262145) & MASK,
                      random_word() % 15, random_word() % 34, random_word() % 26,
                      random_word() % 62, random_word() % 62))
    return cases
