"""Exercise the old and repaired E2E SQL against independent generation histories."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--candidate-file", type=Path)
parser.add_argument("--baseline-file", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
relative_path = "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"
baseline = "907d4f512819a71bece82e7f89944e9406466e36"
values = {
    "old": args.baseline_file.read_text() if args.baseline_file else subprocess.check_output(
        ["git", "show", f"{baseline}:{relative_path}"], cwd=args.repository, text=True
    ),
    "new": (args.candidate_file or args.repository / relative_path).read_text(),
}
queries = {}
for name, value in values.items():
    value = value[value.index("async fn read_kg_sqlite_evidence("):]
    start = value.index('"SELECT r.generation' if name == "old" else '"WITH selected_heads')
    queries[name] = value[start + 1:value.index('",\n    )', start)]

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE kg_projection(projection_scope TEXT PRIMARY KEY, generation INTEGER);
CREATE TABLE kg_projection_generation_receipts(
 projection_scope TEXT, generation INTEGER, trigger_memory_id TEXT,
 trigger_memory_revision INTEGER, fact_set_sha256 TEXT, input_heads_sha256 TEXT,
 output_sha256 TEXT, entity_count INTEGER, relation_count INTEGER,
 node_count INTEGER, edge_count INTEGER, PRIMARY KEY(projection_scope,generation));
CREATE TABLE kg_projection_generation_semantics(
 projection_scope TEXT, generation INTEGER, generation_sha256 TEXT, publication_sha256 TEXT);
CREATE TABLE kg_projection_generation_storage(
 projection_scope TEXT, generation INTEGER, storage_mode TEXT);
CREATE TABLE memory_revisions(
 memory_id TEXT, revision INTEGER, verification TEXT, lifecycle TEXT,
 PRIMARY KEY(memory_id,revision));
CREATE TABLE kg_revision_entities(
 memory_id TEXT, memory_revision INTEGER, entity_key TEXT, source_id TEXT, source_revision INTEGER);
CREATE TABLE kg_revision_relations(
 memory_id TEXT, memory_revision INTEGER, relation_key TEXT, source_id TEXT, source_revision INTEGER);
CREATE TABLE kg_nodes(
 projection_scope TEXT,generation INTEGER,memory_id TEXT,memory_revision INTEGER,
 source_id TEXT,source_revision INTEGER);
CREATE TABLE kg_edges(
 projection_scope TEXT,generation INTEGER,memory_id TEXT,memory_revision INTEGER,
 source_id TEXT,source_revision INTEGER);
""")

active = {}
generations = {}
cases = []

def publish(label, scope, memory, revision, entities, relations, verification="verified", lifecycle="active"):
    generation = generations.get(scope, 0) + 1
    generations[scope] = generation
    # The independent oracle keeps only the latest value in each scope.
    active[(scope, memory)] = (
        entities if verification == "verified" and lifecycle == "active" else 0,
        relations if verification == "verified" and lifecycle == "active" else 0,
    )
    expected = tuple(sum(v[i] for (s, _), v in active.items() if s == scope) for i in (0, 1))
    source = f"source:{memory}:{revision}"
    db.execute("INSERT INTO memory_revisions VALUES (?,?,?,?)", (memory, revision, verification, lifecycle))
    db.executemany("INSERT INTO kg_revision_entities VALUES (?,?,?,?,1)",
                   [(memory, revision, f"entity-{i}", source) for i in range(entities)])
    db.executemany("INSERT INTO kg_revision_relations VALUES (?,?,?,?,1)",
                   [(memory, revision, f"relation-{i}", source) for i in range(relations)])
    db.execute("INSERT INTO kg_projection_generation_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (scope, generation, memory, revision, "fact", "heads", "output",
                entities, relations, *expected))
    db.execute("INSERT INTO kg_projection_generation_semantics VALUES (?,?,?,?)",
               (scope, generation, "generation", "publication"))
    db.execute("INSERT INTO kg_projection_generation_storage VALUES (?,?,?)",
               (scope, generation, "revision_facts_v1"))
    db.execute("INSERT INTO kg_projection VALUES (?,?) ON CONFLICT(projection_scope) DO UPDATE SET generation=excluded.generation",
               (scope, generation))
    repaired = db.execute(queries["new"], (memory, revision)).fetchone()
    original = db.execute(queries["old"], (source, source, memory, revision)).fetchone()
    assert repaired is not None and repaired[-2:] == expected
    assert repaired[8:10] == expected
    cases.append({"case": label, "scope": scope, "generation": generation,
                  "expected_counts": expected, "old_counts": original[-2:],
                  "repaired_counts": repaired[-2:], "passed": True})
    return memory, revision, scope, generation

publish("initial remember", "scope-a", "alpha", 1, 2, 1)
publish("different scope excluded", "scope-b", "foreign", 1, 9, 8)
publish("multiple active memories retained", "scope-a", "beta", 1, 3, 2)
publish("correction supersedes old revision", "scope-a", "alpha", 2, 4, 2)
publish("forget removes prior active facts", "scope-a", "alpha", 3, 0, 0, lifecycle="tombstoned")
publish("unverified facts excluded", "scope-a", "gamma", 1, 5, 4, verification="unverified")
memory, revision, scope, generation = publish("last active memory forgotten", "scope-a", "beta", 2, 0, 0, lifecycle="tombstoned")
assert db.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0] == 0
assert db.execute("SELECT COUNT(*) FROM kg_edges").fetchone()[0] == 0

# Corruption must still be detected; never just copy the receipt's own count.
memory, revision, scope, generation = publish("new active generation", "scope-a", "alpha", 4, 2, 1)
db.execute("DELETE FROM kg_revision_entities WHERE memory_id=? AND memory_revision=? AND entity_key=?",
           (memory, revision, "entity-0"))
row = db.execute(queries["new"], (memory, revision)).fetchone()
assert row[8:10] != row[-2:]
cases.append({"case": "missing immutable fact rejected by count assertion", "passed": True,
              "receipt_counts": row[8:10], "actual_counts": row[-2:]})
db.execute("UPDATE kg_projection_generation_storage SET storage_mode='unsupported' WHERE projection_scope=? AND generation=?",
           (scope, generation))
assert db.execute(queries["new"], (memory, revision)).fetchone() is None
cases.append({"case": "unknown storage mode does not qualify", "passed": True})

result = {
    "baseline_source": "907d4f512819a71bece82e7f89944e9406466e36",
    "validation_kind": "SQLite independent in-memory generation-history oracle",
    "cases": cases,
    "passed": all(c["passed"] for c in cases),
    "full_agentd_process_test_executed": False,
    "limits": "This verifies the repaired evidence query. Original Agentd/Bazel end-to-end qualification remains required.",
}
args.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
