"""Reproducible adapter continuation across processes or three real CI runners.

Features are frozen encoder outputs, not an encoder trained on each node. The
handoff excludes the uninterrupted reference weights; only the verifier obtains
both. Local invocation never establishes distinct-machine execution.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

import numpy as np

from adapter import Adapter
from lifecycle import canonical, sha


PREFIX, TOTAL, EXTRA = 35, 90, 7


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def read_json(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return sha(Path(path).read_bytes())


def identity(role):
    boot = Path("/proc/sys/kernel/random/boot_id")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if os.environ.get("GITHUB_SHA", commit) != commit:
        raise ValueError("checkout differs from this workflow source")
    package = Path(__file__).parent
    return dict(role=role, boot_id=boot.read_text().strip() if boot.exists() else None,
                hostname=platform.node(), pid=os.getpid(), source_commit=commit,
                run_id=os.environ.get("GITHUB_RUN_ID"),
                run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
                job=os.environ.get("GITHUB_JOB"), numpy=np.__version__,
                python=platform.python_version(), blas_core=os.environ.get("OPENBLAS_CORETYPE"),
                source_hashes={name: file_sha(package / name) for name in
                               ("adapter.py", "lifecycle.py", "migration.py", "runtime_restore.py",
                                "backend.py", "download_model.py", "requirements-runtime.txt")})


def same_execution(earlier, current):
    for key in ("source_commit", "run_id", "run_attempt", "source_hashes", "numpy", "python", "blas_core"):
        if earlier[key] != current[key]:
            raise ValueError("handoff execution binding mismatch: " + key)


def fixture(directory, binding):
    directory = Path(directory)
    if file_sha(directory / "features.npz") != binding["features_sha256"]:
        raise ValueError("source feature bytes changed")
    if file_sha(directory / "encoder_manifest.json") != binding["manifest_sha256"]:
        raise ValueError("encoder/source manifest changed")
    with np.load(directory / "features.npz", allow_pickle=False) as data:
        X, y = data["X"].copy(), data["y"].copy()
    if X.dtype != np.float32 or X.ndim != 2 or X.shape[1] != 384 or not np.isfinite(X).all():
        raise ValueError("expected finite frozen 384-dimensional FP32 encoder features")
    if y.dtype != np.int64 or y.shape != (len(X),) or len(X) < 2:
        raise ValueError("invalid frozen labels")
    return X, y


def train(model, X, y, steps, binding):
    return model.train(X, y, steps=steps, batch_size=16, lr=0.01,
                       data_id=binding["features_sha256"],
                       source_version=binding["source_version"],
                       encoder_hash=binding["encoder_hash"])


def load_model(path, binding):
    return Adapter.load(path, expected_encoder_hash=binding["encoder_hash"],
                        expected_source_version=binding["source_version"],
                        expected_data_id=binding["features_sha256"])


def storage(directory):
    return {str(p.relative_to(directory)): p.stat().st_size
            for p in sorted(Path(directory).rglob("*")) if p.is_file()}


def transfer_receipt(start, directory):
    sizes = storage(directory)
    return dict(materialized_bytes=sum(sizes.values()), files=sizes,
                download_and_extract_wall_seconds=None if start is None else
                (time.time_ns() - read_json(start)["started_ns"]) / 1e9,
                scope="includes artifact service/action overhead; upload durations remain in CI logs")


def prepare(args):
    input_started = time.perf_counter()
    out = Path(args.out)
    handoff, reference = out / "handoff", out / "reference"
    handoff.mkdir(parents=True, exist_ok=False)
    reference.mkdir(exist_ok=False)
    shutil.copyfile(args.input, handoff / "features.npz")
    shutil.copyfile(args.manifest, handoff / "encoder_manifest.json")
    manifest = read_json(args.manifest)
    binding = {key: manifest[key] for key in ("encoder_hash", "source_version")}
    for value in binding.values():
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("encoder/source binding must be a SHA-256 identity")
    binding.update(features_sha256=file_sha(handoff / "features.npz"),
                   manifest_sha256=file_sha(handoff / "encoder_manifest.json"))
    X, y = fixture(handoff, binding)
    input_seconds = time.perf_counter() - input_started
    if sorted(set(y.tolist())) != list(range(int(y.max()) + 1)):
        raise ValueError("labels must be contiguous, observed classes")
    initial = Adapter(input_dim=384, num_classes=int(y.max()) + 1, rank=8, seed=13031,
                      encoder_hash=binding["encoder_hash"], source_version=binding["source_version"])
    prefix, expected = initial.clone(), initial.clone()
    times = [train(prefix, X, y, PREFIX, binding), train(expected, X, y, TOTAL, binding)]
    write_started = time.perf_counter()
    prefix.save(handoff / "prefix.npz")
    expected.save(reference / "expected.npz")
    write_seconds = time.perf_counter() - write_started
    expected_plus = expected.clone()
    times.append(train(expected_plus, X, y, EXTRA, binding))
    write_started = time.perf_counter()
    expected_plus.save(reference / "expected_plus.npz")
    write_seconds += time.perf_counter() - write_started
    receipt = dict(schema="hepta.memory.adapter-migration.v13", node=identity("prepare"),
                   binding=binding, prefix_steps=PREFIX, total_steps=TOTAL, extra_steps=EXTRA,
                   prefix_file_sha256=file_sha(handoff / "prefix.npz"),
                   prefix_state_sha256=prefix.state_hash(), training=times,
                   input_copy_read_seconds=input_seconds, checkpoint_write_seconds=write_seconds,
                   limits=["fixed preencoded features; adapter training only",
                           "trusted artifact transport; no distributed ownership protocol"])
    write_json(handoff / "PREPARE.json", receipt)
    write_json(reference / "REFERENCE.json", dict(
        prepare_sha256=file_sha(handoff / "PREPARE.json"),
        expected_state_sha256=expected.state_hash(),
        expected_plus_state_sha256=expected_plus.state_hash(),
        expected_file_sha256=file_sha(reference / "expected.npz"),
        expected_plus_file_sha256=file_sha(reference / "expected_plus.npz"),
        predictions=expected.predict(X).tolist(), extra_predictions=expected_plus.predict(X).tolist()))
    write_json(out / "STORAGE.json", storage(out))
    return receipt


def resume(args):
    directory, out = Path(args.input), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    transport = transfer_receipt(args.transfer_start, directory)
    receipt = read_json(directory / "PREPARE.json")
    node = identity("resume")
    same_execution(receipt["node"], node)
    if receipt["node"]["role"] != "prepare":
        raise ValueError("unexpected handoff role")
    binding = receipt["binding"]
    X, y = fixture(directory, binding)
    if file_sha(directory / "prefix.npz") != receipt["prefix_file_sha256"]:
        raise ValueError("prefix checkpoint changed")
    started = time.perf_counter()
    model = load_model(directory / "prefix.npz", binding)
    load_seconds = time.perf_counter() - started
    if model.state_hash() != receipt["prefix_state_sha256"] or model.step != PREFIX:
        raise ValueError("prefix full training state differs")
    training = train(model, X, y, TOTAL - PREFIX, binding)
    started = time.perf_counter()
    model.save(out / "resumed.npz")
    save_seconds = time.perf_counter() - started
    result = dict(node=node, binding=binding, prepare_sha256=file_sha(directory / "PREPARE.json"),
                  resumed_state_sha256=model.state_hash(), checkpoint_sha256=file_sha(out / "resumed.npz"),
                  step=model.step, predictions=model.predict(X).tolist(), training=training,
                  transfer=transport, load_seconds=load_seconds, save_seconds=save_seconds)
    write_json(out / "RESUME.json", result)
    return result


def verify(args):
    source, resumed, reference = Path(args.source), Path(args.input), Path(args.reference)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    transport = transfer_receipt(args.transfer_start, source.parent)
    preparation = read_json(source / "PREPARE.json")
    continuation = read_json(resumed / "RESUME.json")
    oracle = read_json(reference / "REFERENCE.json")
    node = identity("verify")
    for earlier in (preparation["node"], continuation["node"]):
        same_execution(earlier, node)
    preparation_sha = file_sha(source / "PREPARE.json")
    if continuation["prepare_sha256"] != preparation_sha or oracle["prepare_sha256"] != preparation_sha:
        raise ValueError("reference or continuation belongs to another prefix")
    if continuation["node"]["role"] != "resume" or continuation["binding"] != preparation["binding"]:
        raise ValueError("continuation identity differs")
    binding = preparation["binding"]
    X, y = fixture(source, binding)
    for path, expected in ((resumed / "resumed.npz", continuation["checkpoint_sha256"]),
                           (reference / "expected.npz", oracle["expected_file_sha256"]),
                           (reference / "expected_plus.npz", oracle["expected_plus_file_sha256"])):
        if file_sha(path) != expected:
            raise ValueError("verification checkpoint bytes changed")
    model, expected = load_model(resumed / "resumed.npz", binding), load_model(reference / "expected.npz", binding)
    checks = dict(complete_state_exact=model.state_hash() == expected.state_hash() == oracle["expected_state_sha256"],
                  predictions_exact=np.array_equal(model.predict(X), expected.predict(X)),
                  step_exact=model.step == expected.step == TOTAL,
                  sender_state_exact=model.state_hash() == continuation["resumed_state_sha256"],
                  sender_predictions_exact=model.predict(X).tolist() == continuation["predictions"])
    if args.require_runtime_restore:
        runtime = read_json(resumed / "runtime-restore.json")
        same_execution(runtime["node"], node)
        checks["target_backend_restored"] = (runtime["passed"] is True and runtime["binding"] == binding
            and runtime["checkpoint_sha256"] == continuation["checkpoint_sha256"]
            and runtime["state_before"] == runtime["state_after"] == model.state_hash())
    # Incorrect base/source bindings must fail at load, not only after prediction.
    for key in ("encoder_hash", "source_version", "features_sha256"):
        wrong = dict(binding, **{key: "0" * 64 if binding[key] != "0" * 64 else "1" * 64})
        try:
            load_model(resumed / "resumed.npz", wrong)
        except ValueError:
            checks["reject_wrong_" + key] = True
        else:
            checks["reject_wrong_" + key] = False
    extra_training = train(model, X, y, EXTRA, binding)
    expected_plus = load_model(reference / "expected_plus.npz", binding)
    checks["future_training_exact"] = model.state_hash() == expected_plus.state_hash() == oracle["expected_plus_state_sha256"]
    checks["future_predictions_exact"] = np.array_equal(model.predict(X), expected_plus.predict(X))
    model.save(out / "verified_plus.npz")
    nodes = [preparation["node"], continuation["node"], node]
    distinct = all(n["boot_id"] for n in nodes) and len({n["boot_id"] for n in nodes}) == 3
    if args.require_distinct_boots:
        checks["three_distinct_boots"] = distinct
        checks["three_real_ci_jobs"] = all(n["run_id"] and n["job"] for n in nodes) and len({n["job"] for n in nodes}) == 3
    result = dict(checks=checks, passed=all(checks.values()), nodes=nodes,
                  actual_distinct_boots=distinct, cross_vm_claim=bool(args.require_distinct_boots and distinct),
                  extra_training=extra_training, transfer=transport,
                  expected_state_sha256=expected.state_hash(), resumed_state_sha256=continuation["resumed_state_sha256"],
                  scope="exact adapter/Adam/RNG/sampler continuation on frozen encoder features")
    write_json(out / "VERIFY.json", result)
    if not result["passed"]:
        raise ValueError("migration verification failed; exact evidence retained")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "resume", "verify", "mark-transfer"))
    for name in ("input", "manifest", "source", "reference", "transfer-start"):
        parser.add_argument("--" + name)
    parser.add_argument("--out", required=True)
    parser.add_argument("--require-distinct-boots", action="store_true")
    parser.add_argument("--require-runtime-restore", action="store_true")
    args = parser.parse_args()
    if args.phase == "mark-transfer":
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, dict(started_ns=time.time_ns()))
        return
    started, cpu = time.perf_counter(), time.process_time()
    try:
        result = {"prepare": prepare, "resume": resume, "verify": verify}[args.phase](args)
        print(json.dumps(dict(phase=args.phase, passed=result.get("passed", True)), sort_keys=True))
    except BaseException as error:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        write_json(Path(args.out) / "FAILURE.json", dict(phase=args.phase, type=type(error).__name__, error=str(error)))
        raise
    finally:
        write_json(Path(args.out) / "EXECUTION.json", dict(phase=args.phase,
                   wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                   retained_bytes=sum(storage(args.out).values())))


if __name__ == "__main__":
    main()
