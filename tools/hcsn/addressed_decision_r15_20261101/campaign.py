"""Predeclared training, immutable freeze, and one-use paired confirmation."""

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy

from .calibration import fit
from .execution import FEATURE_SETS, PATTERNS, learn_controllers, run_episode
from .law import Law
from .numerics_study import make_memoryless
from .planner import BeliefMemory, Planner, canonical
from .world import make_episode


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text())


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def save_new(path, value):
    """Exclusive creation prevents accidental reruns replacing a failed run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=str(path), sha256=digest(path), bytes=len(raw))


def check_source():
    manifest_path = HERE / "SOURCE_MANIFEST.json"
    manifest = read_json(manifest_path)
    for relative, expected in manifest["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen source changed: {relative}")
    return digest(manifest_path)


def episode_seed(fit_seed, phase, index, domain="iid"):
    # Disjoint from calibration's 11m/21m streams, and from every other phase.
    phase_id = {"policy": 1, "selection": 2, "confirmation": 3}[phase]
    return phase_id * 10**12 + fit_seed * 10**5 + (10000 if domain == "ood" else 0) + index


def _score(law, episodes, **options):
    records = [run_episode(law, episode, **options) for episode in episodes]
    return dict(utility=float(np.mean([r["utility"] for r in records])),
                reward=float(np.mean([r["reward"] for r in records])),
                cpu_seconds=sum(r["cpu_seconds"] for r in records), episodes=records)


def train(seed, run, source_commit, development=False):
    started, wall = time.process_time(), time.perf_counter()
    manifest_hash = check_source()
    if not development and seed not in PROTOCOL["seeds"]:
        raise ValueError("Unregistered formal fit seed")
    run = Path(run)
    if not development:
        publication = read_json(run / "SOURCE_PUBLICATION.json")
        if (not isinstance(source_commit, str) or not re.fullmatch("[0-9a-f]{40}", source_commit)
                or publication["source_commit"] != source_commit
                or publication["source_manifest_sha256"] != manifest_hash
                or not publication["remote_readback_verified"]):
            raise RuntimeError("Exact published and read-back source is required before training")
    save_new(run / "claims" / f"train_{seed}.json", dict(opened_at=utc(), seed=seed,
             source_commit=source_commit, source_manifest_sha256=manifest_hash,
             development=development))
    config = dict(true_theta=PROTOCOL["world_theta"],
                  train_count=PROTOCOL["calibration"]["train_sequences"],
                  validation_count=PROTOCOL["calibration"]["validation_sequences"],
                  sequence_length=PROTOCOL["calibration"]["length"],
                  max_evals=PROTOCOL["calibration"]["max_evals"],
                  cpu_seconds=PROTOCOL["calibration"]["max_cpu_seconds"])
    if development:
        config.update(train_count=4, validation_count=3, max_evals=6)
    calibrated = fit(seed, config)
    save_new(run / "calibration" / f"{seed}.json.gz", calibrated)
    if any(calibrated["models"][key]["payload"] is None for key in ("hx", "free")):
        save_new(run / "failures" / f"calibration_{seed}.json.gz", calibrated)
        raise RuntimeError("A declared candidate failed; no confirmation may open")
    laws = {key: Law.from_payload(calibrated["models"][key]["payload"])
            for key in ("hx", "free", "hmm_same_matrix")}
    world_started = time.process_time()
    owner = Law(theta=tuple(PROTOCOL["world_theta"]))
    selection_count = 3 if development else PROTOCOL["selection_episodes"]
    policy_count = 3 if development else PROTOCOL["policy_train_episodes"]
    selection = [make_episode(owner, episode_seed(seed, "selection", i), "iid")
                 for i in range(selection_count)]
    policy_training = [make_episode(owner, episode_seed(seed, "policy", i), "iid")
                       for i in range(policy_count)]
    world_cpu = time.process_time() - world_started
    selection_started = time.process_time()
    value_scores = {key: _score(laws[key], selection, policy="value")
                    for key in ("hmm_same_matrix", "free")}
    ordinary = max(value_scores, key=lambda key: value_scores[key]["utility"])
    fixed_scores = {}
    for pattern in PATTERNS:
        scores = {key: _score(laws[key], selection, policy="fixed", pattern=pattern)
                  for key in ("hx", ordinary)}
        fixed_scores[pattern] = dict(cores=scores, pooled_utility=float(np.mean(
            [score["utility"] for score in scores.values()])))
    light = max(fixed_scores, key=lambda key: fixed_scores[key]["pooled_utility"])
    selection_cpu = time.process_time() - selection_started
    learned = learn_controllers(laws["hx"], policy_training)
    if check_source() != manifest_hash:
        raise RuntimeError("Source changed during training")
    result = dict(schema="hcsn-r15-training-v1", seed=seed, development=development,
                  source_commit=source_commit, source_manifest_sha256=manifest_hash,
                  calibration=calibrated, ordinary_selected=ordinary, light_pattern=light,
                  learned=learned, selection_results=dict(value=value_scores, fixed=fixed_scores),
                  selection_cpu_seconds=selection_cpu, world_cpu_seconds=world_cpu,
                  policy_world_fingerprints=[ep.fingerprint for ep in policy_training],
                  selection_world_fingerprints=[ep.fingerprint for ep in selection],
                  training_cpu_seconds=time.process_time() - started,
                  training_wall_seconds=time.perf_counter() - wall, completed_at=utc())
    return save_new(run / "training" / f"{seed}.json.gz", result)


def freeze(run, source_commit, development=False):
    run = Path(run)
    manifest_hash = check_source()
    files = sorted((run / "training").glob("*.json.gz"))
    items = [read_json(path) for path in files]
    expected = sorted(item["seed"] for item in items) if development else sorted(PROTOCOL["seeds"])
    if sorted(item["seed"] for item in items) != expected or not items:
        raise RuntimeError("Every predeclared training seed is required before freezing")
    if any(item["source_commit"] != source_commit or
           item["source_manifest_sha256"] != manifest_hash or
           item["development"] != development for item in items):
        raise RuntimeError("Training provenance does not match this source freeze")
    return save_new(run / "FREEZE.json", dict(schema="hcsn-r15-freeze-v1", frozen_at=utc(),
        source_commit=source_commit, source_manifest_sha256=manifest_hash,
        protocol_sha256=digest(HERE / "PROTOCOL.json"), development=development,
        training={path.name: digest(path) for path in files},
        selections={str(item["seed"]): dict(ordinary=item["ordinary_selected"],
                     fixed=item["light_pattern"]) for item in items},
        confirmation_domains=["iid", "ood"],
        confirmation_count=2 if development else PROTOCOL["confirmation_episodes_per_fit_domain"]))


def _arms(training, domain):
    models = training["calibration"]["models"]
    ordinary = training["ordinary_selected"]
    specs = {"A": (ordinary, dict(policy="fixed", pattern=training["light_pattern"])),
             "B": (ordinary, dict(policy="value")),
             "C": ("hx", dict(policy="fixed", pattern=training["light_pattern"])),
             "D": ("hx", dict(policy="value")),
             "hmm_same_matrix": ("hmm_same_matrix", dict(policy="value")),
             "free_value": ("free", dict(policy="value")),
             "factorized_value": ("hx", dict(policy="value", projection="factorized")),
             "mean_value": ("hx", dict(policy="value", projection="mean")),
             "memoryless_value": ("hx", dict(policy="value"))}
    for kind in FEATURE_SETS:
        specs[f"learned_{kind}"] = ("hx", dict(policy="learned",
                                      learned=training["learned"]["models"][kind]))
    result = {}
    for name, (model, options) in specs.items():
        started = time.process_time()
        law = Law.from_payload(models[model]["payload"])
        if name == "memoryless_value":
            law = make_memoryless(law)
        for dt in PROTOCOL[f"{domain}_dt"]:
            Planner(law, dt, projection=options.get("projection", "full"))
        result[name] = dict(law=law, options=options,
                            preparation_cpu=time.process_time() - started,
                            checkpoint_io_cpu=0., checkpoint_io_wall=0., episodes=[])
    return result


def _world_archive(episode):
    # This scorer-owned archive is written after construction; never given to actors.
    return dict(seed=episode.seed, domain=episode.domain, fingerprint=episode.fingerprint,
                initial_values=episode.initial_values.tolist(), query_keys=episode.query_keys.tolist(),
                dts=episode.dts.tolist(), deadlines=episode.deadlines.tolist(),
                public_events=[episode.events_at(q) for q in range(len(episode.query_keys))],
                paths=[dict(times=t.tolist(), states=s.tolist()) for t, s in episode._paths])


def confirm(seed, domain, run, freeze_commit, development=False):
    started, wall = time.process_time(), time.perf_counter()
    run = Path(run)
    frozen = read_json(run / "FREEZE.json")
    if domain not in frozen["confirmation_domains"]:
        raise ValueError("Unregistered confirmation domain")
    if not development:
        publication = read_json(run / "FREEZE_PUBLICATION.json")
        if (not isinstance(freeze_commit, str) or not re.fullmatch("[0-9a-f]{40}", freeze_commit)
                or publication["freeze_commit"] != freeze_commit
                or publication["freeze_sha256"] != digest(run / "FREEZE.json")
                or not publication["remote_readback_verified"]):
            raise RuntimeError("Published and read-back fitted freeze is required before confirmation")
    if (frozen["development"] != development or
            frozen["source_manifest_sha256"] != check_source() or
            frozen["protocol_sha256"] != digest(HERE / "PROTOCOL.json")):
        raise RuntimeError("Frozen protocol/source identity mismatch")
    training_path = run / "training" / f"{seed}.json.gz"
    if digest(training_path) != frozen["training"][training_path.name]:
        raise RuntimeError("Frozen fitted model or selection changed")
    training = read_json(training_path)
    opened = utc()
    save_new(run / "claims" / f"confirm_{seed}_{domain}.json", dict(
        opened_at=opened, freeze_commit=freeze_commit, freeze_sha256=digest(run / "FREEZE.json"),
        source_commit=frozen["source_commit"], seed=seed, domain=domain, development=development))
    arms = _arms(training, domain)
    world_started = time.process_time()
    owner = Law(theta=tuple(PROTOCOL["world_theta"]))
    world_cpu = time.process_time() - world_started
    tapes = []
    for index in range(frozen["confirmation_count"]):
        world_started = time.process_time()
        episode = make_episode(owner, episode_seed(seed, "confirmation", index, domain), domain)
        tapes.append(_world_archive(episode))
        world_cpu += time.process_time() - world_started
        names = list(arms)
        shift = (seed + index) % len(names)
        names = names[shift:] + names[:shift]
        for name in names:
            arm = arms[name]
            record = run_episode(arm["law"], episode, capture_states=(index == 0), **arm["options"])
            if index == 0:
                checkpoint = record["states"][-1]
                io_cpu, io_wall = time.process_time(), time.perf_counter()
                path = run / "checkpoints" / f"{seed}_{domain}_{name}.json"
                save_new(path, checkpoint)
                restored = BeliefMemory.restore(arm["law"], read_json(path))
                if restored.checkpoint() != checkpoint:
                    raise RuntimeError("Belief checkpoint disk roundtrip changed state")
                arm["checkpoint_io_cpu"] = time.process_time() - io_cpu
                arm["checkpoint_io_wall"] = time.perf_counter() - io_wall
            arm["episodes"].append(record)
        # Same law, same controller, same observations must agree, independently executed.
        if arms["D"]["episodes"][-1]["queries"] != arms["hmm_same_matrix"]["episodes"][-1]["queries"]:
            raise RuntimeError("Same-matrix HMM equivalence failed")
    output_arms = {name: {**{key: value for key, value in item.items() if key not in ("law", "options")},
                         "model_identity": item["law"].identity,
                         "cpu_seconds": sum(r["cpu_seconds"] for r in item["episodes"])}
                   for name, item in arms.items()}
    if check_source() != frozen["source_manifest_sha256"]:
        raise RuntimeError("Source changed during confirmation")
    result = dict(schema="hcsn-r15-confirmation-v1", seed=seed, domain=domain,
                  development=development, count=frozen["confirmation_count"], arms=output_arms,
                  source_commit=frozen["source_commit"], freeze_commit=freeze_commit,
                  freeze_sha256=digest(run / "FREEZE.json"), opened_at=opened, completed_at=utc(),
                  world_cpu_seconds=world_cpu, world_tapes=tapes,
                  worker_cpu_seconds=time.process_time() - started,
                  worker_wall_seconds=time.perf_counter() - wall,
                  environment=dict(python=platform.python_version(), numpy=np.__version__,
                                   scipy=scipy.__version__, platform=platform.platform()))
    return save_new(run / "confirmation" / f"{seed}_{domain}.json.gz", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("train", "freeze", "confirm"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--domain", choices=("iid", "ood"))
    parser.add_argument("--source-commit")
    parser.add_argument("--freeze-commit")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if args.command == "train":
        result = train(args.seed, args.run, args.source_commit, args.development)
    elif args.command == "freeze":
        result = freeze(args.run, args.source_commit, args.development)
    else:
        result = confirm(args.seed, args.domain, args.run, args.freeze_commit, args.development)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
