"""Versioned public fitting and selection, with declared reused development rows."""

from pathlib import Path
import re
import sys

from addressing.contracts import normalize
from .public_language import TRAIN_POSITIVE, SELECTION_POSITIVE, TRAIN_NEGATIVE, SELECTION_NEGATIVE


def public_rows():
    qualification = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(qualification / "memory-cell-v8/addressing"))
    from v8_addressing.public_corpus import public_rows as previous_public_rows
    previous = previous_public_rows()
    rows = {"train": [{**row, "provenance": "reused disclosed V7/V8 development data; never old calibration or held"}
                       for split in ("train", "selection") for row in previous[split]], "selection": []}
    seen = {normalize(row["text"]) for row in rows["train"]}

    def add(split, label, language, index, phrase, group):
        phrase = re.sub(r"(?<![a-z])(?:entity|date)(?![a-z])", lambda match: " " + match.group() + " ", normalize(phrase))
        phrase = " ".join(phrase.split())
        if normalize(phrase) in seen:
            raise ValueError("public V9 development text overlaps a prior public row")
        seen.add(normalize(phrase))
        row = {"id": f"v9-public-{split}-{group}-{label}-{language}-{index}",
               "family": f"v9-public-{split}-{group}-{label}-{index}", "language": language,
               "operation": label, "text": phrase, "provenance": "disclosed V9 development language; not independent evaluation"}
        if label == "reject":
            row["negative_group"] = group
        rows[split].append(row)

    for label, languages in TRAIN_POSITIVE.items():
        for language, phrases in languages.items():
            for index, phrase in enumerate(phrases):
                add("train", label, language, index, phrase, "supported")
    for label, phrases in SELECTION_POSITIVE.items():
        for index, phrase in enumerate(phrases):
            add("selection", label, "en" if index < 4 else "zh", index, phrase, "supported")
    for group, phrases in TRAIN_NEGATIVE.items():
        for index, phrase in enumerate(phrases):
            add("train", "reject", "en" if index < 6 else "zh", index, phrase, group)
    for index, phrase in enumerate(SELECTION_NEGATIVE):
        add("selection", "reject", "en" if index < 32 else "zh", index, phrase, "near-contract")
    return rows
