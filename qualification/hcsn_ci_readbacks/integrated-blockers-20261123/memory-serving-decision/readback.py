"""Read the exact 43e5 regular Rust sources, strict diagnostic roster and protected-file inventory."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE = "43e5da1bb81369e4e999adfa8558f5ccb5460eb6"
STRICT = "da02bc0a91f6e9e33913e8c914a697926276f820c9387eb4248e7249225a8922"
TARGET = "codex-rs/hepta-agentd/src/memory_serving_qualification.rs"
CENSUS = "codex-rs/hepta-intelligence-eval/src/memory_citation_gate.rs"
FIXTURE = "codex-rs/hepta-intelligence-eval/src/memory_citation_gate_tests.rs"
DONOR = "24abd04c825cb0d5d0ce27b52ac5008eda13dde4"
DONOR_BLOB = "814ca0a11bd200572a0be348189584af807f95e1"
SERVING_TYPE = b"MemoryServingQualificationV1"
GATE = b"verify_memory_citation_census_v1"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def rust_objects(checkout):
    tree = subprocess.check_output(["git", "-C", str(checkout), "ls-tree", "-rz", SOURCE])
    entries = []
    for record in tree.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, blob = meta.split()
        if path.endswith(b".rs") and mode in (b"100644", b"100755") and kind == b"blob":
            entries.append((path.decode(), blob))
    with subprocess.Popen(["git", "-C", str(checkout), "cat-file", "--batch"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
        for path, blob in sorted(entries):
            proc.stdin.write(blob + b"\n")
            proc.stdin.flush()
            actual, obj, size = proc.stdout.readline().split()
            if (actual, obj) != (blob, b"blob"):
                raise ValueError(f"missing Rust blob {path}")
            data = proc.stdout.read(int(size))
            if proc.stdout.read(1) != b"\n" or git_blob(data).encode() != blob:
                raise ValueError(f"invalid Git object {path}")
            yield path, data
        proc.stdin.close()
        if proc.wait() != 0:
            raise ValueError("git cat-file did not complete")


def protected_paths(checkout):
    sys.path.insert(0, str(checkout / "scripts"))
    from hepta_caller_manifest import load_manifest
    return {entry["path"] for entry in load_manifest(checkout / "CALLERS.toml")["protected_file"]}


def records(objects, diagnostic_path, protected):
    raw = diagnostic_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != STRICT:
        raise ValueError("unexpected frozen diagnostic bytes")
    roster = json.loads(raw)
    if roster["source"] != SOURCE or roster["diagnostic_count"] != len(roster["diagnostics"]):
        raise ValueError("unexpected diagnostic identity")
    enums = [{**row, "protected_file": row["path"] in protected} for row in roster["diagnostics"]
             if re.match(r"^enum\s", row["source_line"].strip())]
    source_lines, gate_mentions, constructors = {}, {}, []
    source_hashes = hashlib.sha256()
    data_by_path = {}
    count = 0
    expr = re.compile(rb"\bMemoryServingQualificationV1\s*::\s*(selected|rollback)\s*\(")
    for path, data in objects:
        count += 1
        source_hashes.update(path.encode() + b"\0" + git_blob(data).encode() + b"\n")
        if SERVING_TYPE in data:
            source_lines[path] = [i for i, line in enumerate(data.splitlines(), 1) if SERVING_TYPE in line]
        if GATE in data:
            gate_mentions[path] = [i for i, line in enumerate(data.splitlines(), 1) if GATE in line]
        for hit in expr.finditer(data):
            constructors.append([path, data.count(b"\n", 0, hit.start()) + 1, hit.group(1).decode()])
        if path in {TARGET, CENSUS, FIXTURE}:
            data_by_path[path] = data
    old = data_by_path[TARGET]
    substitutions = {
        b"Selected(VerifiedSelfEvolutionSelectionV1)": b"Selected(Box<VerifiedSelfEvolutionSelectionV1>)",
        b"Rollback(VerifiedSelfEvolutionRollbackV1)": b"Rollback(Box<VerifiedSelfEvolutionRollbackV1>)",
        b"decision: Decision::Selected(selection)": b"decision: Decision::Selected(Box::new(selection))",
        b"decision: Decision::Rollback(rollback)": b"decision: Decision::Rollback(Box::new(rollback))",
    }
    boxed = old
    for original, new in substitutions.items():
        if boxed.count(original) != 1:
            raise ValueError("historical donor replacement mismatch")
        boxed = boxed.replace(original, new)
    if git_blob(boxed) != DONOR_BLOB:
        raise ValueError("four old-to-new substitutions do not match the historical donor")
    checks = {
        TARGET: [b"citations.decision_digest() != selection.selection_digest()",
                 b"citations.candidate_digest() != selection.receipt().candidate_artifact_digest",
                 b"citations.objective_digest() != selection.receipt().objective_digest",
                 b"citations.dataset_digest() != selection.receipt().dataset_digest",
                 b"predecessor_citations.candidate_digest() != receipt.predecessor_artifact_digest",
                 b"predecessor_citations.objective_digest() != receipt.objective_digest",
                 b"self.citations.dataset_digest() != manifest.support_digest",
                 b"value.rollback_generation() > receipt.candidate_generation",
                 b".revalidate_current(verifier, withdrawn_audit_roots, now)"],
        CENSUS: [b"selected: &VerifiedSelfEvolutionSelectionV1",
                 b"if census.selection_digest != selected.selection_digest()",
                 b".check_observer(&gate.observer, verifier, now)",
                 b"Ok(VerifiedMemoryCitationGateV1 {"],
        FIXTURE: [b"Synthetic role credentials and virtual time", b"selection: SelfEvolutionSelectionReceiptV1",
                  b"fn check(&self) -> Result<VerifiedMemoryCitationGateV1", b"        verify_census("],
    }
    guard_lines = {}
    for path, snippets in checks.items():
        lines = data_by_path[path].splitlines()
        guard_lines[path] = {}
        for snippet in snippets:
            hits = [i for i, line in enumerate(lines, 1) if snippet in line]
            if not hits:
                raise ValueError(f"absent guard or fixture property {path} {snippet}")
            guard_lines[path][snippet.decode().strip()] = hits
    return {
        "source": SOURCE, "strict_sha256": STRICT, "diagnostics": len(roster["diagnostics"]),
        "protected_file_entries": len(protected), "private_enum_rows": enums,
        "unprotected_in_private_enum_rows": [e["path"] for e in enums if not e["protected_file"]],
        "regular_rust_sources": count, "ordered_rust_path_and_blob_digest": source_hashes.hexdigest(),
        "serving_type_mentions": source_lines, "public_census_function_mentions": gate_mentions,
        "literal_qualified_serving_constructor_calls": constructors, "guard_and_fixture_source_lines": guard_lines,
        "original_blob": git_blob(old), "donor": DONOR, "verified_donor_blob": git_blob(boxed),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("strict_remaining_json", type=Path)
    a = parser.parse_args()
    head = subprocess.check_output(["git", "-C", str(a.checkout), "rev-parse", "HEAD"], text=True).strip()
    if head != SOURCE:
        raise ValueError("use the pinned 43e5 checkout to read the physical CALLERS index")
    subprocess.run(["git", "-C", str(a.checkout), "diff", "--exit-code", "HEAD", "--", "CALLERS.toml",
                    "scripts/hepta_caller_manifest.py", "scripts/hepta_callers_manifest_parts"], check=True)
    r = records(rust_objects(a.checkout), a.strict_remaining_json, protected_paths(a.checkout))
    print(json.dumps(r, indent=2, sort_keys=True))
