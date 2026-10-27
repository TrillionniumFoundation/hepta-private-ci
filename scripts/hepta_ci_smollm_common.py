"""Shared source, byte and parent bindings for controlled SmolLM pair observations."""

import hashlib
import json
import os
from pathlib import Path
import sys

if __package__:
    from .hepta_ci_candidate import candidate_plan
else:
    from hepta_ci_candidate import candidate_plan

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "smollm-pair"
NATIVE = "smollm_neural_read::tests::native::real_smollm_parent_query_original_control_final_use_and_terminal_unload"
COMPARISON = "real_gen2_gen3_forwards_score_only_after_original_holdout_consumption"
DENIED = (
    "product_artifact_installed",
    "ordinary_cognitive_context_qualified",
    "independent_accepted",
    "prospective_accepted",
    "public_reward_eligible",
)
VERSIONS = {
    "torch": "2.9.1+cpu",
    "transformers": "4.57.3",
    "peft": "0.18.0",
    "safetensors": "0.7.0",
    "tokenizers": "0.22.2",
    "numpy": "1.26.4",
    "accelerate": "1.12.0",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def read(path):
    require(path.is_file() and not path.is_symlink(), f"regular file required: {path}")
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, "JSON size limit")
    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda value: require(False, "nonfinite JSON"),
    )


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def sha(path):
    require(path.is_file() and not path.is_symlink(), f"regular file required: {path}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def command(kind):
    args = ["just", "test", "--locked", "--profile", PROFILE]
    if kind == "native":
        args += [
            "-p",
            "codex-hepta-infer-worker-host",
            "--lib",
            "-E",
            f"test(={NATIVE})",
        ]
    else:
        require(kind == "comparison", "unknown experiment")
        args += [
            "-p",
            "codex-hepta-agentd",
            "--test",
            "neural_comparison_native",
            "-E",
            f"test(={COMPARISON})",
        ]
    return args + [
        "--run-ignored",
        "only",
        "--retries",
        "0",
        "--test-threads",
        "1",
        "--no-capture",
    ]


def source_pair(chain):
    lane = os.environ["HEPTA_CI_LANE"]
    require(lane in {"source-head", "base-merge"}, "original pair lane required")
    return {
        "hepta": candidate_plan(
            source=os.environ["SOURCE_SHA"],
            tested=os.environ["TESTED_SHA"],
            base=os.environ["BASE_SHA"],
            lane=lane,
            repository=ROOT,
        ),
        "chain": candidate_plan(
            source=os.environ["CHAIN_SOURCE_SHA"],
            tested=os.environ["HEPTA_PON_CHAIN_SOURCE"],
            base=os.environ["CHAIN_BASE_SHA"],
            lane=lane,
            repository=chain,
        ),
    }


def run_context():
    value = {
        key: os.environ[key]
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    }
    require(all(value.values()), "exact CI run/attempt/job required")
    return value


def load_runtime(chain):
    sys.path.insert(0, str(chain / "scripts"))
    import llm_inherited_runtime as inherited
    import llm_runtime_pilot as runtime

    require(
        Path(runtime.__file__).resolve() == chain / "scripts/llm_runtime_pilot.py",
        "foreign runtime import",
    )
    require(
        Path(inherited.__file__).resolve()
        == chain / "scripts/llm_inherited_runtime.py",
        "foreign training import",
    )
    return runtime, inherited


def parent(output, generation, inherited):
    directory = output / f"gen{generation}" / "worker"
    path = directory / "parent-material.json"
    value = read(path)
    require(
        type(value["generation"]) is int and value["generation"] == generation,
        "wrong parent generation",
    )
    require(value["directory"] == str(directory), "foreign parent directory")
    require(
        value["file_sha256"] == sha(directory / "artifact.safetensors"),
        "parent bytes changed",
    )
    inherited.read_parent(value)
    actual = read(directory / "actual-receipt.json")
    require(
        actual["outcome"] == "success"
        and actual["phase"] == "train"
        and actual["actual_backend"] == "cpu",
        "training did not complete",
    )
    require(
        actual["generation"] == generation
        and actual["parent_material_sha256"] == sha(path),
        "training receipt mismatch",
    )
    require(
        actual["authority"] == inherited.NO_AUTHORITY
        and all(value is False for value in actual["authority"].values()),
        "training authority escalation",
    )
    require(actual["artifact"] == value["adapter"], "training artifact mismatch")
    expected_parent = (
        None
        if generation == 1
        else read(output / f"gen{generation - 1}" / "worker/parent-material.json")
    )
    require(actual["parent"] == expected_parent, "broken inherited generation link")
    return path, value
