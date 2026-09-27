#!/usr/bin/env python3
"""One-shot checked integration; deleted from the materialized candidate."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'a126987b84737dbc2ee2592442a314117bddb4a2'
PRIOR = 'ac294a5d0b33794dd8bf85fc252faa5f4df41abd'
ANCESTOR = '7ddbfac88525196e7a4b31387ceae194958275f5'
IMPORT = [
    '.github/workflows/hepta-knowledge-graph-qualification.yml',
    'codex-rs/hepta-kg/src/generation.rs',
    'codex-rs/hepta-kg/src/generation_tests.rs',
    'codex-rs/hepta-kg/src/lib.rs',
    'codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs',
    'codex-rs/hepta-memory/src/cognitive_store_tests.rs',
    'qualification/knowledge-graph/TARGET_HOST.md',
    'scripts/hepta-knowledge-graph-target-measure.py',
]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def change(path, old, new):
    file = ROOT / path
    text = file.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: expected exactly one patch anchor, got {text.count(old)}: {old[:100]!r}')
    file.write_text(text.replace(old, new))


assert git('merge-base', BASE, PRIOR) == ANCESTOR
assert not git('diff', '--name-only', ANCESTOR, BASE, '--', *IMPORT), 'KG imports conflict with current main'
assert set(git('diff', '--name-only', ANCESTOR, PRIOR).splitlines()) == set(IMPORT), 'unexpected predecessor scope'
for path in IMPORT:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(subprocess.check_output(['git', 'show', f'{PRIOR}:{path}'], cwd=ROOT))

GEN = 'codex-rs/hepta-kg/src/generation.rs'
change(GEN, 'use std::fmt;\n', 'use std::fmt;\n\n#[path = "indexed_query.rs"]\nmod indexed_query;\npub use indexed_query::VerifiedKnowledgeGenerationV2;\n')
change(GEN, '    NonCanonicalSupportOrder,\n', '    NonCanonicalSupportOrder,\n    NonCanonicalNodeOrder,\n    NonCanonicalEdgeOrder,\n')
change(GEN, '    let mut node_ids = BTreeSet::new();\n', '''    if nodes.windows(2).any(|pair| pair[0].node_id > pair[1].node_id) {
        return Err(KnowledgeGenerationErrorV2::NonCanonicalNodeOrder);
    }
    if edges.windows(2).any(|pair| pair[0].identity > pair[1].identity) {
        return Err(KnowledgeGenerationErrorV2::NonCanonicalEdgeOrder);
    }
    let mut node_ids = BTreeSet::new();
''')
change(GEN, '        if previous.is_some_and(|value| value >= support) {\n', '''        if previous.is_some_and(|value| {
            value.source_id == support.source_id && value.source_revision == support.source_revision
        }) {
            return Err(KnowledgeGenerationErrorV2::DuplicateSupport);
        }
        if previous.is_some_and(|value| value >= support) {
''')
change(GEN, '''        if !node_ids.contains(&edge.identity.source_node_id)
            || !node_ids.contains(&edge.identity.target_node_id)
        {
            return Err(KnowledgeGenerationErrorV2::UnknownEdgeNode);
        }
        canonicalize_supports(&mut edge.supports)?;
        edge.supports.retain(|support| !support.tombstoned);
        if edge.supports.is_empty() {
            continue;
        }
''', '''        canonicalize_supports(&mut edge.supports)?;
        edge.supports.retain(|support| !support.tombstoned);
        if edge.supports.is_empty() {
            continue;
        }
        if !node_ids.contains(&edge.identity.source_node_id)
            || !node_ids.contains(&edge.identity.target_node_id)
        {
            return Err(KnowledgeGenerationErrorV2::UnknownEdgeNode);
        }
''')
change(GEN, '    ensure_unique_ids("query_seed", &query.seed_node_ids)?;\n', '''    if query.seed_node_ids.len() > MAX_KNOWLEDGE_NODES_V2
        || query.relation_kinds.len() > MAX_KNOWLEDGE_EDGES_V2
    {
        return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit);
    }
    ensure_unique_ids("query_seed", &query.seed_node_ids)?;
''')
change('codex-rs/hepta-kg/src/lib.rs', 'pub use generation::KnowledgeSupportV2;\n', 'pub use generation::KnowledgeSupportV2;\npub use generation::VerifiedKnowledgeGenerationV2;\n')
with (ROOT / 'codex-rs/hepta-kg/src/generation_tests.rs').open('a') as output:
    output.write('\n#[path = "query_closure_tests.rs"]\nmod query_closure;\n')

RETRIEVAL = 'codex-rs/hepta-memory/src/cognitive_retrieval.rs'
change(RETRIEVAL, 'use codex_hepta_kg::KnowledgeGenerationV2;\n', 'use codex_hepta_kg::VerifiedKnowledgeGenerationV2;\n')
change(RETRIEVAL, 'use codex_hepta_kg::query_relations;\n', '')
change(RETRIEVAL, 'type RetrievalGenerations = BTreeMap<(String, i64), KnowledgeGenerationV2>;', '''struct RetrievalGeneration {
    verified: VerifiedKnowledgeGenerationV2,
    compact_supports: Option<BTreeMap<String, (String, i64)>>,
}

// This map never escapes one owner's SQLite read transaction. The key therefore
// cannot alias a different owner/store, and no cache survives correction/reopen.
type RetrievalGenerations = BTreeMap<(String, i64), RetrievalGeneration>;''')
change(RETRIEVAL, '''                    std::collections::btree_map::Entry::Vacant(entry) => entry.insert(
                        load_canonical_generation_tx(
                            transaction,
                            &seed.projection_scope,
                            seed.generation,
                        )
                        .await?,
                    ),''', '''                    std::collections::btree_map::Entry::Vacant(entry) => {
                        let loaded = load_canonical_generation_tx(
                            transaction, &seed.projection_scope, seed.generation,
                        ).await?;
                        let verified = VerifiedKnowledgeGenerationV2::new(loaded).map_err(|error| {
                            CognitiveStoreError::Corrupt(format!("KG query view rejected generation: {error}"))
                        })?;
                        let compact_supports = load_compact_edge_support_index_tx(
                            transaction, &seed.projection_scope, seed.generation,
                        ).await?;
                        entry.insert(RetrievalGeneration { verified, compact_supports })
                    },''')
change(RETRIEVAL, '            if generation.generation_digest.to_string() != generation_sha256.as_str() {', '            if generation.verified.generation().generation_digest.to_string() != generation_sha256.as_str() {')
change(RETRIEVAL, '''                None => generation
                    .edges
                    .iter()
                    .map(|edge| edge.identity.relation.clone())''', '''                None => generation
                    .verified
                    .relation_kinds()
                    .iter()
                    .cloned()''')
change(RETRIEVAL, '''            let query_result = query_relations(
                generation,
                KnowledgeRelationQueryV2 {''', '''            let query_result = generation.verified.query_relations(
                KnowledgeRelationQueryV2 {''')
change(RETRIEVAL, '                    generation_digest: generation.generation_digest,', '                    generation_digest: generation.verified.generation().generation_digest,')
change(RETRIEVAL, '''            let compact_supports = load_compact_edge_support_index_tx(
                transaction,
                &seed.projection_scope,
                seed.generation,
            )
            .await?;''', '            let compact_supports = &generation.compact_supports;')

# Stop silently replacing malformed benchmark settings with defaults.
BENCH = 'codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs'
change(BENCH, '''    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0 && *value <= maximum)
        .unwrap_or(default)''', '''    match std::env::var(name) {
        Err(std::env::VarError::NotPresent) => default,
        Err(error) => panic!("invalid benchmark setting {name}: {error}"),
        Ok(raw) => {
            let value = raw.parse::<usize>().expect("integer benchmark setting");
            assert!((1..=maximum).contains(&value), "out-of-range benchmark setting {name}");
            value
        }
    }''')
change('scripts/hepta-knowledge-graph-target-measure.py', 'if not isinstance(value, int) or value < lower:', 'if type(value) is not int or value < lower:')
if (ROOT / 'codex-rs/hepta-memory/src/cognitive_kg_history_tests.rs').exists():
    with (ROOT / BENCH).open('a') as output:
        output.write('\n#[path = "cognitive_kg_history_tests.rs"]\nmod history;\n')
    workflow = '.github/workflows/hepta-knowledge-graph-qualification.yml'
    change(workflow, '      - name: Strict KG lint\n', '''      - name: Exercise bounded history growth and deletion across reopen
        working-directory: codex-rs
        run: |
          cargo test --locked -p codex-hepta-memory --lib \\
            cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection \\
            -- --ignored --exact --nocapture --test-threads=1

      - name: Strict KG lint
''')

GUIDE = 'docs/modules/knowledge.graph/TECHNICAL.md'
with (ROOT / GUIDE).open('a') as output:
    output.write('''

## Query closure candidate — 2026-09-27

The durable writer still computes a complete bounded canonical generation per
logical mutation. G14 storage is `revision_facts_v1`: immutable revision facts and
generation receipts reconstruct each historical cut; new generations do not copy
all `kg_nodes`/`kg_edges` rows. Storage compaction is not incremental computation.

`VerifiedKnowledgeGenerationV2` validates an owned immutable generation once and
indexes incident edges in original canonical order. The cognitive read adapter
caches this view and the compact edge-support index once per scope/generation per
owner SQLite transaction, across seeds and relation channels. It caches no
cross-request authorization/currentness result. Temporal visibility is computed
per query, and the persisted generation digest is checked on every seed use.

The indexed path is compared against the independent full-scan selection path:
complete request/result digests, edge order, selected supports and exact omission
counts must agree. Unrelated edges are not scanned; only returned live supports
are cloned. Exact omission counts still require visiting all incident matches.
Validation and selection work counters distinguish one-time preparation from
query work. Input seed/filter lengths are bounded by kernel limits; output-edge
bounds do not imply a byte budget or a host-independent latency SLO.

Generation validators reject duplicate `(source_id, source_revision)` supports,
noncanonical node/edge order, digest drift and live dangling edges. Simultaneous
revocation of an endpoint and its final edge support removes both atomically.

See `qualification/knowledge-graph/QUERY_CLOSURE_20260927.md` for the candidate
scope, executable checks, capacity layers, history probe and acceptance boundary.
Source composition is not execution proof. All production/activation/acceptance
claims remain false until exact-head and pinned-base candidate checks and the
separate target-host/independent gates have succeeded.
''')
print('Applied checked KG source integration; commit and rebind before qualification.')
