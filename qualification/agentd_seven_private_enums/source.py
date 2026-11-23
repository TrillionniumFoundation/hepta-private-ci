"""Replay scoped source comparisons against three unmodified trees or materialized blob roots."""
import hashlib
import json
import sys
from pathlib import Path

BASE = "c12ee03f3185d5a13949faca54f066dfd634e509"
PRODUCT = "f2d0f3ddaf5a2350ddb46584ad3b80d3271f982f"
DONOR = "24abd04c825cb0d5d0ce27b52ac5008eda13dde4"
MODULE = Path("codex-rs/hepta-agentd/src")
root = Path(__file__).resolve().parent
base, product, donor = (Path(arg).resolve() for arg in sys.argv[1:])
table = json.loads((root/"seven.json").read_bytes())
assert len(table) == len({r["type"] for r in table}) == 7

def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

sys.path.insert(0, str(base / "scripts"))
import verify_hepta_callers as callers

manifest = callers._load_manifest(base / "CALLERS.toml")
protected = {r["path"]: r for r in manifest["protected_file"]}
comparisons = {}
for item in table:
    path = item["path"]
    before = (base/path).read_bytes()
    ancestor = (donor/path).read_bytes()
    assert git_blob(before) == item["source_blob"]
    assert git_blob(ancestor) == item["donor_blob"]
    assert before.decode().splitlines()[item["line"] - 1] == f'enum {item["type"]} {{'
    if path in comparisons:
        continue
    row = protected[path]
    current = (product/path).read_bytes()
    result = {"base": git_blob(before), "candidate": git_blob(current), "donor": git_blob(ancestor)}
    for label, tree in (("base", base), ("candidate", product), ("direct_full_donor", donor)):
        try:
            callers._verify_protected_files(tree, {"protected_file": [row]})
            outcome = "pass"
        except callers.VerificationFailure as exc:
            outcome = str(exc)
        result[label + "_source_guard"] = outcome
    assert result["base_source_guard"] == result["candidate_source_guard"] == "pass"
    result["donor_lost_literal_markers"] = [m for m in row.get("required", []) if m in before.decode() and m not in ancestor.decode()]
    comparisons[path] = result
transport = str(MODULE/"authority_host_learning_resident_transport.rs")
assert [path for path, obj in comparisons.items() if obj["base"] != obj["candidate"]] == [transport]
assert comparisons[transport]["candidate"] == "747e86df3d0e937dc00ccec4ba9f898c7635a766"
old = (base/transport).read_text()
edits = [
    ("    Observed(RootResidentLearningObservationV3),", "    Observed(Box<RootResidentLearningObservationV3>),"),
    ("                    ResidentExchangeV3::Observed(observed)\n", "                    ResidentExchangeV3::Observed(Box::new(observed))\n"),
    ("ResidentExchangeV3::Observed(observed) => Ok(observed),", "ResidentExchangeV3::Observed(observed) => Ok(*observed),"),
]
updated = old
for previous, replacement in edits:
    assert old.count(previous) == (donor/transport).read_text().count(replacement) == 1
    updated = updated.replace(previous, replacement)
assert updated.encode() == (product/transport).read_bytes()
assert "Refused(Error)" in old and old.count("ResidentExchangeV3::Observed(") == 3

readback_names = ["recover_original_root_stream", "recover_original_model_root_stream"]
readback_symbols = {s: [] for s in readback_names}
for src in sorted((base/"codex-rs").rglob("*.rs")):
    for line_no, line in enumerate(src.read_bytes().splitlines(), 1):
        for name in readback_names:
            if name.encode() in line:
                readback_symbols[name].append([str(src.relative_to(base)), line_no, line.decode().strip()])
for name, echoes in readback_symbols.items():
    assert len(echoes) == 1 and "pub fn " + name + "(" in echoes[0][2]

