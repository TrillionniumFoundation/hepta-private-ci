"""Valid UTF-8 inputs; semantic expectations always come from original Chrono."""
from datetime_parse_cases import parsing_cases

MASK = (1 << 64) - 1
WHITESPACE = [*range(9, 14), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
              0x2028, 0x2029, 0x202F, 0x205F, 0x3000]


def relaxed_cases():
    # Keep every previously qualified strict input, including the whole 400-year
    # Gregorian cycle, malformed fields, Unicode mutations and million-digit fractions.
    for payload in parsing_cases():
        yield 0, payload
    seeds = [
        "1-1-1T1:1:1Z", "0001-01-01t01:01:01z", "+1-1-1 1:1:1UTC",
        "-0001-1-1T1:1:1utc", "+10000-12-31T23:59:60.123456789+0000",
        "2000-2-29T3:4:5+00::00", "2000-2-30T3:4:5Z",
        "2000-1-1T24:0:0.Z", "2000-1-1T0:60:0x", "2000-1-1T0:0:61x",
        "2000-13-1T0:0:0x", "2000-1-32T0:0:0x", "2000-0-0T0:0:0x",
        "2000-1-1T0:0:0+99::00x", "2000-1-1T0:0:0+00::60x",
        "-262143-1-1T0:0:0+00:01", "+262142-12-31T23:59:59-00:01",
    ]
    spaces = [chr(value) for value in WHITESPACE]
    nonspaces = ["\0", "\x1c", "\x1d", "\x1e", "\x1f", "\u180e", "\u200b", "\ufeff", "😀"]
    for text in seeds:
        yield 0, text.encode()
        for character in spaces + nonspaces:
            for position in range(len(text) + 1):
                yield 0, (text[:position] + character + text[position:]).encode()
    for first in spaces:
        for second in spaces:
            for separator in [first + second, first + ":" + second, ":" + first + "::" + second]:
                yield 0, ("2000-01-02T03:04:05+05" + separator + "30").encode()
    years = ["", "0", "00", "000", "0000", "00000", "1", "12", "123", "1234", "12345",
             "+0", "-0", "+1", "-1", "+00001", "-00001", "+10000", "-10000",
             "+262142", "+262143", "-262143", "-262144", "2147483647", "-2147483648",
             "+2147483647", "+2147483648", "-2147483649", "+9223372036854775807",
             "+9223372036854775808", "-9223372036854775807", "-9223372036854775808",
             "+18446744073709551615", "−1", "+ 1", "-\t1"]
    for year in years:
        for rest in ["-1-1T0:0:0Z", "-2-29T23:59:60.123456789UTC", "-2-30T0:0:0Z",
                     "-13-32T24:60:61.x", "-1-1T0:0:0+24:00", "-1-1T0:0:0+00:60"]:
            for ending in ["", "x", " ", "\u3000"]:
                yield 0, (year + rest + ending).encode()
    for zeros in [1, 4, 5, 19, 20, 100, 1024, 65536, 1000000]:
        for sign in ["+", "-"]:
            for ending in ["1-1-1T0:0:0Z", "9223372036854775807-1-1T0:0:0Z",
                           "9223372036854775808-1-1T0:0:0Z"]:
                yield 0, (sign + "0" * zeros + ending).encode()
    for year, month, day, time in [(-262143, 1, 1, "0:0:0"), (-262143, 1, 1, "0:0:60.1"),
                                  (262142, 12, 31, "23:59:59.999999999"),
                                  (262142, 12, 31, "23:59:60.999999999")]:
        for sign in ["+", "-", "−"]:
            for hour in [0, 1, 23, 24, 99]:
                for minute in [0, 1, 59, 60, 99]:
                    for tail in ["", "x", "\u2003"]:
                        yield 0, f"{year:+}-{month}-{day}T{time}{sign}{hour:02}::{minute:02}{tail}".encode()
    state = 0x8DEAC728AB3CE15D
    for _ in range(20000):
        values = []
        for _ in range(8):
            state = (state * 6364136223846793005 + 1442695040888963407) & MASK
            values.append(state)
        year = int(values[0] % 524290) - 262145
        month, day, hour, minute, second = [value % limit for value, limit in
                                           zip(values[1:6], [14, 33, 26, 62, 62])]
        fraction = ["", ".1", ".001", ".123456789987", ".x"][values[6] % 5]
        zone = ["Z", "UTC", "+0530", "−00 \t:30", "+24:00", "x"][values[7] % 6]
        yield 0, f"{year:+}-{month}-{day}T{hour}:{minute}:{second}{fraction}{zone}".encode()
    # Observe the actual Rust parser for every valid scalar. This catches both
    # missing Unicode whitespace and accidental trimming of non-whitespace.
    tail = b"2000-01-02T03:04:05Z"
    for scalar in range(0x110000):
        if not 0xD800 <= scalar <= 0xDFFF:
            yield 1, chr(scalar).encode() + tail


def batches():
    batch, size = [], 0
    for coverage, payload in relaxed_cases():
        if batch and (len(batch) >= 4096 or size + 16 + len(payload) > 1024 * 1024):
            yield batch
            batch, size = [], 0
        batch.append((coverage, payload))
        size += 16 + len(payload)
    if batch:
        yield batch
