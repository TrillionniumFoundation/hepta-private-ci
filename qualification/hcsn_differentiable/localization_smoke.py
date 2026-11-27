"""Acquire/audit real UCI events; optionally run a bounded two-model interface smoke.

Default mode needs only the standard library. User research authorization already
exists; this separate smoke never grants formal-comparison or fidelity credit.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import sys
import time
from urllib.request import urlopen
from zipfile import ZipFile

URL = "https://archive.ics.uci.edu/static/public/196/localization%2Bdata%2Bfor%2Bperson%2Bactivity.zip"
TAGS = ("010-000-024-033", "010-000-030-096", "020-000-033-111", "020-000-032-221")
LABELS = ("walking", "falling", "lying down", "lying", "sitting down", "sitting",
          "standing up from lying", "on all fours", "sitting on the ground",
          "standing up from sitting", "standing up from sitting on the ground")
SPEC = {"train": ["A01", 128], "dev": ["D01", 64], "test_used": False,
        "seed": 20261108, "updates_per_arm": 4, "window_events": 32, "threads": 1,
        "arms": ["gru", "hcsn"], "dtype": "float64", "max_dt_seconds": .1,
        "active_cells": 6, "phase_cells": 3, "quadrature_order": 8, "content_width": 4,
        "physics_trainable": False, "optimizer": "Adam", "learning_rate": .001,
        "gradient_norm_cap": 1., "wall_budget_seconds": 180, "rss_budget_bytes": 2**30,
        "download_timeout_seconds": 30, "max_archive_bytes": 16 * 2**20,
        "max_expanded_bytes": 32 * 2**20, "relative_clock_tolerance_seconds": .002}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
    return sha(data)


def source_hashes():
    return {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}


def peak_rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def acquire(output, archive, report, check):
    acquisition = {"official_url": URL, "mode": "supplied_archive" if archive else "https_download",
                   "origin_receipt_required": bool(archive), "bytes": 0}
    report["acquisition"] = acquisition
    source = archive.open("rb") if archive else urlopen(URL, timeout=SPEC["download_timeout_seconds"])
    temporary = output / "archive.partial"
    with source, temporary.open("xb") as target:
        acquisition["resolved_url"] = source.geturl() if not archive else None
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            acquisition["bytes"] += len(chunk)
            if acquisition["bytes"] > SPEC["max_archive_bytes"]:
                raise ValueError("archive exceeds the fixed download budget")
            target.write(chunk)
            check()
    saved = output / "official-localization.zip"
    temporary.rename(saved)
    acquisition["archive_sha256"] = sha(saved.read_bytes())
    with ZipFile(saved) as zipped:
        members = [item for item in zipped.infolist() if not item.is_dir()]
        if sum(item.file_size for item in members) > SPEC["max_expanded_bytes"]:
            raise ValueError("ZIP exceeds the fixed expansion budget")
        acquisition["members"] = []
        data_members = []
        for item in members:
            data = zipped.read(item)
            acquisition["members"].append({"name": item.filename, "bytes": len(data),
                                            "sha256": sha(data)})
            if Path(item.filename).name == "ConfLongDemo_JSI.txt":
                data_members.append(data)
            check()
        if len(data_members) != 1:
            raise ValueError("expected exactly one ConfLongDemo_JSI.txt ZIP member")
        return data_members[0]


def parse_data(data, report, check):
    groups, labels, tags = defaultdict(list), Counter(), Counter()
    valid_sequences = {f"{subject}0{index}" for subject in "ABCDE" for index in range(1, 6)}
    progress = report["dataset"] = {"data_sha256": sha(data), "rows_parsed": 0, "verified": False}
    for line, row in enumerate(csv.reader(io.StringIO(data.decode("utf-8"))), 1):
        if not row:
            continue
        if len(row) != 8 or row[0] not in valid_sequences or row[1] not in TAGS or row[7] not in LABELS:
            raise ValueError(f"unexpected eight-column sequence/tag/activity schema at line {line}")
        tick, xyz = int(row[2]), tuple(float(value) for value in row[4:7])
        date = datetime.strptime(row[3], "%d.%m.%Y %H:%M:%S:%f")
        calendar_us = ((date.toordinal() * 86400 + date.hour * 3600 + date.minute * 60
                        + date.second) * 1000000 + date.microsecond)
        if tick <= 0 or not all(math.isfinite(value) for value in xyz):
            raise ValueError(f"invalid timestamp/position at line {line}")
        groups[row[0]].append((tick, calendar_us, TAGS.index(row[1]), *xyz, LABELS.index(row[7]), line))
        labels[row[7]] += 1
        tags[row[1]] += 1
        progress["rows_parsed"] += 1
        if line % 4096 == 0:
            check()
    if progress["rows_parsed"] != 164860 or set(groups) != valid_sequences:
        raise ValueError("full dataset does not match the official 164860 rows / 25 sequences")
    scales = (1., .001, .000001, .0000001, .000000001)
    residuals, gaps, sequences = {str(scale): 0. for scale in scales}, [], {}
    for sequence, rows in sorted(groups.items()):
        backwards = sum(b[0] < a[0] for a, b in zip(rows, rows[1:]))
        rows.sort(key=lambda item: (item[0], item[7]))
        local_gaps = []
        for left, right in zip(rows, rows[1:]):
            delta, calendar_delta = right[0] - left[0], (right[1] - left[1]) / 1000000
            for scale in scales:
                key = str(scale)
                residuals[key] = max(residuals[key], abs(delta * scale - calendar_delta))
            local_gaps.append(delta * .0000001)
        gaps.extend(local_gaps)
        sequences[sequence] = {"events": len(rows), "source_backward_pairs": backwards,
                               "duplicate_timestamps": len(rows) - len({r[0] for r in rows}),
                               "max_gap_seconds_at_candidate_scale": max(local_gaps)}
        check()
    matches = [scale for scale in scales if residuals[str(scale)] <= SPEC["relative_clock_tolerance_seconds"]]
    gaps.sort()
    progress.update(sequences=sequences, labels=dict(labels), tags=dict(tags),
                    clock_candidate_max_residual_seconds=residuals,
                    timestamp_unit_verified=matches == [.0000001],
                    candidate_seconds_per_tick=.0000001,
                    gap_quantiles_seconds={str(q): gaps[round(q * (len(gaps) - 1))] for q in (.5, .95, .99, 1.)},
                    holdout_use="E only integrity/schema/clock audit; no frontend fit, windows, optimization or model evaluation")
    if matches != [.0000001] or set(labels) != set(LABELS) or set(tags) != set(TAGS):
        raise ValueError("timestamp unit or complete label/tag schema remains unverified")
    progress["verified"] = True
    return groups


def frontend(groups, output, report):
    selected = {part: groups[sequence][:count] for part, (sequence, count) in
                ((part, SPEC[part]) for part in ("train", "dev"))}
    columns = [[] for _ in range(12)]
    for row in selected["train"]:
        for axis in range(3):
            columns[row[2] * 3 + axis].append(row[3 + axis])
    means = [sum(values) / len(values) if values else 0. for values in columns]
    stds = [max(math.sqrt(sum((x - means[i]) ** 2 for x in values) / len(values)), 1e-6)
            if values else 1. for i, values in enumerate(columns)]
    norm = {"fit_sequence": "A01", "fit_rows": [r[7] for r in selected["train"]],
            "mean": means, "scale": stds, "observed_counts": list(map(len, columns)),
            "tag_order": TAGS, "feature_order": "12 normalized values, 12 masks, log1p(dt_seconds)",
            "unseen_training_coordinate": "mean=0, scale=1; never fit on development data"}
    report["frontend_sha256"] = write_json(output / "frontend.json", norm)
    features, selection = {}, {}
    for part, rows in selected.items():
        x, dt = [], [0.] + [(b[0] - a[0]) * .0000001 for a, b in zip(rows, rows[1:])]
        for row, elapsed in zip(rows, dt):
            values, mask = [0.] * 12, [0.] * 12
            for axis in range(3):
                index = row[2] * 3 + axis
                values[index], mask[index] = (row[3 + axis] - means[index]) / stds[index], 1.
            x.append(values + mask + [math.log1p(elapsed)])
        if len(rows) != SPEC[part][1] or not all(math.isfinite(v) for event in x for v in event):
            raise ValueError("fixed selection incomplete or frontend produced nonfinite features")
        features[part] = {"x": x, "dt": dt, "y": [r[6] for r in rows], "source_rows": [r[7] for r in rows]}
        selection[part] = {"sequence": SPEC[part][0], "events": len(rows),
                           "max_gap_seconds": max(dt), "gaps_above_limit": sum(t > .1 for t in dt),
                           "first_tick": rows[0][0], "last_tick": rows[-1][0],
                           "label_counts": dict(Counter(LABELS[r[6]] for r in rows))}
    report["selection"] = selection
    report["features_sha256"] = write_json(output / "features.json", features)
    report["frontend_verified"] = True
    return features


def train_smoke(features, output, report, check, event):
    import torch
    from .contract import GridSpec
    from .network import ContinuousSpikingNetwork

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    report["torch"] = torch.__version__
    tensors = {part: (torch.tensor(rows["x"], dtype=torch.float64)[None],
                      torch.tensor(rows["dt"], dtype=torch.float64)[None],
                      torch.tensor(rows["y"], dtype=torch.long)) for part, rows in features.items()}

    class GRU(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.rnn = torch.nn.GRU(25, 4, batch_first=True)
            self.head = torch.nn.Linear(4, len(LABELS))

        def forward(self, x):
            return self.head(self.rnn(x)[0])

    for arm in SPEC["arms"]:
        check()
        torch.manual_seed(SPEC["seed"])
        if arm == "hcsn":
            model = ContinuousSpikingNetwork(25, 4, len(LABELS), layer_count=1,
                        grid=GridSpec(active_cells=6, phase_cells=3, quadrature_order=8)).double()
            model.layers[0].physics.requires_grad_(False)
            physics = {name: value.detach().clone() for name, value in model.layers[0].physics.state_dict().items()}
        else:
            model = GRU().double()
        parameters = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.Adam(parameters, lr=SPEC["learning_rate"])
        info = report["training"][arm] = {"status": "started", "optimizer_updates": 0,
                 "trainable_parameters": sum(p.numel() for p in parameters), "window_losses": [],
                 "reset_policy": "fresh state before each fixed 32-event training window; original dt retained"}
        report["smoke_fits_started"] += 1
        initial = output / f"{arm}-initial.pt"
        torch.save(model.state_dict(), initial)
        info["initialization_sha256"] = sha(initial.read_bytes())
        x, dt, y = tensors["train"]
        for update in range(SPEC["updates_per_arm"]):
            check()
            lo, hi = update * 32, (update + 1) * 32
            optimizer.zero_grad(set_to_none=True)
            logits = (model(x[:, lo:hi], dt[:, lo:hi], state=model.initial_state(1)).predictions
                      if arm == "hcsn" else model(x[:, lo:hi]))
            loss = torch.nn.functional.cross_entropy(logits[0], y[lo:hi])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError(f"{arm}: nonfinite training loss")
            loss.backward()
            if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):
                raise FloatingPointError(f"{arm}: missing/nonfinite training gradient")
            norm = torch.nn.utils.clip_grad_norm_(parameters, SPEC["gradient_norm_cap"])
            if not bool(torch.isfinite(norm)) or float(norm) <= 0:
                raise FloatingPointError(f"{arm}: invalid gradient norm")
            optimizer.step()
            info["optimizer_updates"] += 1
            info["window_losses"].append(float(loss.detach()))
            checkpoint = output / f"{arm}-update-{update + 1}.pt"
            torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                        "rng": torch.get_rng_state(), "frontend_sha256": report["frontend_sha256"],
                        "source_rows": features["train"]["source_rows"][lo:hi]}, checkpoint)
            info["checkpoint_sha256"] = sha(checkpoint.read_bytes())
            event("optimizer_update", arm=arm, update=update + 1, loss=info["window_losses"][-1])
        check()
        x, dt, y = tensors["dev"]
        with torch.no_grad():
            logits = model(x, dt, state=model.initial_state(1)).predictions if arm == "hcsn" else model(x)
            if not bool(torch.isfinite(logits).all()):
                raise FloatingPointError(f"{arm}: nonfinite development logits")
            info["dev_cross_entropy"] = float(torch.nn.functional.cross_entropy(logits[0], y))
        info["dev_logits_sha256"] = write_json(output / f"{arm}-dev-logits.json", logits[0].tolist())
        if arm == "hcsn":
            info["physics_unchanged"] = all(torch.equal(old, model.layers[0].physics.state_dict()[name])
                                            for name, old in physics.items())
            if not info["physics_unchanged"]:
                raise RuntimeError("frozen physical parameters changed")
        info["status"] = "completed_interface_smoke"
        event("arm_complete", arm=arm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory; never overwrite prior evidence")
    parser.add_argument("--archive", type=Path, help="reuse an official ZIP; retain its prior origin receipt")
    parser.add_argument("--train", action="store_true", help="also run the fixed 1-seed GRU/HCSN interface smoke")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    report = {"schema": "hcsn-localization-interface-smoke-v1", "status": "started",
              "started_utc": datetime.now(timezone.utc).isoformat(), "spec": SPEC,
              "mode": "training_smoke" if args.train else "dataset_only", "training": {},
              "source_before": source_hashes(), "formal_fits_started": 0, "old_study_credit": 0,
              "smoke_fits_started": 0, "physical_energy_joules": None, "provider_charges": None,
              "frontend_verified": False, "user_authorization": "existing full-research instruction",
              "python": sys.version, "platform": platform.platform(),
              "claim_boundary": "Real-input interface smoke only; coarse unqualified physical grid, no fair six-family comparison, no generalization/efficiency claim."}
    write_json(args.output / "locked-spec.json", {"spec": SPEC, "source_before": report["source_before"]})
    events = (args.output / "events.jsonl").open("x", encoding="utf-8")

    def check():
        if time.perf_counter() - started > SPEC["wall_budget_seconds"]:
            raise TimeoutError("fixed 180-second wall budget exhausted")
        rss = peak_rss()
        if rss is not None and rss > SPEC["rss_budget_bytes"]:
            raise MemoryError("fixed 1-GiB peak RSS budget exceeded")

    def event(name, **fields):
        events.write(json.dumps({"event": name, "wall_seconds": time.perf_counter() - started, **fields}) + "\n")
        events.flush()

    exit_code, phase = 2, "acquisition"
    try:
        data = acquire(args.output, args.archive, report, check)
        event("archive_verified")
        phase = "dataset"
        groups = parse_data(data, report, check)
        del data
        features = frontend(groups, args.output, report)
        del groups
        event("dataset_and_frontend_verified")
        if any(row["gaps_above_limit"] for row in report["selection"].values()):
            report["status"] = "blocked_selected_gaps"
        elif not args.train:
            report["status"], exit_code = "dataset_only_verified", 0
        else:
            phase = "training"
            train_smoke(features, args.output, report, check, event)
            check()
            report["status"], exit_code = "completed_interface_smoke", 0
    except (TimeoutError, MemoryError) as error:
        report.update(status="incomplete_budget", error=str(error))
    except ImportError as error:
        report.update(status="blocked_dependency", error=str(error))
    except Exception as error:
        report.update(status=f"blocked_{phase}" if phase != "training" else "failed_smoke",
                      error=f"{type(error).__name__}: {error}")
        exit_code = 1 if phase == "training" else 2
    finally:
        report.update(source_after=source_hashes(), wall_seconds=time.perf_counter() - started,
                      process_cpu_seconds=time.process_time() - cpu_started, peak_rss_bytes=peak_rss(),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"], exit_code = "source_changed_during_smoke", 1
        event("finished", status=report["status"])
        events.close()
        report["events_sha256"] = sha((args.output / "events.jsonl").read_bytes())
        write_json(args.output / "report.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "smoke_fits_started": report["smoke_fits_started"], "formal_fits_started": 0}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