p = str(MODULE/"neuron_generation_receipt_owner.rs")
assert comparisons[p]["donor_lost_literal_markers"] == ["Feature(OriginalCircuitFeatureLearningSourcesV1)"]
p = str(MODULE/"circuit_evaluation_cohort_custody.rs")
assert set(comparisons[p]["donor_lost_literal_markers"]) == {"Shared(OriginalCircuitEvaluationCohortReadbackV1)", "Paired(OriginalCircuitOnPolicyCohortReadbackV1)"}
for obj, marker in (("authority_host_run_start_historical.rs","ReadState::Bound(identity.clone())"), ("authority_host_learning_resident_transport.rs","ClientOriginV3::Readback(authorization)")):
    assert marker in comparisons[str(MODULE/obj)]["direct_full_donor_source_guard"]
roster = json.loads((root/"roster.json").read_bytes())
fixtures = ["authority_host_learning_resident_wire.rs", "authority_host_learning_resident_auth.rs", "authority_host_learning_resident_profile.rs", "authority_host_learning_resident_transport_tests.rs", "authority_host_learning_resident_root_tests.rs", "authority_host_learning_resident_root_support_tests.rs", "authority_host_learning_resident_model_recovery.rs", "circuit_original_evaluation_panel_member_support_tests.rs", "circuit_original_evaluation_panel_tests.rs", "circuit_on_policy_evaluation_policy_tests.rs", "root_historical_ledger_data_tests.rs", "authority_host_run_start_retention_tests.rs", "circuit_feature_historical_source.rs", "authority_host_historical_task.rs", "ordinary_q24_cold_process_tests.rs"]
seen = set()
for src in (base/MODULE).glob("*.rs"):
    raw = src.read_bytes()
    for names in roster.values():
        for name in names:
            if b"fn " + name.rsplit("::", 1)[1].encode() + b"(" in raw:
                seen.add(name)
                fixtures.append(src.name)
assert seen == set(sum(roster.values(), []))
fixture_blobs = {}
for name in sorted(set(fixtures)):
    original = (base/MODULE/name).read_bytes()
    assert (product/MODULE/name).read_bytes() == original
    fixture_blobs[name] = git_blob(original)
transport_test = (base/MODULE/"authority_host_learning_resident_transport_tests.rs").read_text()
for evidence in ["Err(Error::CommitUncertain)", "assert_eq!(readback.snapshot(), Some(&expected))", "assert_eq!(readback.attestations(), expected_signatures.as_slice())", "assert!(!readback.dispatch_pending())", "assert_eq!(frames.load(Ordering::SeqCst), 2)", "assert_eq!(admissions.load(Ordering::SeqCst), 0)", "origin: Arc::new(ClientOriginV3::Fresh)"]:
    assert evidence in transport_test
assert git_blob((root/"cold01-original.json").read_bytes()) == "dd45e1f1098f6070fcb9d3eadb3b32e773a2aad7"
assert git_blob((root/"noupdate19-original.json").read_bytes()) == "5b92928fb9d80452e0a0c96f02bdbf891c1930a1"
cold = json.loads((root/"cold01-original.json").read_bytes())
warm = json.loads((root/"noupdate19-original.json").read_bytes())
assert warm["current_canonical_native_cases_passed"] == 4 and warm["current_canonical_native_cases_failed"] == 0
assert warm["complete_native_NoUpdate"] and not warm["physical_external_ordinary_whole_phase_downloaded"]
assert cold["source"] == warm["source_commit"] == "61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd"
assert cold["actual_result"]["failed"] == 1 and cold["actual_result"]["passed"] == 0
assert cold["actual_result"]["inner_error"] == "Error: actual first publication verification fact differs"
print(json.dumps({"base": BASE, "candidate": PRODUCT, "donor": DONOR, "private_cases": [row["type"] for row in table], "source_blob_comparisons": comparisons, "unchanged_controls": fixture_blobs, "readback_symbol_count_in_all_codex_rs": readback_symbols, "direct_donor_scope": "per whole historical file, others unchanged; production candidate takes only the three exact resident substitutions"}, indent=2, sort_keys=True))
