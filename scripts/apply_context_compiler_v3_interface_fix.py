#!/usr/bin/env python3
"""Close V2-to-V3 interface mismatches without exposing authority internals."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one interface anchor, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    #[must_use]\n"
    "    pub const fn portfolio_valid_until_unix_ms(&self) -> u64 {\n"
    "        self.portfolio_valid_until_unix_ms\n"
    "    }\n",
    "    #[must_use]\n"
    "    pub const fn portfolio_valid_until_unix_ms(&self) -> u64 {\n"
    "        self.portfolio_valid_until_unix_ms\n"
    "    }\n\n"
    "    /// Observation time of the verified registry-owned authority snapshot.\n"
    "    /// Exposes only the monotonic clock fence required by the runtime owner;\n"
    "    /// callers cannot issue admissions or reconstruct the opaque snapshot.\n"
    "    #[must_use]\n"
    "    pub fn authority_observed_unix_ms(&self) -> u64 {\n"
    "        self.verified_snapshot.observed_unix_ms()\n"
    "    }\n",
)

replace_once(
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "        if now_unix_ms < compiled.admission_snapshot.observed_unix_ms() {",
    "        if now_unix_ms < compiled.authority_observed_unix_ms() {",
)
