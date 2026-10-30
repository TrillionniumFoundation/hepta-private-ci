"""A data-free freeze and hard scientific prerequisite, without importing JAX."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MEMORY = ROOT / "third/memory"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def verify():
    record = json.loads((HERE / "freeze.json").read_text())
    for path, digest in record["source_sha256"].items():
        if sha(ROOT / path) != digest:
            raise RuntimeError("Confirmation source changed: " + path)
    if sha(MEMORY / "freeze.json") != record["development_freeze_sha256"]:
        raise RuntimeError("Development scientific identity changed")
    return record


def require_development():
    record = verify()
    result_path = MEMORY / "development_results.json"
    result = json.loads(result_path.read_text())
    if result["freeze_sha256"] != record["development_freeze_sha256"]:
        raise RuntimeError("Development result belongs to another freeze")
    if not result.get("complete") or not result.get("development_gate", {}).get("passed"):
        raise RuntimeError("Confirmation is blocked until the complete development gate passes")
    return dict(development_result_sha256=sha(result_path),
                development_freeze_sha256=record["development_freeze_sha256"],
                development_runs=len(result["runs"]), development_gate=result["development_gate"],
                confirmation_freeze_sha256=sha(HERE / "freeze.json"))


def freeze():
    target = HERE / "freeze.json"
    if target.exists():
        return verify()
    protocol = json.loads((HERE / "protocol.json").read_text())
    previous = json.loads((MEMORY / "freeze.json").read_text())
    for name, digest in previous["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("Cannot bind a changed development source: " + name)
    # Read metadata only. No make_data call, PRNG draw or model initialization.
    historical_seeds = set()
    examined = []
    def collect(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                collect(item, name)
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif "seed" in key.lower() and isinstance(value, int) and not isinstance(value, bool):
            historical_seeds.add(value)
    for path in sorted(ROOT.rglob("*.json")):
        if HERE in path.parents:
            continue
        try:
            collect(json.loads(path.read_text()))
            examined.append(str(path.relative_to(ROOT)))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    proposed = set(protocol["seeds"])
    for task_index in range(len(protocol["tasks"])):
        for seed in protocol["seeds"]:
            base = protocol["data_seed_base"] + task_index * protocol["data_task_offset"] + 1000 * seed
            proposed.update(base + n for n in (8, 16, 32, 201, 332, 364, 428, 812, 1001, 1002, 1003))
            proposed.add(protocol["initialization_seed_base"] + task_index * protocol["parameter_task_offset"] + seed)
            proposed.add(protocol["optimizer_seed_base"] + task_index * protocol["parameter_task_offset"] + seed)
            proposed.add(protocol["optimizer_seed_base"] + task_index * protocol["parameter_task_offset"] + seed + 50000)
    overlap = proposed & historical_seeds
    if overlap:
        raise RuntimeError("Known seed namespace collision: " + str(sorted(overlap)))
    paths = set(previous["source_sha256"])
    paths.update(str(p.relative_to(ROOT)) for p in HERE.glob("*.py"))
    paths.add("third/confirmation/protocol.json")
    paths.add("third/confirmation/README.md")
    paths.add("third/memory/operational_driver.py")
    paths.update(str(p.relative_to(ROOT)) for p in ROOT.rglob("*protocol*.json") if HERE not in p.parents)
    result = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        development_freeze_sha256=sha(MEMORY / "freeze.json"),
        source_sha256={p: sha(ROOT / p) for p in sorted(paths)},
        seed_audit=dict(metadata_files=len(examined), explicit_historical_seed_values=len(historical_seeds),
                        known_collisions=[], proposed_seed_values=sorted(proposed),
                        scope="All existing JSON seed fields; generated-input freshness is separately required after the gate"),
        no_confirmation_data_constructed=True, no_confirmation_training_started=True)
    atomic_json(target, result)
    return result


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
