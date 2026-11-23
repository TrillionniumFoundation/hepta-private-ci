"""Verify two fixed Rust source representations against their unchanged c12 originals.

This source-equivalence check is separate from the released caller verifier.
Pass the root of a c12 checkout. Both adjacent patches are data. Unmodified
ordinary closure tests and real compiled tests are reported separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
PREFIX = Path("codex-rs/hepta-agentd/src")
RECORDS = "circuit_original_evaluation_provider_records.rs"
PARENT = "circuit_original_evaluation_provider.rs"
ON_POLICY = "circuit_on_policy_evaluation_episode.rs"
CALLER = "circuit_original_evaluation_provider_read.rs"
CONTRACT = "circuit_original_evaluation_provider_contract.rs"
SOURCE = {
    RECORDS: "f6860787be7c3548bf231f3dd22a4ec510cb69c7",
    PARENT: "c9313c239c6cc5dc30b793a4c05f839b54ee1bd8",
    ON_POLICY: "a95939a0ad17393cc7aafe918df67a3f018c8b11",
    CALLER: "4be0fc89cceacb42570a09609f110b730c537e85",
}
PATCHES = {
    "lookup": ("bbef3e506491a09fc7f0660ee73948223cc9e6549c07d5e727c82e603a032155", (ON_POLICY, PARENT, RECORDS)),
    "owner": ("0e2e01fbfad2e304de7621ea8be561e913cd70d4a1e739d820d6117af0419a54", (CALLER, RECORDS)),
}


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def apply(root, patch, reverse):
    options = ["--reverse"] if reverse else []
    return subprocess.run(
        ["git", "apply", "--whitespace=nowarn", *options, str(patch)],
        cwd=root, capture_output=True, check=False,
    )


def write_sources(root, values):
    target = root / PREFIX
    target.mkdir(exist_ok=True, parents=True)
    for name, value in values.items():
        (target / name).write_bytes(value)


def read_sources(root, files):
    return {name: (root / PREFIX / name).read_bytes() for name in files}


def change(data, file, old, new, index=0):
    content = data[file].decode()
    matches = content.split(old)
    assert len(matches) > index + 1, (file, old, index)
    edited = old.join(matches[:index + 1]) + new + old.join(matches[index + 1:])
    return {**data, file: edited.encode()}


def controls(mode):
    if mode == "owner":
        return [
            ("unrelated cohort owner", CALLER, "&self.owners,", "&other.owners,", 0),
            ("owner with mutable binding", RECORDS, "}: &OriginalCircuitEvaluationSourceOwnersV1,", "}: &mut OriginalCircuitEvaluationSourceOwnersV1,", 0),
            ("owned source clone", RECORDS, "sources.as_slice()", "sources.clone().as_slice()", 0),
            ("omit first source read", CALLER, "let sources = self.read_sources()?;", "let sources = Vec::new();", 0),
            ("remove fresh source read", CALLER, "if self.read_sources()? != sources", "if false", 0),
            ("omit outcome validation", RECORDS, "|| outcome.authentication_digest.is_zero()", "", 0),
            ("unrelated ledger-based identity", RECORDS, "circuit_learning_run_id_v1(ledger,", "circuit_learning_run_id_v1(other_ledger,", 0),
        ]
    cases = []
    for arm, index in (("historical", 0), ("held-out", 1)):
        for field, source, other in (
            ("decision", "                decisions: &decisions,", "                decisions: &other_decisions,"),
            ("outcome", "                outcomes: &outcomes,", "                outcomes: &other_outcomes,"),
            ("publication", "                publications,", "                publications: unrelated_publications,"),
        ):
            cases.append((arm + " " + field + " source", RECORDS, source, other, index))
        cases.append((arm + " drops lookup", RECORDS, "                outcomes: &outcomes,", "", index))
    cases.extend([
        ("wrong episode key", RECORDS, ".get(&requested.episode_id)", ".get(&requested.behavior_run_id)", 0),
        ("unpacked outcome alias", RECORDS, "            outcomes,\n            publications,\n        } = records;", "            outcomes: other,\n            publications,\n        } = records;", 0),
        ("lookup written", PARENT, "pub(crate) decisions: &'lookup BTreeMap", "pub(crate) decisions: &'lookup mut BTreeMap", 0),
        ("added lookup capability", PARENT, "    pub(crate) publications: &'data Publications,", "    pub(crate) publications: &'data Publications,\n    pub(crate) owner: &'data LedgerWriter,", 0),
        ("external visibility", PARENT, "pub(crate) struct EpisodeRecords", "pub struct EpisodeRecords", 0),
        ("additional implementation", PARENT, "/// One observed cohort", "impl EpisodeRecords<'_, '_> { fn other(&self) {} }\n\n/// One observed cohort", 0),
        ("changed independent terminality", RECORDS, "|| outcome.terminality != AuthenticatedOutcomeTerminality::Terminal", "", 0),
        ("ignore zero support", RECORDS, "|| decision.support_digest.is_zero()", "", 0),
        ("unbound lineage", RECORDS, "ledger.binding_digest().as_array()", "other.binding_digest().as_array()", 0),
        ("no freshness", RECORDS, "|| finalized_at > current", "", 0),
        ("moved previous caller", ON_POLICY, "fn read_episode(", "fn read_another_episode(", 0),
        ("changed other episode check", ON_POLICY, "|| decision.support_digest.is_zero()", "", 0),
    ])
    return cases


def verify(scope, original, source_dir):
    patch_hash, files = PATCHES[scope]
    patch = HERE / (scope + ".patch")
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == patch_hash
    with tempfile.TemporaryDirectory() as name:
        stage = Path(name)
        write_sources(stage, {key: original[key] for key in files})
        assert apply(stage, patch, False).returncode == 0
        candidate = read_sources(stage, files)
        if source_dir:
            assert candidate == {key: (source_dir/key).read_bytes() for key in files}
    def reverse(snapshot):
        with tempfile.TemporaryDirectory() as name:
            restored = Path(name)
            write_sources(restored, snapshot)
            if apply(restored, patch, True).returncode:
                return False
            return all(git_blob((restored/PREFIX/path).read_bytes()) == SOURCE[path] for path in files)
    assert reverse(candidate)
    if scope == "owner":
        mark = b"    let rule = &config.rule;"
        assert original[RECORDS].split(mark, 1)[1] == candidate[RECORDS].split(mark, 1)[1]
    else:
        for path, mark in ((RECORDS, b"        let decision = *decisions"), (ON_POLICY, b"pub(super) struct Episode<'a>")):
            assert original[path].split(mark, 1)[1] == candidate[path].split(mark, 1)[1]
    negative = []
    for label, path, before, after, number in controls(scope):
        assert not reverse(change(candidate, path, before, after, number)), label
        negative.append(label)
    return {"original_git_blobs": {path: SOURCE[path] for path in files},
            "candidate_git_blobs": {path: git_blob(content) for path, content in candidate.items()},
            "patch_sha256": patch_hash, "all_original_file_bytes_recovered": True,
            "rejected_negative_controls": negative}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--lookup", type=Path)
    parser.add_argument("--owner", type=Path)
    args = parser.parse_args()
    original = read_sources(args.checkout, SOURCE)
    assert all(git_blob(original[key]) == value for key, value in SOURCE.items())
    contract = (args.checkout/PREFIX/CONTRACT).read_text()
    assert "pub struct OriginalCircuitEvaluationSourceOwnersV1 {\n    pub ledger: LedgerWriter,\n    pub sources: Vec<OriginalCircuitEvaluationSourceV1>,\n}" in contract
    print(json.dumps({key: verify(key, original, getattr(args, key)) for key in PATCHES}, indent=2))
