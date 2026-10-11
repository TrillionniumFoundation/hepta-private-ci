"""Strict provenance-time comparator for registered native research inputs.

Do not use lexicographic comparison of human-readable session dates. Reject
unknown or mixed-precision formats rather than inventing a chronology.
Observed time equality is coeval in the registered benchmark, not a verified
per-message ordering. This parser does not authorize evidence by itself.
"""

from datetime import datetime, timezone
import re


def _parse_observation(value):
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 128:
        raise ValueError("bounded observation timestamp string required")
    if re.fullmatch(r"\d{4}", value):
        return datetime.strptime(value, "%Y"), "year", False
    if re.fullmatch(r"\d{4}(?:-\d{2}-\d{2}|/\d{2}/\d{2})", value):
        normalized = value.replace("/", "-")
        return datetime.strptime(normalized, "%Y-%m-%d"), "day", False
    if re.fullmatch(r"\d{1,2}:\d{2} [aApP][mM] on \d{1,2} [A-Za-z]+, \d{4}", value):
        for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
            try:
                return datetime.strptime(value, fmt), "minute", False
            except ValueError:
                pass
        raise ValueError("invalid native LoCoMo timestamp")
    # Pinned LongMemEval native chronology: YYYY/MM/DD (Ddd) HH:MM.
    # The weekday is evidence provenance metadata; validate it rather than
    # silently accepting a contradictory day label.
    native = re.fullmatch(
        r"(\d{4})/(\d{2})/(\d{2}) "
        r"\((Mon|Tue|Wed|Thu|Fri|Sat|Sun)\) (\d{2}):(\d{2})",
        value,
    )
    if native:
        year, month, day, weekday, hour, minute = native.groups()
        parsed = datetime(int(year), int(month), int(day), int(hour), int(minute))
        if ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[
            parsed.weekday()
        ] != weekday:
            raise ValueError("LongMemEval weekday/date mismatch")
        return parsed, "minute", False
    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
        r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?",
        value,
    )
    if match:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        aware = timestamp.utcoffset() is not None
        precision = "second" if re.search(r"\d{2}:\d{2}:\d{2}", value) else "minute"
        if aware:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp, precision, aware
    raise ValueError("unsupported observation timestamp grammar")


def source_not_after_question(source_observed_at, question_observed_at):
    """Fail closed when date formats are incomparable; do not truncate times."""
    source, precision, aware = _parse_observation(source_observed_at)
    question, target_precision, target_aware = _parse_observation(question_observed_at)
    if precision != target_precision or aware != target_aware:
        raise ValueError("incomparable observation precision or timezone")
    return source <= question
