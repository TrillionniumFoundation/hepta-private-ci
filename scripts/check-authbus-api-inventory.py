#!/usr/bin/env python3
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
lib = (root / "codex-rs/hepta-authbus/src/lib.rs").read_text()
signed = (root / "codex-rs/hepta-authbus/src/signed.rs").read_text()
settlement = (root / "codex-rs/hepta-authbus/src/settlement.rs").read_text()
errors = []
if "pub use authority_store::AuthBusAuthorityStore" in lib:
    errors.append("raw authority writer is publicly re-exported")
if re.search(r"pub struct IssuerRegistration\\s*\\{\\s*pub ", signed):
    errors.append("IssuerRegistration trusted fields are public")
if "pub struct SettlementIssuerRegistration" in settlement:
    errors.append("settlement issuer registration is public")
for cargo in (root / "codex-rs").glob("*/Cargo.toml"):
    text = cargo.read_text()
    before_dev = text.split("[dev-dependencies]", 1)[0]
    if "codex-hepta-authbus" in before_dev and "test-support" in before_dev:
        errors.append(f"test-support enabled by production dependency: {cargo}")
if errors:
    print("\\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("auth.authbus closed-world API inventory: PASS")
