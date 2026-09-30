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
                # An unparsable item is retained, so it cannot hide a write.
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
    # Raw identifiers name the same Rust symbol. Normalize only after cfg item
    # removal, which depends on the original source offsets.
    code = re.sub(r"\br#(?=[A-Za-z_])", "", code)
    findings = []
    for variant in ("Decision", "Outcome", "Credit", "Revocation"):
        pattern = rf"\bLedgerEvent\s*::\s*{variant}\b"
        for match in re.finditer(pattern, code):
            cursor = _skip_space(code, match.end())
            end = _matching_delimiter(code, cursor, "(", ")")
            # Exhaustive read-only match arms decode historical events without
            # constructing or appending a legacy learning fact.
            if end is not None and code[_skip_space(code, end + 1) :].startswith("=>"):
                continue
            findings.append(f"raw V1 {variant} construction")
            break
    for match in re.finditer(r"\bLedgerEvent\s*::\s*\{", code):
        end = _matching_delimiter(code, match.end() - 1, "{", "}")
        imported = code[match.end() : end] if end is not None else code[match.end() :]
        # Importing a constructor makes later unqualified calls ambiguous.
        # Keep simple LedgerEvent type imports for historical inspection.
        if any(
            re.search(rf"\b{variant}\b", imported)
            for variant in ("Decision", "Outcome", "Credit", "Revocation")
        ) or re.search(r"\*|\bself\s+as\b", imported):
            findings.append("ambiguous raw V1 event import")
            break
    if re.search(r"\bLedgerEvent\s*::\s*\*|\bLedgerEvent\s+as\b", code) or any(
        "=" in match.group() and re.search(r"\bLedgerEvent\b", match.group())
        for match in re.finditer(r"\btype\b[^;]*;", code)
    ):
        findings.append("ambiguous raw V1 event alias")
    if re.search(r"\bDurableLearningJournal\s+as\b", code) or any(
        "=" in match.group() and re.search(r"\bDurableLearningJournal\b", match.group())
        for match in re.finditer(r"\b(?:type|trait)\b[^;{}]*;", code)
    ):
        findings.append("ambiguous legacy durable journal alias")
    ledger_namespace_alias = re.search(r"\bcodex_hepta_learning_ledger\s+as\b", code)
    ledger_glob = False
    for match in re.finditer(r"\bcodex_hepta_learning_ledger\s*::\s*([*{])", code):
        if match.group(1) == "*":
            ledger_glob = True
            break
        end = _matching_delimiter(code, match.end() - 1, "{", "}")
        imported = code[match.end() : end] if end is not None else code[match.end() :]
        if "*" in imported:
            ledger_glob = True
            break
    if ledger_namespace_alias or ledger_glob:
        # A wildcard or renamed crate can bring the legacy trait into method
        # scope without its name appearing next to append_decision.
        findings.append("ambiguous learning ledger namespace")
    for pattern, description in (
        (r"\bappend_qualification\b", "raw qualification append"),
        (
            r"\bDurableLearningJournal\s*>?\s*::\s*append_decision\b",
            "legacy durable journal append",
        ),
    ):
        if re.search(pattern, code):
            findings.append(description)
    if (
        "legacy durable journal append" not in findings
        and "ambiguous legacy durable journal alias" not in findings
        and re.search(r"\bDurableLearningJournal\b", code)
        and re.search(r"\bappend_decision\b", code)
    ):
        # A generic/trait-object receiver can call this method without naming
        # the trait at the callsite. Lexical analysis cannot prove it belongs
        # to a sealed LedgerWriter instead, so keep the mixed file in scope.
        findings.append("ambiguous legacy durable journal write")
    return findings
