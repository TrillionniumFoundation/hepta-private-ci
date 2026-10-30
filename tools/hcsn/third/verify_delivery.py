"""Verify exact delivered files and distinguish integrity from scientific gates."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE/"delivery_manifest.json").read_text())
    python_modules = 0
    for row in manifest["files"]:
        path = (ROOT/row["path"]).resolve()
        assert path.is_relative_to(ROOT.resolve()) and path.is_file(), row["path"]
        raw = path.read_bytes()
        assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"], row["path"]
        git = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        assert git == row["git_blob_sha"], row["path"]
        if path.suffix == ".py":
            source = raw.decode()
            tree = ast.parse(source, filename=str(path))
            assert len(source.splitlines()) < 500, row["path"]
            assert not any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in ast.walk(tree))
            python_modules += 1
    for relative, digest in manifest["baseline_unchanged_sha256"].items():
        assert sha(ROOT/relative) == digest, relative
    for group in ("encoder", "memory", "confirmation"):
        frozen = json.loads((HERE/group/"freeze.json").read_text())
        for relative, digest in frozen["source_sha256"].items():
            assert sha(ROOT/relative) == digest, (group, relative)
    analytical = json.loads((HERE/"analytic/results.json").read_text())
    assert analytical["all_executed_checks_passed"] and analytical["complete_with_jax"]
    assert json.loads((HERE/"flow/results.json").read_text())["passed"]
    assert json.loads((HERE/"legacy/replay_results.json").read_text())["passed"]
    encoder_audit = json.loads((HERE/"encoder/audit.json").read_text())
    assert encoder_audit["passed"]
    assert encoder_audit["analysis_sha256"] == sha(HERE/"encoder/analysis.json")
    assert encoder_audit["source_freeze_sha256"] == sha(HERE/"encoder/freeze.json")
    features = json.loads((HERE/"encoder/features/manifest.json").read_text())
    feature_hashes = {d["dataset"]: d["sha256"] for d in features["datasets"]}
    assert features["source_freeze_sha256"] == sha(HERE/"encoder/freeze.json")
    assert features["source_audit_sha256"] == sha(HERE/"encoder/audit.json")
    neural_runs = 0
    for dataset in ("ag_news", "cifar10"):
        result = json.loads((HERE/"encoder"/(dataset+"_results.json")).read_text())
        assert result["complete"] and len(result["runs"]) == 50
        assert result["freeze_sha256"] == sha(HERE/"encoder/freeze.json")
        assert result["features_sha256"] == feature_hashes[dataset]
        assert encoder_audit["datasets"][dataset]["result_sha256"] == sha(HERE/"encoder"/(dataset+"_results.json"))
        for row in result["runs"]:
            for name in ("checkpoint", "prediction"):
                assert sha(HERE/"encoder"/row[name+"_file"]) == row[name+"_sha256"]
        neural_runs += len(result["runs"])
    memory = json.loads((HERE/"memory/development_results.json").read_text())
    assert memory["complete"] and len(memory["runs"]) == 48
    assert not memory["development_gate"]["passed"]
    replay = json.loads((HERE/"memory/development_audit.json").read_text())
    assert replay["passed"] and len(replay["independent_numpy_replays"]) == 48
    assert replay["development_results_sha256"] == sha(HERE/"memory/development_results.json")
    summary = json.loads((HERE/"memory/development_summary.json").read_text())
    assert summary["evidence_audit_passed"] and not summary["development_gate_passed"]
    assert summary["scientific_freeze_sha256"] == sha(HERE/"memory/freeze.json")
    assert summary["development_results_sha256"] == sha(HERE/"memory/development_results.json")
    assert summary["replay_audit_sha256"] == sha(HERE/"memory/development_audit.json")
    assert summary["summarizer_sha256"] == sha(HERE/"memory/summarize.py")
    sealed_memory = json.loads((HERE/"memory/delivery_manifest.json").read_text())
    for relative, record in sealed_memory["files"].items():
        assert sha(HERE/"memory"/relative) == record["sha256"], relative
    for row in memory["runs"]:
        assert sha(HERE/"memory"/row["checkpoint_file"]) == row["checkpoint_sha256"]
    neural_runs += len(memory["runs"])
    confirmation = json.loads((HERE/"confirmation/execution.json").read_text())
    assert confirmation["status"] == "not_executed_development_failed"
    assert confirmation["development_result_sha256"] == sha(HERE/"memory/development_results.json")
    assert confirmation["confirmation_freeze_sha256"] == sha(HERE/"confirmation/freeze.json")
    assert confirmation["no_confirmation_data_constructed"]
    assert not confirmation["children"] and not confirmation["preparation_attempts"]
    assert not (HERE/"confirmation/data").exists()
    assert not (HERE/"confirmation/checkpoints").exists()
    completion = json.loads((HERE/"confirmation/completion_audit.json").read_text())
    assert completion["execution_sha256"] == sha(HERE/"confirmation/execution.json")
    assert completion["development_result_sha256"] == sha(HERE/"memory/development_results.json")
    assert completion["confirmation_freeze_sha256"] == sha(HERE/"confirmation/freeze.json")
    assert completion["no_confirmation_model_initialization_or_training_started"]
    assert completion["completed_development_runs"] == 48 and completion["formal_training_runs"] == 0
    for dataset in features["datasets"]:
        combined = hashlib.sha256()
        total = 0
        for part in dataset["parts"]:
            raw = (HERE/"encoder/features"/part["name"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == part["sha256"]
            combined.update(raw)
            total += len(raw)
        assert total == dataset["size_bytes"] and combined.hexdigest() == dataset["sha256"]
    analysis = json.loads((HERE/"encoder/analysis.json").read_text())
    assert not analysis["financial_specific_gate_passed"]
    report = dict(integrity_passed=True, manifest_sha256=sha(HERE/"delivery_manifest.json"),
                  files_verified=len(manifest["files"]), python_modules_checked=python_modules,
                  unchanged_baseline_files_verified=len(manifest["baseline_unchanged_sha256"]),
                  new_neural_training_runs=neural_runs, new_linear_fits=2,
                  encoder_training_runs=100, sequence_development_runs=48,
                  conditional_confirmation_training_runs=0,
                  sequence_development_gate_passed=False, encoder_financial_specific_gate_passed=False,
                  full_backbone_scale_gate_established=False,
                  meaning="File and recorded-evidence integrity; scientific failures remain failures")
    (HERE/"delivery_integrity.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
