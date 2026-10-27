"""Bounded provenance and source-cluster uncertainty for the new studies."""
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cpu_now():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


def paired_ci(rows, treatment, control, key, cluster, seed=2811):
    identities = sorted({r["id"] for r in rows})
    differences = []
    for identity in identities:
        selected = [r for r in rows if r["id"] == identity]
        a, b = ([r for r in selected if r["arm"] == arm] for arm in (treatment, control))
        if not a or len(a) != len(b):
            raise ValueError("Missing paired comparison or repetition")
        differences.append((a[0][cluster], float(np.mean([r[key] for r in a]) - np.mean([r[key] for r in b]))))
    groups = sorted({g for g, _ in differences})
    values = np.array([np.mean([v for g, v in differences if g == group]) for group in groups])
    rng = np.random.default_rng(seed)
    samples = values[rng.integers(len(values), size=(5000, len(values)))].mean(1)
    return {"difference": float(values.mean()), "CI95": np.quantile(samples, [.025, .975]).tolist(),
        "independent_source_clusters": len(groups), "source_level_differences": dict(zip(map(str, groups), values.tolist()))}


def freeze(source, assets, output, protocol, extra=None):
    """Write exact executed sources and inputs before held-out generation."""
    destination = output / "executed-source"
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for path in sorted(source.glob("*.py")):
        (destination / path.name).write_bytes(path.read_bytes())
        files.append({"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size})
    record = {"registered_ns": time.time_ns(), "assets_sha256": sha(assets), "protocol": protocol,
        "source_files": files, "source_snapshot": str(destination), "heldout_generation_not_started": True,
        **(extra or {})}
    save(output / "FROZEN_REGISTRATION.json", record)
    return record


def verify_frozen(record):
    for row in record["source_files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Executed source changed during the study")


def summarize_quality(rows, arms, quality_keys, cluster, comparisons):
    summary = {}
    for arm in arms:
        chosen = [r for r in rows if r["arm"] == arm]
        summary[arm] = {key: float(np.mean([r[key] for r in chosen])) for key in quality_keys}
        summary[arm].update(records=len(chosen), sources=len({r[cluster] for r in chosen}))
    contrasts = {}
    for treatment, control in comparisons:
        contrasts[treatment + "__minus__" + control] = {
            key: paired_ci(rows, treatment, control, key, cluster) for key in quality_keys}
    return {"summary": summary, "comparisons": contrasts}
