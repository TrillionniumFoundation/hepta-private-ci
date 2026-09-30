"""Detect legacy learning writes while preserving read-only journal inspection.

This is a conservative source guard, not a Rust type checker. Exact, explicit
qualification-only items are excluded; unknown or negated cfg expressions stay
in scope. Compilation remains responsible for enforcing the sealed owner API.
"""

import re

from verify_hepta_callers import _matching_delimiter
from verify_hepta_callers import _rust_item_end
from verify_hepta_callers import _skip_space
from verify_hepta_callers import _strip_rust_non_code


def _product_code(source: str) -> str:
    code = _strip_rust_non_code(source)
    output = list(code)
    index = 0
    while index < len(code):
        start = code.find("#[", index)
        if start < 0:
            break
        end = _matching_delimiter(code, start + 1, "[", "]")
        if end is None:
            break
        attribute = source[start : end + 1]
        exact_qualification = re.fullmatch(
            r'#\[\s*cfg\s*\(\s*feature\s*=\s*"qualification-legacy-learning-write"\s*\)\s*\]',
            attribute,
        )
        exact_test = re.fullmatch(r"#\[\s*cfg\s*\(\s*test\s*\)\s*\]", attribute)
        if not (exact_qualification or exact_test):
            index = end + 1
            continue
        cursor = _skip_space(code, end + 1)
        while code.startswith("#[", cursor):
            extra_end = _matching_delimiter(code, cursor + 1, "[", "]")
            if extra_end is None:
                # An unparseable item is retained, so it cannot hide a write.
                return "".join(output)
            cursor = _skip_space(code, extra_end + 1)
        item_end = _rust_item_end(code, cursor)
        if item_end is None:
            index = end + 1
            continue
        for offset in range(start, item_end + 1):
            if output[offset] != "\n":
                output[offset] = " "
        index = item_end + 1
    return "".join(output)


def legacy_write_findings(source: str) -> list[str]:
    code = _product_code(source)
    findings = []
    for variant in ("Decision", "Outcome", "Credit", "Revocation"):
        pattern = rf"\bLedgerEvent\s*::\s*{variant}\s*\("
        for match in re.finditer(pattern, code):
            end = _matching_delimiter(code, match.end() - 1, "(", ")")
            # Exhaustive read-only match arms decode historical events without
            # constructing or appending a legacy learning fact.
            if end is not None and code[_skip_space(code, end + 1) :].startswith("=>"):
                continue
            findings.append(f"raw V1 {variant} construction")
            break
    for pattern, description in (
        (r"\bappend_qualification\s*\(", "raw qualification append"),
        (
            r"\bDurableLearningJournal\s*::\s*append_decision\s*\(",
            "legacy durable journal append",
        ),
    ):
        if re.search(pattern, code):
            findings.append(description)
    return findings
