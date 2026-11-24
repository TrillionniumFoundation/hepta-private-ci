"""Measure complete local update episodes on the retained MiniLM/teacher data."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import runpy
import statistics
import sys
import tempfile
import time
import zipfile

import numpy as np
import torch

from resident import FeatureCache, RecursiveRidge, direct

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import encoder
import panel


def bp_fit(x, y, initial):
    X, Y = torch.from_numpy(x), torch.from_numpy(y)
    w = torch.tensor(initial, dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([w], max_iter=256, max_eval=320, history_size=50,
                            tolerance_grad=1e-9, tolerance_change=1e-14,
                            line_search_fn="strong_wolfe")
    calls = 0

    def closure():
        nonlocal calls
        calls += 1
        opt.zero_grad()
        loss = ((X @ w - Y).square().sum() + .2 * w.square().sum()) / 2
        loss.backward()
        return loss

    opt.step(closure)
    return w.detach().numpy().copy(), calls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    model, output = args.model.resolve(), args.output.resolve()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    clock = time.perf_counter
    archive = ROOT / "evidence/encoder-run.zip"
    assert encoder.file_sha(archive) == "84b379a59d454e22009b434c254628e56e023467366ca9bde237df469154ffe0"
    prep_start = clock()
    # The original fit supplies the unchanged teacher residuals and row order.
    # It does not see the confirmation seed until after its fit has completed.
    with tempfile.TemporaryDirectory(prefix="resident-", dir=ROOT.parent) as folder:
        previous_cwd, previous_argv = Path.cwd(), sys.argv
        try:
            os.chdir(folder)
            Path("work").mkdir()
            with zipfile.ZipFile(archive) as z:
                for name in ("teacher-fit-smol.json", "teacher-fit-t5.json"):
                    Path("work", name).write_bytes(z.read(name))
                sys.argv = [str(ROOT / "fit.py"), str(model)]
                ctx = runpy.run_path(str(ROOT / "fit.py"))
                rows = ctx["train"]
                targets = (ctx["ys"]["t5"] + ctx["ys"]["smol"]) / 2
                published = np.load(io.BytesIO(z.read("heads.npz")), allow_pickle=False)
                parent = published["parent"].copy()
                blind = json.loads(z.read("blind.json"))
                original = json.loads(z.read("cold-mix.json"))["rows"]
                original_parent = json.loads(z.read("cold-parent.json"))["rows"]
                Path("work/confirmation-seed.json").write_bytes(z.read("confirmation-seed.json"))
                labeled = {r["id"]: r for r in panel.panel()}
            del ctx
        finally:
            os.chdir(previous_cwd)
            sys.argv = previous_argv
    preparation_seconds = clock() - prep_start
    torch.set_num_threads(1)  # fit.py deliberately uses two threads only for preparation
    labels = np.array([labeled[r["id"]]["label"] for r in blind])
    subsets = {split: np.array([labeled[r["id"]]["split"] == split for r in blind])
               for split in ("holdout", "old-test", "composition")}
    parent_answers = np.array([r["answer"] for r in original_parent])
    assert [r["id"] for r in original] == [r["id"] for r in blind]
    assert [r["id"] for r in original_parent] == [r["id"] for r in blind]
    encoder_identity = json.loads((model / "identity.json").read_bytes())
    identity = panel.digest({"encoder": encoder_identity, "features": encoder.file_sha(ROOT / "encoder.py")})
    sources = {p.name: encoder.file_sha(p) for p in (Path(__file__), Path(__file__).with_name("resident.py"))}
    parent_sha = hashlib.sha256(parent.tobytes()).hexdigest()
    # Warm imports equally; optimization itself remains inside each episode timer.
    bp_fit(np.ones((1, 1)), np.ones(1), np.zeros(1))
    records, episodes = [], []
    methods = ("reload_direct", "resident_direct", "resident_rls", "resident_bp")
    for repeat in range(3):
        order = methods[repeat:] + methods[:repeat]
        for method in order:
            episode_start, cpu_start = clock(), time.process_time()
            E = cache = recursive = None
            weights = np.zeros(1152)
            encoder_inputs = 0
            with tempfile.TemporaryDirectory(prefix="hepta-readout-") as destination:
                for step, stop in enumerate(range(224, 449, 32)):
                    started = clock()
                    phases = {}
                    before = clock()
                    if E is None or method == "reload_direct":
                        E = encoder.Encoder(model)
                        if method != "reload_direct":
                            cache = FeatureCache(E, identity)
                    phases["load"] = clock() - before
                    before = clock()
                    indexes = list(range(stop)) + list(range(448, 464))
                    fetch = cache.features if cache else E.features
                    count_before = E.presentations
                    x, _, cosine = fetch([rows[i] for i in indexes])
                    hx, _, hc = fetch(blind)
                    encoder_inputs += E.presentations - count_before
                    y = targets[indexes] - cosine - x @ parent
                    phases["features"] = clock() - before
                    before = clock()
                    calls = 0
                    if method == "resident_bp":
                        weights, calls = bp_fit(x, y, weights)
                    elif method == "resident_rls":
                        if recursive is None:
                            bx = np.concatenate((x[:192], x[-16:]))
                            by = np.concatenate((y[:192], y[-16:]))
                            recursive = RecursiveRidge(bx, by)
                        weights = recursive.append(x[stop-32:stop], y[stop-32:stop])
                    else:
                        weights = direct(x, y)
                    phases["fit"] = clock() - before
                    before = clock()
                    residual = x @ weights - y
                    gradient = x.T @ residual + .2 * weights
                    stationarity = float(np.linalg.norm(gradient) / max(np.linalg.norm(x.T @ y), 1e-15))
                    answers = (hc + hx @ (parent + weights) > 0).astype(int)
                    quality = {split: int(((answers == labels) & mask).sum())
                               for split, mask in subsets.items()}
                    quality["lost_old_parent_passes"] = int(((parent_answers == labels) &
                        (answers != labels) & subsets["old-test"]).sum())
                    phases["diagnose_and_verify"] = clock() - before
                    before = clock()
                    path = Path(destination) / f"attempt-{step}.npz"
                    np.savez(path, weights=weights)
                    manifest = {"parent_weights_sha256": parent_sha, "encoder_identity": identity,
                                "weights_sha256": encoder.file_sha(path), "sources": sources,
                                "scope": "retrospective_local_attempt", "adopted": False}
                    manifest_path = path.with_suffix(".json")
                    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
                    disk_manifest = json.loads(manifest_path.read_bytes())
                    assert disk_manifest["weights_sha256"] == encoder.file_sha(path)
                    with np.load(path, allow_pickle=False) as artifact:
                        recovered = artifact["weights"]
                    assert np.array_equal(answers, (hc + hx @ (parent + recovered) > 0).astype(int))
                    phases["local_write_hash_reload"] = clock() - before
                    total = clock() - started
                    records.append(dict(repeat=repeat, method=method, step=step, rows=len(x),
                        seconds=total, phases=phases, backward_calls=calls, stationarity=stationarity,
                        quality=quality, answers=answers.tolist(), weights_sha256=hashlib.sha256(weights.tobytes()).hexdigest()))
                episodes.append(dict(repeat=repeat, method=method, seconds=clock() - episode_start,
                    cpu_seconds=time.process_time()-cpu_start, encoder_inputs=encoder_inputs,
                    cache_hits=cache.hits if cache else 0, cache_misses=cache.misses if cache else 0))
            print("EPISODE", json.dumps(episodes[-1]), flush=True)
    reference = {r["step"]: r["answers"] for r in records if r["repeat"] == 0 and r["method"] == "reload_direct"}
    equal = all(r["answers"] == reference[r["step"]] for r in records)
    same_published = sum(a == r["answer"] for a, r in zip(reference[7], original, strict=True))
    medians = {m: statistics.median(r["seconds"] for r in episodes if r["method"] == m) for m in methods}
    report = dict(schema="hepta.resident-readout-measurement.v1", sources=sources,
        original_archive_sha256=encoder.file_sha(archive), frozen_encoder=encoder_identity,
        parent_weights_sha256=parent_sha, torch=torch.__version__, numpy=np.__version__, cpu=platform.machine(),
        torch_threads=torch.get_num_threads(), preparation_seconds=preparation_seconds,
        episodes=episodes, episode_median_seconds=medians, records=records,
        all_incremental_predictions_equal=equal, final_matches_published=same_published,
        local_measurement_pass=equal and same_published == len(blind) and
            all(r["stationarity"] < 1e-6 for r in records),
        real_participants=0, new_blind_tasks=0, adopted_improvements=0,
        production_end_to_end_seconds=None, utility_per_total_cost=None,
        excludes=["teacher label acquisition", "model download", "network distribution",
                  "independent user adoption", "chain settlement"],
        status="HISTORICAL_ENGINEERING_MEASUREMENT_ONLY")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("SUMMARY", json.dumps({k: report[k] for k in ("episode_median_seconds", "all_incremental_predictions_equal", "final_matches_published", "local_measurement_pass")}))
    if not report["local_measurement_pass"]:
        raise SystemExit("Same-quality measurement failed; preserve this output")


if __name__ == "__main__":
    main()
