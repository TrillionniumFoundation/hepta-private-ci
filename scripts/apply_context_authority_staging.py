#!/usr/bin/env python3
"""Wire the construction-closed prompt-registry context authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "codex-rs/hepta-prompt-registry/src/lib.rs"


def replace_once(old: str, new: str) -> None:
    text = LIB.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one lib.rs anchor, found {count}: {old!r}")
    LIB.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "mod admission;\nmod delivery;",
    "mod admission;\nmod context_authority;\nmod delivery;",
)
replace_once(
    "pub use admission::final_use_revoke_binding;\npub use delivery::MAX_REALIZATION_PAYLOAD_BYTES;",
    "pub use admission::final_use_revoke_binding;\n"
    "pub use context_authority::PromptContextAuthorityAdmissionV3;\n"
    "pub use context_authority::PromptContextAuthorityErrorV3;\n"
    "pub use context_authority::PromptContextAuthoritySnapshotV3;\n"
    "pub use context_authority::PromptContextAuthoritySuccessorV3;\n"
    "pub use context_authority::prompt_context_authority_verifier_digest_v3;\n"
    "pub use delivery::MAX_REALIZATION_PAYLOAD_BYTES;",
)
