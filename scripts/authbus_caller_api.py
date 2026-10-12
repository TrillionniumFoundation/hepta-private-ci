"""Reject raw operation identity in the named Bao admission source body.

This small precompile regression check only reads an explicit braced struct.
It does not resolve Rust names, imports, methods, aliases, attributes or macros.
External compiler controls and owner/runtime tests cover their concrete API
contracts; changes to authority APIs still require ordinary security review.
"""

import re

from verify_hepta_callers import _matching_delimiter
from verify_hepta_callers import _strip_rust_non_code

ADMISSION = "BaoDurableAuthBusAdmission"


def validate_bao_api(source: str) -> None:
    code = _strip_rust_non_code(source)
    declarations = list(re.finditer(rf"\bstruct\s+{ADMISSION}\s*\{{", code))
    if len(declarations) != 1:
        raise ValueError(
            f"expected one explicit braced {ADMISSION}; review changed source shape"
        )
    opening = declarations[0].end() - 1
    closing = _matching_delimiter(code, opening, "{", "}")
    if closing is None:
        raise ValueError(f"unbalanced {ADMISSION} source body")
    if re.search(r"\b(?:r#)?operation_id\s*:", code[opening + 1 : closing]):
        raise ValueError(f"{ADMISSION} cannot accept caller-supplied operation_id")
