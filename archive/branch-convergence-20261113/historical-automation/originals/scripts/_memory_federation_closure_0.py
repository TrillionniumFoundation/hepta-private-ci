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
manifest_anchor = '    "codex-hepta-types = { workspace = true }\\n",'
manifest_path_anchor = '    \'codex-hepta-types = { path = "../hepta-types" }\\n\','
if manifest_path_anchor not in stage1:
    if manifest_anchor not in stage1:
        raise RuntimeError("stage 1 memory-federation manifest anchor missing")
    stage1 = stage1.replace(manifest_anchor, manifest_path_anchor, 1)
manifest_payload = '    """codex-hepta-types = { workspace = true }\n'
manifest_path_payload = '    """codex-hepta-types = { path = "../hepta-types" }\n'
if manifest_path_payload not in stage1:
    if manifest_payload not in stage1:
        raise RuntimeError("stage 1 memory-federation dependency payload missing")
    stage1 = stage1.replace(manifest_payload, manifest_path_payload, 1)
legacy_test_anchor = 'write("codex-rs/hepta-memory-federation/src/legacy_v1.rs", legacy_source)'
legacy_test_patch = r'''write("codex-rs/hepta-memory-federation/src/legacy_v1.rs", legacy_source)
legacy_tests_rel = "codex-rs/hepta-memory-federation/src/lib_tests.rs"
legacy_tests = read(legacy_tests_rel)
legacy_tests = legacy_tests.replace(
    "use super::*;\n",
    "use super::*;\nuse codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n",
    1,
)
write(legacy_tests_rel, legacy_tests)'''
if legacy_test_patch not in stage1:
    if legacy_test_anchor not in stage1:
        raise RuntimeError("stage 1 legacy test anchor missing")
    stage1 = stage1.replace(legacy_test_anchor, legacy_test_patch, 1)
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

strict_literal_match = '''            if match is None:
                raise RuntimeError(f"{struct_name} literal has no {before_field}")'''
scoped_literal_match = '''            if match is None:
                cursor = end + 1
                continue'''
if scoped_literal_match not in stage2:
    if strict_literal_match not in stage2:
        raise RuntimeError("stage 2 response literal matcher anchor missing")
    stage2 = stage2.replace(strict_literal_match, scoped_literal_match, 1)

colon_call = '''    "RemoteFederatedResponseV2",
    "completeness:",
    "omitted_items,",
)'''
shorthand_call = '''    "RemoteFederatedResponseV2",
    "completeness,",
    "omitted_items,",
)'''
if shorthand_call not in stage2:
    if colon_call not in stage2:
        raise RuntimeError("stage 2 response completeness anchor missing")
    stage2 = stage2.replace(colon_call, shorthand_call, 1)

attempt_patches = [
    (
        "    let attempts = stream::iter(readers.iter())\n",
        "    let attempts = stream::iter(readers.into_iter())\n",
    ),
    (
        """            let (query, lease) = build_product_query_and_lease(
                reader,
""",
        """            let (query, lease) = build_product_query_and_lease(
                &reader,
""",
    ),
    (
        """            let transport = ProductReaderTransport {
                reader,
""",
        """            let transport = ProductReaderTransport {
                reader: &reader,
""",
    ),
    (
        """            let authority = ProductReaderAuthority {
                owner_layout,
""",
        """            let authority = ProductReaderAuthority {
                owner_layout: &owner_layout,
""",
    ),
]
for old, new in attempt_patches:
    if new not in stage2:
        if old not in stage2:
            raise RuntimeError(f"stage 2 owned attempt anchor missing: {old!r}")
        stage2 = stage2.replace(old, new, 1)

stage2_path.write_text(stage2, encoding="utf-8")

print("stage 0 applied")
