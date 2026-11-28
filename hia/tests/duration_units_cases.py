"""Unit and optional-accessor boundaries observed with original TimeDelta APIs."""
MASK = (1 << 64) - 1
MINIMUM, MAXIMUM = -(1 << 63), (1 << 63) - 1
FIRST, LAST = -9223372036854776, 9223372036854775


def duration_cases():
    cases = []
    fractions = [0, 1, 999, 1000, 999999, 1000000, 145224191, 145224192, 145224193,
                 192999999, 193000000, 193000001, 806999999, 807000000, 807000001,
                 854775806, 854775807, 854775808, 999999998, 999999999,
                 1000000000, 4294967295, 1 << 32, MASK]
    seconds = [MINIMUM, MINIMUM + 1, MAXIMUM - 1, MAXIMUM]
    for center in [FIRST, LAST, -9223372036855, 9223372036854, -9223372037, 9223372036,
                   -604800, -86400, -3600, -60, -1, 0, 1, 60, 3600, 86400, 604800]:
        seconds.extend(center + delta for delta in range(-128, 129))
    for value in seconds:
        for nanos in fractions:
            cases.append((0, value & MASK, nanos))
    state = 0x672D90A35FC841BE

    def random_word():
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) & MASK
        return state

    for _ in range(20000):
        cases.append((0, random_word(), fractions[random_word() % len(fractions)]))
        seconds = FIRST + random_word() % (LAST - FIRST + 1)
        cases.append((0, seconds & MASK, random_word() % 1000000000))
    factors = {1: 604800, 2: 86400, 3: 3600, 4: 60, 5: 1}
    for operation in range(1, 9):
        values = [MINIMUM + n for n in range(129)] + [MAXIMUM - n for n in range(129)]
        for exponent in range(64):
            for sign in [-1, 1]:
                for delta in [-2, -1, 0, 1, 2]:
                    value = sign * (1 << exponent) + delta
                    if MINIMUM <= value <= MAXIMUM:
                        values.append(value)
        if operation <= 5:
            bound = LAST // factors[operation]
            low, high = -bound, bound
        elif operation == 6:
            low, high = -MAXIMUM, MAXIMUM
        else:
            low, high = MINIMUM, MAXIMUM
        for center in [low, high, -1000000000, -1000000, -1000, -1, 0, 1, 1000, 1000000, 1000000000]:
            for delta in range(-32, 33):
                if MINIMUM <= center + delta <= MAXIMUM:
                    values.append(center + delta)
        for _ in range(20000):
            word = random_word()
            values.append(word if word < (1 << 63) else word - (1 << 64))
            values.append(low + random_word() % (high - low + 1))
        cases.extend((operation, value & MASK, 0) for value in values)
    unsigned_seconds = [0, 1, (1 << 63) - 1, 1 << 63, MASK - 1, MASK]
    unsigned_seconds.extend(LAST + delta for delta in range(-128, 129))
    for seconds in unsigned_seconds:
        for nanos in fractions:
            cases.append((9, seconds, nanos))
    for _ in range(20000):
        cases.append((9, random_word(), fractions[random_word() % len(fractions)]))
        cases.append((9, random_word() % (LAST + 1), random_word() % 1000000000))
    cases.append((10, 0, 0))
    return cases
