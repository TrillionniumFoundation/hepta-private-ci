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
stage1 = stage1.replace(
    '    #[cfg(test)]\n    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    '    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn sign_with_nonce(',
    1,
)
stage1_path.write_text(stage1, encoding="utf-8")

stage2_path = root / "scripts/_memory_federation_closure_2.py"
stage2 = stage2_path.read_text(encoding="utf-8")
ambiguous = '''observation = replace_exact(
    observation,
    "    channels: Vec<RetrievalChannelObservation>,\\n",
    "    pub(super) channels: Vec<RetrievalChannelObservation>,\\n",
)'''
scoped = '''observation = replace_exact(
    observation,
    """pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    channels: Vec<RetrievalChannelObservation>,
}
""",
    """pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    pub(super) channels: Vec<RetrievalChannelObservation>,
}
""",
)'''
if scoped not in stage2:
    if ambiguous not in stage2:
        raise RuntimeError("stage 2 retrieval visibility anchor missing")
    stage2 = stage2.replace(ambiguous, scoped, 1)
stage2_path.write_text(stage2, encoding="utf-8")

print("stage 0 applied")
