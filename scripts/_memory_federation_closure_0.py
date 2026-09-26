#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]

stage1_path = root / "scripts/_memory_federation_closure_1.py"
stage1 = stage1_path.read_text(encoding="utf-8")
old = '''for line in [
    "use std::error::Error as StdError;\\n",
    "use std::fmt;\\n",
    "use codex_hepta_types::AuthorityPosture;\\n",
    "use codex_hepta_types::Digest32;\\n",
    "use codex_hepta_types::StableId;\\n",
]:
    lib = lib.replace(line, "", 1)
lib = lib[:legacy_start] + '''
new = '''for line in [
    "use std::error::Error as StdError;\\n",
    "use std::fmt;\\n",
    "use codex_hepta_types::AuthorityPosture;\\n",
    "use codex_hepta_types::Digest32;\\n",
    "use codex_hepta_types::StableId;\\n",
]:
    lib = lib.replace(line, "", 1)
# Import removal changes byte offsets; resolve the extraction boundary again
# before replacing the V1 block in the crate root.
legacy_start = lib.index("#[derive(Clone, Debug, Eq, PartialEq)]\\npub struct FederatedReadRequest")
legacy_end = lib.index("#[cfg(test)]\\n#[path = \\\"lib_tests.rs\\\"]")
lib = lib[:legacy_start] + '''
if old not in stage1:
    raise RuntimeError("stage 1 legacy extraction anchor missing")
stage1 = stage1.replace(old, new, 1)
stage1 = stage1.replace(
    '    #[cfg(test)]\n    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    '    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    1,
)
stage1_path.write_text(stage1, encoding="utf-8")

print("stage 0 applied")
