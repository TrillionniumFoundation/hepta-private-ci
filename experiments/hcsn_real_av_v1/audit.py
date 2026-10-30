"""Outcome-free data checks, train-only integration preflight and immutable seal."""

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np

from .data import digest, write_json


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEPENDENCIES = (
    "experiments/hcsn_distributional_v2/model.py",
    "experiments/hcsn_distributional_v2/distribution_kernel.py",
    "experiments/hcsn_free_boundary_v1/model.py",
    "experiments/hcsn_free_boundary_v1/oracle_torch.py",
    "experiments/continuous_spiking_network/baseline.py",
    "experiments/continuous_spiking_network/BASELINES.md",
)


def sources():
    paths = list(HERE.glob("*.py")) + [HERE / "PROTOCOL.json"]
    paths += [ROOT / name for name in DEPENDENCIES]
    for package in (ROOT / "experiments", *(ROOT / name.rsplit("/", 1)[0] for name in DEPENDENCIES)):
        if (package / "__init__.py").is_file():
            paths.append(package / "__init__.py")
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def audit_data(cache, output):
    manifest = json.loads((HERE / "data/MANIFEST.json").read_text())
    dataset = json.loads((HERE / "data/DATASET.json").read_text())
    plan = json.loads((HERE / "data/COHORT_PLAN.json").read_text())
    receipt = json.loads((HERE / "data/DECODE.json").read_text())
    assert dataset["manifest_sha256"] == digest(HERE / "data/MANIFEST.json")
    assert dataset["decoder_sha256"] == digest(HERE / "data.py")
    assert dataset["decode_receipt_sha256"] == digest(HERE / "data/DECODE.json")
    assert dataset["normalization_sha256"] == digest(HERE / "data/normalization.npz")
    assert manifest["cohort_plan_sha256"] == digest(HERE / "data/COHORT_PLAN.json")
    with np.load(HERE / "data/normalization.npz", allow_pickle=False) as norm:
        scales = dict(audio=norm["scale"][0, 0, 0], video=norm["scale"][0, 1, 0])
    records = manifest["records"]
    assert len(records) == len({r["clip"] for r in records}) == 720
    actors, clips, results = {}, {}, {}
    decoded = {r["clip"]: r for r in receipt["records"]}
    for split, expected_size in (("train", 480), ("validation", 120), ("test", 120)):
        row = dataset["splits"][split]
        path = HERE / "data" / row["path"]
        assert digest(path) == row["sha256"]
        expected = [r for r in records if r["split"] == split]
        with np.load(path, allow_pickle=False) as z:
            assert np.array_equal(z["clip"], [r["clip"] for r in expected])
            assert np.array_equal(z["actor"], [r["actor"] for r in expected])
            assert np.array_equal(z["y"], [r["label"] for r in expected])
            actors[split], clips[split] = set(z["actor"].tolist()), set(z["clip"].tolist())
            assert actors[split] == set(plan["splits"][split])
            for modality in ("audio", "video"):
                x = z[modality]
                assert x.shape == (expected_size, 32, 128) and x.dtype == np.float32
                assert np.isfinite(x).all()
                if split == "train":
                    mean, std = x.astype(np.float64).mean((0, 1)), x.astype(np.float64).std((0, 1))
                    assert np.abs(mean).max() < 1e-5
                    regular = scales[modality] > 1e-5
                    assert np.abs(std[regular] - 1).max(initial=0) < 1e-5
                    assert std[~regular].max(initial=0) <= 1 + 1e-5
            assert np.isfinite(z["dt"]).all() and (z["dt"] > 0).all()
            duration = np.array([decoded[r["clip"]]["duration_seconds"] for r in expected])
            assert np.allclose(z["dt"].sum(1), 10 * duration, rtol=2e-6, atol=1e-6)
            assert np.array_equal(np.bincount(z["y"]), np.full(6, expected_size // 6))
            results[split] = dict(clips=expected_size, actors=len(actors[split]), sha256=row["sha256"])
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        assert not actors[a] & actors[b] and not clips[a] & clips[b]
    for r in records:
        media = cache / "media" / (r["clip"] + ".flv")
        assert media.stat().st_size == r["bytes"] and digest(media) == r["sha256"]
        assert decoded[r["clip"]]["audio_samples"] > 0 and decoded[r["clip"]]["video_frames"] > 1
    write_json(output, dict(passed=True, scope="Fixed integrity/shape/normalization checks; no model evaluation",
        source_sha256=sources(), splits=results, media_count=720,
        media_bytes=sum(r["bytes"] for r in records), paired_source="same verified original FLV"))


def preflight(output):
    import torch
    from .study import PairEncoder, load_split, objective

    if output.exists():
        raise FileExistsError("Preserve the original train-only preflight")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started = time.process_time()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    dataset = json.loads((HERE / "data/DATASET.json").read_text())
    train_path = HERE / "data" / dataset["splits"]["train"]["path"]
    report = dict(passed=False, train_only=True, accessed_tensor=str(train_path.relative_to(ROOT)),
        train_sha256=digest(train_path), source_sha256=sources(), torch=torch.__version__, models=[])
    try:
        data = load_split(train_path, dataset["splits"]["train"]["sha256"])
        ids = torch.argsort(data["dt"].sum(1), descending=True, stable=True)[:8]
        report.update(indices=ids.tolist(), max_train_dt=float(data["dt"].max()),
                      max_train_total_dt=float(data["dt"].sum(1).max()))
        for name in protocol["models"]:
            model = PairEncoder(name, 9401)
            optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
            updates = []
            for _ in range(2):
                before = {id(p): p.detach().clone() for p in model.parameters()}
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model(data["audio"][ids], data["video"][ids], data["dt"][ids]),
                                 data["y"][ids], protocol["temperature"])
                assert bool(torch.isfinite(loss))
                loss.backward()
                assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
                gradients = {k: sum(float(p.grad.square().sum()) for _, p in v)**.5
                             for k, v in model.groups().items()}
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
                optimizer.step()
                changes = {k: sum(float((p.detach()-before[id(p)]).square().sum()) for _, p in v)**.5
                           for k, v in model.groups().items()}
                assert all(v > 0 for v in gradients.values()) and all(v > 0 for v in changes.values())
                updates.append(dict(loss=float(loss.detach()), gradients=gradients, changes=changes))
            report["models"].append(dict(model=name, audio_counts=model.audio.counts(),
                video_counts=model.video.counts(), total_parameters=sum(p.numel() for p in model.parameters()),
                probability_checks=model.probability_checks, updates=updates))
            print(json.dumps(dict(preflight=name, passed=True)), flush=True)
            del model, optimizer, before, loss
            gc.collect()
        assert sources() == report["source_sha256"]
        report["passed"] = True
    except Exception as error:
        report.update(error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        raise
    finally:
        report.update(cpu_seconds=time.process_time()-started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        write_json(output, report)


def freeze():
    for filename in ("DATA_AUDIT.json", "PREFLIGHT.json"):
        receipt = json.loads((HERE / filename).read_text())
        if not receipt["passed"] or receipt["source_sha256"] != sources():
            raise ValueError("Data audit and train-only preflight must pass the exact source closure")
    paths = {ROOT / p for p in sources()}
    paths.update(HERE / p for p in ("README.md", "DATA_AUDIT.json", "PREFLIGHT.json"))
    paths.update(p for p in (HERE / "data").iterdir() if p.is_file())
    files = [dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size, sha256=digest(p))
             for p in sorted(paths)]
    write_json(HERE / "FREEZE.json", dict(schema="hcsn-real-av-freeze-v1", files=files,
        sealed_utc=datetime.now(timezone.utc).isoformat(),
        no_test_model_evaluation=True,
        upstream_commit=json.loads((HERE / "data/MANIFEST.json").read_text())["commit"],
        source_revision_scope="Exact original v2 physical model/kernel hashes; no probability-helper substitution",
        publication_gate="Publish this seal before registered training/heldout evaluation"))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("data", "preflight", "freeze", "verify"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path, help="Fresh receipt path for data/preflight rechecks")
    args = parser.parse_args()
    if args.command == "data":
        if args.cache is None:
            parser.error("--cache is required for raw-media integrity checking")
        audit_data(args.cache, args.output or HERE / "DATA_AUDIT.json")
    elif args.command == "preflight":
        preflight(args.output or HERE / "PREFLIGHT.json")
    elif args.command == "freeze":
        freeze()
    else:
        seal = json.loads((HERE / "FREEZE.json").read_text())
        for row in seal["files"]:
            assert digest(ROOT / row["path"]) == row["sha256"], row["path"]
        print(json.dumps(dict(passed=True, frozen_files=len(seal["files"]),
                              freeze_sha256=digest(HERE / "FREEZE.json"))))


if __name__ == "__main__":
    main()
