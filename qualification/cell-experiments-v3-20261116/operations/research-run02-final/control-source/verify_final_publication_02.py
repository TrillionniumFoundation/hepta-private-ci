"""Verify a frozen final publication package without mutating Git or research evidence."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
BASE = "6b8d8c44a183c48e761aff76e0570ab278b4f7da"
EXPECTED_CORE = json.loads("{\"scripts/cell_experiments/__init__.py\":\"6deac8e2e9f77ca207467a8911356e206a416554\",\"scripts/cell_experiments/adapter_mix_v2.py\":\"d34b8323a06e8c520505ab85b825005f0b82ff75\",\"scripts/cell_experiments/adoption.py\":\"7081221645b10962097ab9d342c4873bb2bbaf47\",\"scripts/cell_experiments/campaign.py\":\"a845278e7245670aa06189c3f698eda8e8f16138\",\"scripts/cell_experiments/causal_probe_v3.py\":\"9360b4539a1c01339a5eb6b66bf2c551ce945c71\",\"scripts/cell_experiments/causal_train_v3.py\":\"2758c33f80532635a800c0ae391864fcedeaf7a5\",\"scripts/cell_experiments/causal_training_contract_v3.py\":\"9facc17b67af8d366828fd98d5f93813dafec169\",\"scripts/cell_experiments/chat_protocol.py\":\"dfb0d33ed6e1aa48e55f81641a4c63f87e207aee\",\"scripts/cell_experiments/circuit_readiness_v3.py\":\"34686d4b9ae2a6fe37cad6f6da015ddc36d7aa64\",\"scripts/cell_experiments/circuit_receipts_v3.py\":\"09a76e0d0d664e2abad70b8e98e2b64dcd157157\",\"scripts/cell_experiments/circuit_study_v2.py\":\"8b9a41aa4116a1098f67509fbc44f99ac7d3fa70\",\"scripts/cell_experiments/circuit_task_bindings_v2.py\":\"3fa0bc82805b5acbbbdb2ea2775c3ce949fe6108\",\"scripts/cell_experiments/circuit_task_readout_v2.py\":\"1c11b926b4d3037f1275179befab827e62273097\",\"scripts/cell_experiments/circuit_v2.py\":\"63e3da539ccbded0920000fecb3a7dce799b99ea\",\"scripts/cell_experiments/coding_sft.py\":\"8ccaaf2443a6aa2893500aad89a70d83a7b1dbb7\",\"scripts/cell_experiments/composition.py\":\"4fd27499d00552b4ed32c54bfdecae3442b76bb2\",\"scripts/cell_experiments/composition_core.py\":\"06eb3dbac9ed09b3e0754eb2b2ec68ed063950ad\",\"scripts/cell_experiments/data.py\":\"1f32cb00fb815ced989580a31dd8d39424d3e1e8\",\"scripts/cell_experiments/data_builder.py\":\"01afb313916171c13aceeb57780af5bb962e62be\",\"scripts/cell_experiments/development_readiness_v3.py\":\"23d9a96f4eca594bb8cbdc503949d1e689ef6f00\",\"scripts/cell_experiments/interaction.py\":\"281f35cde9712e9046d4192db86fe47d1a8922e9\",\"scripts/cell_experiments/interaction_campaign.py\":\"89ca359422ab8e1ead2cd7e7f14e1a264c5b0cf2\",\"scripts/cell_experiments/protocol_v3.py\":\"9b9eb67ea4eed2844f27e98f9ef0b6c3b91981c7\",\"scripts/cell_experiments/repo_execution.py\":\"f6b4b82f6aac21875c27813762a7d03dc1a0b125\",\"scripts/cell_experiments/repo_interaction_v2.py\":\"6b7712e1879bac41b6ce533fd999521a7659e6d3\",\"scripts/cell_experiments/repo_interaction_v3.py\":\"56c44e28d4ecd8e365d421ef4115a624083ad935\",\"scripts/cell_experiments/repo_tasks.py\":\"46c2dc2b6772a4fe7b3e92e4ae2e405b72562d16\",\"scripts/cell_experiments/repo_tasks_v3_sqlite.py\":\"6efcaceb6972db2fd3c07d61910c13c5dce558ba\",\"scripts/cell_experiments/run_study_v2.py\":\"02e4ccce86e7abc962b6c25e743d77a8e838bfe0\",\"scripts/cell_experiments/sequence.py\":\"4cdc47188baa6c3d10317b6316061ea794a21763\",\"scripts/cell_experiments/source_metrics_retention_v3.py\":\"ac0697be6e4dba6436f7de713cf9cf506783db32\",\"scripts/cell_experiments/source_metrics_v3.py\":\"1a8fd3c43fd09d6aafee81b74275a7b57571abda\",\"scripts/cell_experiments/sqlite_agent_probe_v3.py\":\"b1d6e07ef2c918abf136473deef02533b1f24ca0\",\"scripts/cell_experiments/stage_resources_v2.py\":\"7964a0a0f146b3707879c75e5eb62ea62aa3b294\",\"scripts/cell_experiments/study_v2.py\":\"9e55d53f105201f05f0a615ffd0b47cc28d92dbf\",\"scripts/cell_experiments/study_v2_confirm.py\":\"a17a70125027cc243a569ec241758a39a6df2803\",\"scripts/cell_experiments/study_v2_evidence.py\":\"1545a727ecaa74d374ad28b4369762569328b967\",\"scripts/cell_experiments/study_v2_reporting.py\":\"f3391ddf9a49a74aee05c9b7a322b040589a532b\",\"scripts/cell_experiments/study_v2_support.py\":\"85a62561c1df2f75b32313f385788ae64b6e71f1\",\"scripts/cell_experiments/test_adapter_mix_v2.py\":\"55ab92ca9a4e2459dff6e0b6195a5217f5a81820\",\"scripts/cell_experiments/test_adoption.py\":\"6157bb3d6cff0c645307cfd67789b5cfc033d131\",\"scripts/cell_experiments/test_campaign.py\":\"0c96b86632fb0b4fc6d72b5cb5b602402279663e\",\"scripts/cell_experiments/test_causal_probe_v3.py\":\"e47b9d838828e723db5d886dd1dac3fe86839788\",\"scripts/cell_experiments/test_causal_train_v3.py\":\"fc2a136215cb01a1a887b7b9665433d27b240ab5\",\"scripts/cell_experiments/test_causal_training_contract_v3.py\":\"74b431bdb158835e1dd52f37fc42ca6f570aef17\",\"scripts/cell_experiments/test_chat_protocol.py\":\"a91ae3963f0fd4f619a2096a14a05ef1da18067f\",\"scripts/cell_experiments/test_circuit_readiness_v3.py\":\"b3bae00bab25cec943532440c2475dcb93e6297a\",\"scripts/cell_experiments/test_circuit_task_readout_v2.py\":\"ed5431ce0870ead0d87d46747504b13c748e5589\",\"scripts/cell_experiments/test_circuit_v2.py\":\"b289959f53975138aa6e76180ea0f1a9fad0afe1\",\"scripts/cell_experiments/test_coding_sft.py\":\"3e6274b517cb93408efbca5020387cde2f9cedbe\",\"scripts/cell_experiments/test_composition.py\":\"0e1a964cf1e56774b9a71994912c43f0782bce32\",\"scripts/cell_experiments/test_composition_core.py\":\"745a8ab97e4ace589d27cbffe8712a5445e77d4e\",\"scripts/cell_experiments/test_data.py\":\"0e9c16af65ff992c59669cdc5cd4ef719bb72474\",\"scripts/cell_experiments/test_development_readiness_v3.py\":\"643a81b2d67ffb6959931a4a87d17027c9e63a98\",\"scripts/cell_experiments/test_interaction.py\":\"7ed4de9218618b60c0591b4299692cd01911260c\",\"scripts/cell_experiments/test_interaction_campaign.py\":\"729b7ed61451b2d97a09683fb31d16710b1bc23c\",\"scripts/cell_experiments/test_repo_execution.py\":\"e57f7a6eaaf5bc9324ada5391c385e1e1106b196\",\"scripts/cell_experiments/test_repo_interaction_v2.py\":\"18a42c8990d0e921651de54cf0dbb6b670e4ef47\",\"scripts/cell_experiments/test_repo_interaction_v3.py\":\"fd9dbfdb84624e464bd962c35ce702803dd9ae7c\",\"scripts/cell_experiments/test_sequence.py\":\"5987e279f6d8c8754f7cfda1ea094c799c21362f\",\"scripts/cell_experiments/test_source_metrics_v3.py\":\"a77262478b058d0b26a6c53385108e157ae8ff22\",\"scripts/cell_experiments/test_sqlite_agent_probe_v3.py\":\"fd981418c08ffd4cf0121cd6b44984c0ab48e78d\",\"scripts/cell_experiments/test_study_v2.py\":\"e866a2ed757988d21b5c493c236bbe2bc952aa35\",\"scripts/cell_experiments/test_study_v2_confirm.py\":\"c4f31e7c2ec7d6df64e16278c2c9d76417407b3a\"}")
PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-run02-final/"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    assert Path(args.archive).name == args.archive
    archive_path = ROOT / args.archive
    assert archive_path.is_file() and not archive_path.is_symlink()
    raw = archive_path.read_bytes()
    assert sha(raw) == args.archive_sha256
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        for name in names:
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
        assert archive.testzip() is None
        def member(path):
            matches = [n for n in names if n == path or n.endswith("/" + path)]
            assert len(matches) == 1, (path, matches)
            return archive.read(matches[0])
        plan_raw = member("NATIVE_FINAL_PLAN_01.json")
        assert sha(plan_raw) == args.plan_sha256
        plan = json.loads(plan_raw)
        assert plan["base_commit"] == BASE
        assert plan["expected_complete_core_git_blobs"] == EXPECTED_CORE
        assert len(EXPECTED_CORE) == 64
        seen = []
        expected_number = 97
        for stage in plan["stages"]:
            assert stage["number"] == expected_number
            expected_number += 1
            assert stage["added_text_lines"] <= 800
            assert not stage.get("mechanical_evidence_exception")
            seen.extend(stage["files"])
        assert len(seen) == len(set(seen)) and set(seen) == set(plan["files"])
        total_bytes = 0
        for name, identity in plan["files"].items():
            assert name.startswith(PREFIX)
            data = member(name)
            assert len(data) == identity["bytes"] < 512000
            assert sha(data) == identity["sha256"]
            total_bytes += len(data)
        summary_name = PREFIX + "summary/RESULTS_AND_DECISIONS.md"
        assert summary_name in plan["files"]
        review = {name: member(name).decode("utf-8") for name in plan["files"]
                  if name in (summary_name, PREFIX + "README.md", PREFIX + "COVERAGE.json")}
    output = ROOT / "publication-final-root-check-02"
    output.mkdir(exist_ok=False)
    result = {
        "schema": "hepta.final-publication-root-byte-review.v1",
        "archive": archive_path.name, "archive_sha256": sha(raw),
        "plan_sha256": sha(plan_raw), "base_commit": BASE,
        "verified_payload_files": len(plan["files"]), "payload_bytes": total_bytes,
        "stages": len(plan["stages"]), "first_stage": 97,
        "last_stage": expected_number - 1, "core_git_blobs": 64,
        "all_payload_bytes_verified": True,
        "new_model_calls": 0, "new_verifier_calls": 0, "git_mutated": False,
        "archive_copied": False, "merged": False, "production_adoption": False,
        "scope": "Immutable publication bytes and plan limits; not a new experimental result"}
    for name, value in (("RESULT.json", result), ("REVIEW_TEXT.json", review)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
