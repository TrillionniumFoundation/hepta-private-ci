"""Read-only audit of already saved outputs/updates; no model or RNG forward."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import resource
import sys
import traceback

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from content_reconcile.policy import repair
from data import parse_caption, templates
from independent.accounting import WorkLedger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    run = Path(__file__).resolve().parent.parent
    frozen = json.loads(args.freeze.read_text())
    ledger = WorkLedger("saved-output-audit")
    result = dict(scope="saved-output/model-state read-only audit; zero neural inference, draws, renders or retiming",
                  model_forward_calls=0, decoder_forward_calls=0, sampling_draws=0,
                  new_model_renders=0, new_service_calls=0, errors=None)
    status = 0
    try:
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == frozen["audit_sha256"]
        manifest_path = ROOT / "content_joint/retained-train-v1.json"
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == frozen["manifest_sha256"]
        manifest = json.loads(manifest_path.read_text())
        for row in manifest["files"]:
            assert hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() == row["sha256"], row["path"]
        old = json.loads(Path(str(run) + ".execution.json").read_text())
        summary = json.loads((run / "quality-summary.json").read_text())
        build = json.loads((run / "build.json").read_text())
        source_map = json.loads((run / "source-map.json").read_text())
        indices = np.linspace(0, 767, 64, dtype=int)
        with np.load(ROOT / "runs/content-control-train-r2-20261023/train-inputs.npz", allow_pickle=False) as data:
            labels = data["inner_labels"][indices]
        references = templates()
        ledger.record("audit", data_reference_templates=12)
        behavior, trajectories, displacement = {}, {}, {}
        for call in build["plan"]["service_calls"]:
            family, recipe, seed, profile = [call[k] for k in ("family", "recipe", "seed", "profile")]
            path = run / f"service-{family}-{recipe}-{seed}-{profile}.json"
            receipt = json.loads(path.read_text())
            assert receipt["source_ids"] == [source_map["inner_rows"][i] for i in indices]
            np.testing.assert_array_equal(receipt["labels"], labels)
            pairs = np.asarray(receipt["final_pairs"])
            if recipe == "native":
                s = np.asarray(receipt["probabilities"]["s"])
                np.testing.assert_allclose(s.sum(1), 1, rtol=0, atol=1e-10)
                assert np.isfinite(s).all() and np.all(s >= 0)
                assert np.array_equal(pairs[:, 0], pairs[:, 1])
                assert np.all(s[np.arange(64), pairs[:, 0]] > 0)
                assert receipt["original_pairs"] is None and receipt["actions"] is None
                repairs = 0
            else:
                p, q = [np.asarray(receipt["probabilities"][key]) for key in ("p", "q")]
                for policy in (p, q):
                    np.testing.assert_allclose(policy.sum(1), 1, rtol=0, atol=1e-10)
                    assert np.isfinite(policy).all() and np.all(policy >= 0)
                original = np.asarray(receipt["original_pairs"])
                actual, actions = repair(p, q, original, "log2" if profile == "log2" else "infinity", ledger, "audit")
                np.testing.assert_array_equal(actual, pairs)
                np.testing.assert_array_equal(actions, receipt["actions"])
                repairs = int(np.count_nonzero(actions))
            ledger.charge_kernel("audit", "law_and_source_checks", scalar_ops=24 * 64, compare_ops=50 * 64)
            counts = dict(requests=64, repairs=repairs, text_correct=0, image_correct=0,
                          joint_success=0, both_wrong=0, wrong_agreement=0,
                          text_only_correct=0, image_only_correct=0)
            mse = 0.
            for index, entry in enumerate(receipt["outputs"]):
                png = base64.b64decode(entry["png_base64"])
                assert hashlib.sha256(png).hexdigest() == entry["png_sha256"]
                pixels = np.asarray(Image.open(io.BytesIO(png)), dtype=np.float64).reshape(192) / 255.
                distances = np.mean((pixels[None, :] - references) ** 2, axis=1)
                text, image = parse_caption(entry["caption"]), int(distances.argmin())
                assert (text, image) == tuple(pairs[index])
                assert entry["choices"] == {"text": int(pairs[index, 0]), "image": int(pairs[index, 1])}
                tc, ic = text == labels[index], image == labels[index]
                counts["text_correct"] += int(tc)
                counts["image_correct"] += int(ic)
                counts["joint_success"] += int(tc and ic)
                counts["both_wrong"] += int(not tc and not ic)
                counts["wrong_agreement"] += int(not tc and not ic and text == image)
                counts["text_only_correct"] += int(tc and not ic)
                counts["image_only_correct"] += int(not tc and ic)
                mse += float(distances[labels[index]])
            ledger.charge_kernel("audit", "actual_saved_PNG_observer",
                scalar_ops=64 * (3 * 12 * 192 - 12 + 9), div_ops=64 * (192 + 12),
                compare_ops=64 * (11 + 8))
            counts["mean_actual_PNG_mse"] = mse / 64
            behavior[f"{family}-{recipe}-{seed}-{profile}"] = counts
        for slot in build["slot_results"]:
            family, recipe, seed = [slot[k] for k in ("family", "recipe", "seed")]
            folder = run / f"{family}-{recipe}-{seed}"
            with np.load(folder / "gradient-updates.npz", allow_pickle=False) as data:
                keys = data["group_names"].tolist()
                row = {}
                for key in keys:
                    first, final = data["first_delta/" + key], data["final_delta/" + key]
                    clock = int(data["clock/" + key])
                    assert clock == slot["updates"]
                    row[key] = dict(first_delta_norm=float(np.linalg.norm(first)),
                                    final_delta_norm=float(np.linalg.norm(final)), clock=clock,
                                    first_nonzero_entries=int(np.count_nonzero(first)),
                                    final_nonzero_entries=int(np.count_nonzero(final)))
                    ledger.charge_kernel("audit", "actual_displacement_norms",
                        scalar_ops=4 * final.size, sqrt_ops=2, compare_ops=2 * final.size)
                row["train_first_last_loss"] = [float(data["loss"][0]), float(data["loss"][-1])]
                row["clipped_steps"] = int(np.count_nonzero(data["clip_scale"] < 1))
                displacement[folder.name] = row
            trajectories[folder.name] = []
            for checkpoint in slot["checkpoints"]:
                update = checkpoint["update"]
                with np.load(folder / f"checkpoint-{update}.npz", allow_pickle=False) as data:
                    laws = ("native",) if recipe == "native" else ("KEEP", "log2")
                    values = {}
                    for law in laws:
                        for partition, start, stop in (("fit", 0, 128), ("inner", 128, 256)):
                            values[law + "/" + partition] = {
                                key: float(data[law + "/" + key][start:stop].mean())
                                for key in ("ce", "joint_success", "both_wrong", "text_correct", "image_correct")}
                            ledger.charge_kernel("audit", "fixed_saved_curve_reduction",
                                                 scalar_ops=5 * 127, div_ops=5)
                    trajectories[folder.name].append(dict(update=update, values=values))
        result.update(behavior=behavior, parameter_displacement=displacement,
                      fixed_saved_trajectories=trajectories, verified_PNG_outputs=2304,
                      verified_model_states=24, original_build_and_analysis_unchanged=True)
    except BaseException:
        result["errors"] = traceback.format_exc()
        status = 1
    usage = resource.getrusage(resource.RUSAGE_SELF)
    audit_CPU = usage.ru_utime + usage.ru_stime
    result.update(exit_code=status, complete_audit_CPU_before_receipt=audit_CPU,
                  audit_units=ledger.consumed_units, ledger=ledger.snapshot())
    if 'old' in locals():
        result["combined_complete_costs"] = {
            f: dict(CPU=row["CPU"] + audit_CPU, units=row["units"] + ledger.consumed_units)
            for f, row in old["complete_costs_including_administration"].items()}
        result["all_final_caps_hold"] = all(c["CPU"] <= 10 and c["units"] <= 12_000_000_000
                                           for c in result["combined_complete_costs"].values())
        if not result["all_final_caps_hold"]:
            status = 2
            result["exit_code"] = status
    (run / "evidence/audit-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("exit_code", "complete_audit_CPU_before_receipt", "audit_units")}))
    if result["errors"]:
        print(result["errors"])
    raise SystemExit(status)


if __name__ == "__main__":
    main()
