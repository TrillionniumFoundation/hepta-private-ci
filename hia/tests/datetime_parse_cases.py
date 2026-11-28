"""Deterministic UTF-8 inputs; all semantic expectations come from original Chrono."""
from datetime import date, timedelta

MASK = (1 << 64) - 1


def parsing_cases():
    cases = []
    epoch = date(2000, 3, 1)
    fractions = ["", ".1", ".123", ".123456", ".123456789", ".123456789012"]
    offsets = ["Z", "z", "+00:00", "-00:00", "+23:59", "-23:59", "−05:30", "+05:45", "-00:30"]
    for index in range(146097):
        day = epoch + timedelta(days=index)
        seconds = (index * 7919) % 86400
        hour, rem = divmod(seconds, 3600)
        minute, second = divmod(rem, 60)
        if second == 59 and index % 7 == 0:
            second = 60
        separator = ["T", "t", " "][index % 3]
        cases.append(f"{day.year:04}-{day.month:02}-{day.day:02}{separator}{hour:02}:{minute:02}:{second:02}"
                     + fractions[index % len(fractions)] + offsets[index % len(offsets)])
    for year in [0, 1, 4, 100, 400, 1900, 1969, 1970, 1999, 2000, 2100, 2400, 9998, 9999]:
        for month in range(14):
            for day in range(33):
                cases.append(f"{year:04}-{month:02}-{day:02}T12:34:56Z")
    for hour in [*range(26), 59, 99]:
        for minute in [*range(62), 98, 99]:
            for second in [*range(62), 98, 99]:
                cases.append(f"2000-02-29T{hour:02}:{minute:02}:{second:02}.123456789Z")
    for sign in ["+", "-", "−"]:
        for hour in range(100):
            for minute in range(100):
                text = f"2000-02-29T23:59:60.123456789{sign}{hour:02}:{minute:02}"
                cases.extend([text, text + "x"])
    seeds = [
        "0000-01-01T00:00:00Z", "9999-12-31T23:59:60.999999999-23:59",
        "2000-02-29T12:34:56Z", "1900-02-29T12:34:56Z", "2100-02-29T12:34:56Z",
        "2000-01-01T24:00:00Z", "2000-01-01T00:60:00Z", "2000-01-01T00:00:61Z",
        "2000-13-01T00:00:00Z", "2000-01-32T00:00:00Z", "2000-00-00T00:00:00Z",
        "2024-01-02t03:04:05z", "2024-01-02 03:04:05+00:00",
        "2024-01-02T03:04:05.1Z", "2024-01-02T03:04:05.123456789999Z",
        "2024-01-02T03:04:60.001−05:30", "2024-01-02T03:04:05+23:59",
        "2024-01-02T03:04:05+24:00", "2024-01-02T03:04:05+99:99",
        "2024-01-02T03:04:05+24:00x", "2024-01-02T03:04:05+00:60x",
        "2024-01-02T03:04:05.Z", "2024-01-02T03:04:05.",
        "+10000-01-01T00:00:00Z", "-0001-01-01T00:00:00Z",
        "2024-01-02T03:04:05+0000", "2024-01-02T03:04:05UTC",
        " 2024-01-02T03:04:05Z ", "2024-01-02T03:04:05Z\n",
    ]
    replacements = [chr(value) for value in range(128)] + ["\u00a0", "\u2003", "−", "一", "😀", "١", "１"]
    for text in seeds:
        cases.append(text)
        cases.extend(text[:end] for end in range(len(text) + 1))
        for index in range(len(text)):
            cases.append(text[:index] + text[index + 1:])
            cases.extend(text[:index] + character + text[index + 1:] for character in replacements)
        for index in range(len(text) + 1):
            cases.extend(text[:index] + character + text[index:] for character in ["0", " ", "\t", ":", "+", "−", "."])
    for length in [*range(101), 255, 256, 1024, 4096, 65536, 1000000]:
        digits = ("0123456789" * ((length + 9) // 10))[:length]
        for time in ["23:59:59", "23:59:60", "24:99:99"]:
            for ending in ["Z", "", "+01:30", "x"]:
                cases.append(f"2000-02-29T{time}." + digits + ending)
    alphabet = "0123456789-+:TZtz. /\t\n\0" + "−\u00a0\u2003一😀١"
    state = 0x83A43CA191284E7D
    for _ in range(10000):
        state = (state * 6364136223846793005 + 1442695040888963407) & MASK
        length = state % 80
        value = []
        for _ in range(length):
            state = (state * 6364136223846793005 + 1442695040888963407) & MASK
            value.append(alphabet[state % len(alphabet)])
        cases.append("".join(value))
    return [text.encode("utf-8") for text in cases]
