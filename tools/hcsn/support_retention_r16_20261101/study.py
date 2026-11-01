"""Fresh trajectory extension of eight previously frozen R15 fitted models."""

import argparse
import gzip
import hashlib
import json
import platform
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy

try:
    import resource
except ImportError:
    resource = None

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from .compression import BlockLaw
from .execution import execute


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / "addressed_decision_r15_20261101"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return dict(path=str(path.relative_to(HERE)), sha256=digest(path), bytes=len(raw))


def verify():
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    for relative, expected in manifest["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen source mismatch: {relative}")
    frozen = json.loads((BASE / "run_02/FREEZE.json").read_text())
    for name, expected in frozen["training"].items():
        if digest(BASE / "run_01/training" / name) != expected:
            raise RuntimeError(f"Frozen model mismatch: {name}")
    return manifest


def run(seed, domain, development=False):
    started, wall = time.process_time(), time.perf_counter()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    count = 2 if development else protocol["episodes_per_fit_domain"]
    if seed not in protocol["fits"] or domain not in protocol["domains"]:
        raise ValueError("Undeclared fit/domain")
    publication = None
    if not development:
        verify()
        publication = json.loads((HERE / "PUBLICATION.json").read_text())
        if publication["manifest_sha256"] != digest(HERE / "SOURCE_MANIFEST.json") or not publication["readback_verified"]:
            raise RuntimeError("Published source freeze is required")
    out = HERE / ("development" if development else "results")
    claim = dict(fit=seed, domain=domain, development=development,
                 opened_at=datetime.now(timezone.utc).isoformat(), publication=publication)
    save(out / f"claim_{seed}_{domain}.json", claim)
    training_path = BASE / "run_01/training" / f"{seed}.json.gz"
    training = json.loads(gzip.decompress(training_path.read_bytes()))
    training_process = json.loads((BASE / "run_01/supervisor" / f"train_{seed}.json").read_text())
    if training_process["exit_code"] != 0 or training_process["seed"] != seed:
        raise RuntimeError("Inherited training process did not complete successfully")
    models, ordinary = training["calibration"]["models"], training["ordinary_selected"]
    specs = {
        "A": (ordinary, "fixed", "full"), "B": (ordinary, "value", "full"),
        "C": ("hx", "fixed", "full"), "D": ("hx", "value", "full"),
        "hmm": ("hmm_same_matrix", "value", "full"), "free": ("free", "value", "full"),
        "factorized": ("hx", "value", "factorized"), "mean": ("hx", "value", "mean"),
        "block": ("hx", "value", "block"), "anchored": ("hx", "value", "anchored")}
    prep = time.process_time()
    laws, arm_preparation = {}, {}
    for arm, (model, _, _) in specs.items():
        one_start = time.process_time()
        laws[arm] = BlockLaw.from_payload(models[model]["payload"])
        arm_preparation[arm] = time.process_time() - one_start
    preparation_cpu = time.process_time() - prep
    owner = Law(theta=tuple(protocol["world_theta"]))
    arm_rows, worlds, failures, archives = {name: [] for name in specs}, [], [], []
    sums = {name: dict(utility=[], reward=[], cpu_seconds=[], wall_seconds=[], checkpoint_io_cpu_seconds=[]) for name in specs}
    counts = dict(hmm_trace_mismatches=0, valid={name: 0 for name in specs}, attempts={name: 0 for name in specs})
    world_cpu = 0.
    namespace = protocol["development_namespace"] if development else protocol["confirmation_namespace"]
    with tempfile.TemporaryDirectory(prefix="hcsn-r16-checkpoint-") as directory:
        checkpoint = Path(directory) / "owned-state.json"
        for index in range(count):
            world_start = time.process_time()
            world_seed = namespace * 10**12 + seed * 10**5 + (10000 if domain == "ood" else 0) + index
            episode = make_episode(owner, world_seed, domain)
            world_cpu += time.process_time() - world_start
            worlds.append(dict(seed=world_seed, fingerprint=episode.fingerprint,
                paths=[dict(times=t.tolist(), states=s.tolist()) for t, s in episode._paths]))
            episode_rows = {}
            # A public cyclic order balances warmup effects without outcome-based selection.
            names = list(specs)
            names = names[index % len(names):] + names[:index % len(names)]
            for arm in names:
                _, policy, representation = specs[arm]
                counts["attempts"][arm] += 1
                arm_start = time.process_time()
                try:
                    row = execute(laws[arm], episode, policy, training["light_pattern"], representation, checkpoint)
                except Exception as exc:
                    row = dict(seed=world_seed, world=episode.fingerprint, invalid=True,
                               error_type=type(exc).__name__, error=str(exc),
                               cpu_seconds=time.process_time() - arm_start)
                    failures.append(dict(arm=arm, **row))
                else:
                    counts["valid"][arm] += 1
                    for metric in sums[arm]:
                        sums[arm][metric].append(row[metric])
                arm_rows[arm].append(row)
                episode_rows[arm] = row
            if (episode_rows["D"].get("queries") != episode_rows["hmm"].get("queries")
                    or "queries" not in episode_rows["D"]):
                counts["hmm_trace_mismatches"] += 1
            if (index + 1) % 32 == 0 or index + 1 == count:
                archives.append(save(out / f"raw_{seed}_{domain}_{index // 32:02d}.json.gz",
                                     dict(fit=seed, domain=domain, worlds=worlds, arms=arm_rows)))
                worlds, arm_rows = [], {name: [] for name in specs}
    summary = {}
    for arm in specs:
        valid = counts["valid"][arm] == count
        summary[arm] = dict(valid=valid, **{
            key: (float(np.mean(value)) if valid else None) for key, value in sums[arm].items()},
            preparation_cpu_seconds=arm_preparation[arm],
            failure_cpu_seconds=sum(r["cpu_seconds"] for r in failures if r["arm"] == arm))
    if not development:
        verify()
    result = dict(schema="hcsn-support-retention-r16-run-v1", **claim, episodes=count,
        model_training_sha256=digest(training_path), ordinary_selected=ordinary,
        fixed_pattern=training["light_pattern"], arms=summary, counts=counts, failures=failures,
        archives=archives, source_manifest_sha256=None if development else digest(HERE / "SOURCE_MANIFEST.json"),
        costs=dict(worker_internal_cpu_seconds=time.process_time() - started,
                   worker_internal_wall_seconds=time.perf_counter() - wall,
                   max_rss_linux_kib=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                       if resource is not None and platform.system() == "Linux" else None),
                   world_cpu_seconds=world_cpu, model_preparation_cpu_seconds=preparation_cpu,
                   inherited_training_cpu_seconds=training_process["total_cpu_seconds"],
                   inherited_training_internal_cpu_seconds=training["training_cpu_seconds"]),
        environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                         machine=platform.machine(), system=platform.system()))
    path = out / f"summary_{seed}_{domain}.json"
    save(path, result)
    print(json.dumps(dict(path=str(path), valid=counts["valid"], hmm_mismatches=counts["hmm_trace_mismatches"],
                          cpu=result["costs"]["worker_internal_cpu_seconds"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--domain", choices=("iid", "ood"), required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    run(args.seed, args.domain, args.development)
