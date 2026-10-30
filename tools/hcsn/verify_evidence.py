"""Verify delivered run counts, source/checkpoint hashes and paired data receipts."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_FILES = {
    "benchmarks/sequence_results.json":60,
    "benchmarks/sequence_v2_results.json":40,
    "benchmarks/v2_reference_results.json":10,
    "encoder/head_results.json":20,
    "benchmarks/frozen_v2_results.json":10,
    "benchmarks/snn_reference_results.json":15,
    "benchmarks/snn_frozen_results.json":5,
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(relative):
    return json.loads((ROOT/relative).read_text())


def main():
    counts, checkpoints, source_checks = {}, [], []
    for relative, expected in RUN_FILES.items():
        data = read(relative)
        assert data["complete"] and len(data["runs"]) == expected, relative
        counts[relative] = len(data["runs"])
        directory = (ROOT/relative).parent
        for run in data["runs"]:
            assert run["timing"]["steps"] == 300, (relative,run.get("seed"))
            assert run["timing"]["batch_size"] == 32
            if "checkpoint_file" in run:
                path = directory/run["checkpoint_file"]
                assert path.exists(), path
                assert sha(path) == run["checkpoint_sha256"], path
                checkpoints.append(str(path.relative_to(ROOT)))
    for path in ROOT.rglob("*.json"):
        if path.name in ("evidence_checks.json","delivery_manifest.json"):
            continue
        data = json.loads(path.read_text())
        for scope in (data,data.get("metadata",{})):
            for field in ("source_hashes","source_sha256"):
                hashes=scope.get(field,{})
                if not isinstance(hashes,dict):
                    continue
                for name,expected in hashes.items():
                    source=path.parent/name
                    assert source.exists(), (path,source)
                    assert sha(source)==expected, (path,source)
                    source_checks.append((str(path.relative_to(ROOT)),name))
    previous=read("benchmarks/sequence_results.json")["runs"]
    paired={(r["task"],r["seed"]):r["data_sha256"] for r in previous}
    for row in read("benchmarks/snn_reference_results.json")["runs"]:
        assert row["data_sha256"] == paired[(row["task"],row["seed"])]
    v2={(r["task"],r["seed"]):r["data_sha256"]
        for r in read("benchmarks/sequence_v2_results.json")["runs"]}
    for row in read("benchmarks/v2_reference_results.json")["runs"]:
        assert row["data_sha256"] == v2[(row["task"],row["seed"])]
    features=read("encoder/feature_manifest.json")["feature_file_sha256"]
    for relative in ("encoder/head_results.json","benchmarks/frozen_v2_results.json",
                     "benchmarks/snn_frozen_results.json"):
        data=read(relative)
        assert data["metadata"]["feature_sha256"] == features
        assert data["feature_sha_after_training"] == features
    assert read("analytic/validation_results.json")["all_passed"]
    assert read("analytic/jax_validation_results.json")["all_float64_checks_passed"]
    assert read("dynamics/dynamics_results.json")["validation_passed"]
    assert read("encoder/audit_results.json")["all_checks_passed"]
    syntax=[]
    for path in ROOT.rglob("*.py"):
        content=path.read_text()
        compile(content,str(path),"exec")
        assert len(content.splitlines())<500, path
        assert not any(isinstance(node,ast.ImportFrom) and node.module=="__future__"
                       for node in ast.walk(ast.parse(content))), path
        syntax.append(str(path.relative_to(ROOT)))
    result=dict(all_delivery_checks_passed=True,training_run_counts=counts,
        total_neural_training_runs=sum(counts.values()),
        independent_linear_fits_in_main_comparison=1,
        total_optimizer_updates=sum(counts.values())*300,
        checkpoint_hashes_verified=len(set(checkpoints)),
        historical_source_hash_pairs_verified=len(source_checks),
        python_files_syntax_checked=syntax,paired_synthetic_data_hashes_match=True,
        frozen_feature_hash_consistent=features,
        scope="Artifact consistency, not a new claim of scientific advantage",
        known_limitations=["float32 complete financial-kernel tolerance failed",
            "Legacy warm training timings may include a second compilation",
            "Full neural training used simplified C1 operators, not the new complete financial JAX kernel"])
    (ROOT/"evidence_checks.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
