#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
stage1_path = root / "scripts/_memory_federation_closure_1.py"
stage1 = stage1_path.read_text(encoding="utf-8")

splice = 'lib = lib[:legacy_start] + """#[cfg(feature = "legacy-v1")]'
recomputed_splice = '''# Removing imports changes byte offsets. Resolve both boundaries immediately
# before replacing the legacy block, rather than carrying stale offsets from
# the earlier extraction used to create legacy_v1.rs.
legacy_start = lib.index(
    "#[derive(Clone, Debug, Eq, PartialEq)]\\npub struct FederatedReadRequest"
)
legacy_end = lib.index("#[cfg(test)]\\n#[path = \\\"lib_tests.rs\\\"]")
lib = lib[:legacy_start] + """#[cfg(feature = "legacy-v1")]'''

if recomputed_splice not in stage1:
    if splice not in stage1:
        raise RuntimeError("stage 1 legacy splice anchor missing")
    stage1 = stage1.replace(splice, recomputed_splice, 1)

# Deterministic non-random signing is crate-private test support. Keeping it
# available while the feature tests compile avoids making its visibility
# depend on the nested module's cfg expansion order.
stage1 = stage1.replace(
    '    #[cfg(test)]\n    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    '    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    1,
)

stage1_path.write_text(stage1, encoding="utf-8")
print("stage 0 applied")
