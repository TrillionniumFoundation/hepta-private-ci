"""Real pretrained Granite97 + DINOv2-small image/text differentiation (SHADOW).

Offline unit tests use expressly artificial tensors; this CLI's `run` subcommand
REQUIRES exact publisher safetensors, actually materialized stock transformers,
source-only ScienceQA images, original TRAIN+CAL labels and successful forwards.
No future target argument is exposed, no fallback or promotion. The learned
384x384 ridge belongs to an ORGAN, and the learned Cell gate has 769 parameters.
"""
from __future__ import annotations
import argparse
import hashlib
import io
from pathlib import Path
import shutil
import time

from e3_scienceqa_contract import (ARMS, DINO, GRANITE, E3Error, MAX_ROWS, SCHEMA,
     canonical, digest, read_jsonl, read_pinned, revision, sha, unit_probabilities,
     validate_labels, validate_source, write_new)


def verified_acquisition(repo_id, pinned_revision, stage_dir):
    """Only exact-publisher-revision JSON, tokenizer data and safetensors."""
    from huggingface_hub import HfApi, hf_hub_download
    revision(pinned_revision)
    info = HfApi().model_info(repo_id, revision=pinned_revision, files_metadata=True)
    if info.sha != pinned_revision:
        raise E3Error("pretrained source mutable/drifted")
    names = {}
    for f in info.siblings:
        name = f.rfilename
        if (name.count("/") or name.startswith(".") or
                not name.endswith((".json", ".safetensors", ".model", ".txt"))):
            continue
        if not isinstance(f.size, int) or f.size <= 0:
            raise E3Error("unbounded model material")
        names[name] = f
    if not {"config.json", "model.safetensors"} <= set(names) or not 2 <= len(names) <= 32:
        raise E3Error("missing approved full safetensors model inventory")
    if sum(x.size for x in names.values()) > 2 * 1024**3:
        raise E3Error("model weights/processor limit exceeded")
    if stage_dir.exists():
        raise E3Error("model directory must be created once")
    stage_dir.mkdir(parents=True)
    registry = {}
    for name, metadata in sorted(names.items()):
        p = Path(hf_hub_download(repo_id, name, revision=pinned_revision))
        source = stage_dir / name
        shutil.copyfile(p, source)  # no HF cache symlink in the verified snapshot
        if source.stat().st_size != metadata.size:
            raise E3Error("model member size changed")
        actual = sha(source.read_bytes())
        lfs = getattr(metadata, "lfs", None)
        original_sha = getattr(lfs, "sha256", None) if lfs else None
        if original_sha is not None and actual != original_sha:
            raise E3Error("publisher LFS mismatch")
        registry[name] = actual
    return {"revision": pinned_revision, "files": registry, "kind": "encoder"}


class FrozenVision:
    """Strict source-saved tensor equality: missing Meta or aliases fail closed."""
    def __init__(self, root, manifest):
        import torch
        from safetensors import safe_open
        from transformers import AutoImageProcessor, Dinov2Model
        from execution import verify_snapshot
        self.identity = verify_snapshot(root, manifest)
        loaded, report = Dinov2Model.from_pretrained(
            root, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, output_loading_info=True, attn_implementation="eager")
        if any(report.get(k) for k in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
            raise E3Error("DINO checkpoint keys incompletely materialized")
        if any(p.is_meta for p in loaded.parameters()) or any(b.is_meta for b in loaded.buffers()):
            raise E3Error("DINO checkpoint contains Meta Tensors")
        self.model = loaded.cpu().float().eval().requires_grad_(False)
        self.processor = AutoImageProcessor.from_pretrained(root, local_files_only=True,
                                                             trust_remote_code=False)
        original, matched = self.model.state_dict(), set()
        for filename in manifest["files"]:
            if not filename.endswith(".safetensors"):
                continue
            with safe_open(str(root / filename), framework="pt", device="cpu") as source:
                for key in source.keys():
                    if key in matched or key not in original or not torch.equal(source.get_tensor(key), original[key]):
                        raise E3Error("DINO original-tensor equality failure")
                    matched.add(key)
        if matched != set(original):
            raise E3Error("DINO has tensor not present in pinned saved checkpoint")
        if self.model.config.hidden_size != 384:
            raise E3Error("unreviewed DINO feature width")
        verify_snapshot(root, manifest)
        self.root, self.manifest, self.calls = root, manifest, 0

    def encode(self, originals):
        import torch
        import torch.nn.functional as F
        from PIL import Image
        if not 1 <= len(originals) <= 8:
            raise E3Error("physical frozen vision batch limit")
        pictures = []
        for raw in originals:
            if not 0 < len(raw) <= 8 * 1024 * 1024:
                raise E3Error("unsafe vision source")
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ("PNG", "JPEG") or img.width * img.height > 4_194_304:
                    raise E3Error("unsupported media")
                img.load()
                pictures.append(img.convert("RGB"))
        with torch.no_grad():
            args = self.processor(images=pictures, return_tensors="pt")
            vectors = self.model(**args).last_hidden_state[:, 0, :]
            if vectors.shape != (len(originals), 384) or not torch.isfinite(vectors).all():
                raise E3Error("invalid true DINO CLS vectors")
            vectors = F.normalize(vectors, dim=-1)
        self.calls += 1
        return vectors.detach().cpu().float()

    def close(self):
        from execution import verify_snapshot
        verify_snapshot(self.root, self.manifest)


def input_prompts(item):
    """No answer or answer index, only source question and ALL four candidates."""
    question = item["question"] + ("\n" + item["hint"] if item["hint"] else "")
    return ["query: " + question] + ["passage: " + question + "\nChoice: " + x for x in item["choices"]]


def real_features(items, image_root, text_model, visual_model):
    """One persistent shared Text+Vision pair, no encoder per Cell."""
    import torch
    import torch.nn.functional as F
    if not 1 <= len(items) <= MAX_ROWS:
        raise E3Error("bounded source sample count")
    texts = [query for row in items for query in input_prompts(row)]
    vectors = []
    for i in range(0, len(texts), 16):
        x = text_model.encode(texts[i:i + 16], pooling="cls-first-token")
        if x.shape != (len(texts[i:i+16]), 384) or not torch.isfinite(x).all():
            raise E3Error("Granite official 384D CLS pooling rejected")
        vectors.append(x)
    t = F.normalize(torch.cat(vectors).view(len(items), 5, 384), dim=-1)
    vs = []
    for i in range(0, len(items), 8):
        raw = [read_pinned(image_root / row["image"], row["image"], maximum=8*1024*1024)
               for row in items[i:i + 8]]
        vs.append(visual_model.encode(raw))
    visual = F.normalize(torch.cat(vs), dim=-1)
    text_model.close()
    visual_model.close()
    if visual.shape != (len(items), 384) or t.shape != (len(items), 5, 384):
        raise E3Error("feature width/count changed")
    return t[:, 0].contiguous(), t[:, 1:].contiguous(), visual.contiguous()


def fit_and_predict(sources, train_labels, question, choices, image, *, steps=80, seed=20261015):
    """All learned parameters updated ONLY from TRAIN labels.

    CAL labels choose one predeclared convex mixing weight; HOLD labels never
    enter this function. Returns label-free HOLD predictions and work receipt.
    """
    import torch
    import torch.nn.functional as F
    torch.manual_seed(seed)
    validate_source(sources)
    labels = validate_labels(sources, train_labels, {"train", "validation"})
    if (question.shape != (len(sources), 384) or choices.shape != (len(sources), 4, 384)
            or image.shape != (len(sources), 384) or not all(torch.isfinite(v).all()
            for v in (question, choices, image))):
        raise E3Error("mixed or nonfinite pretrained feature batch")
    if type(steps) is not int or not 1 <= steps <= 256:
        raise E3Error("bounded actual SGD steps")
    ix = {split: [i for i, r in enumerate(sources) if r["split"] == split] for split in ("train", "validation", "test")}
    tr, cal, held = (ix[k] for k in ("train", "validation", "test"))
    label_train = torch.tensor([labels[sources[i]["id"]] for i in tr], dtype=torch.long)
    label_cal = torch.tensor([labels[sources[i]["id"]] for i in cal], dtype=torch.long)
    y = choices[tr][torch.arange(len(tr)), label_train]
    # Organ-level learned bridge (147,840 scalars) and TRAIN-label rotated negative control.
    start = time.perf_counter_ns()
    def ridge(x, target):
        # Same declared f64/intercept-unpenalized ridge objective as V1, but
        # this task's stand-alone producer does not gain training target access
        # outside the provided original TRAIN labels.
        a = torch.cat((x, torch.ones(len(x), 1, dtype=torch.float64)), dim=1)
        penalty = torch.eye(a.shape[1], dtype=torch.float64) * 0.25
        penalty[-1, -1] = 0
        fit = torch.linalg.solve(a.T @ a + penalty, a.T @ target)
        if fit.shape != (385, 384) or not torch.isfinite(fit).all() or fit.abs().max() > 8:
            raise E3Error("unbounded trained organ Bridge")
        weight, bias = fit[:-1].float().T.contiguous(), fit[-1].float()
        return weight, bias, sha(canonical([weight.tolist(), bias.tolist()]))

    learned = ridge(image[tr].double(), y.double())
    rotated = ridge(image[tr].double(), torch.roll(y.double(), shifts=17, dims=0))

    def apply(bridge):
        weight, bias, _ = bridge
        value = image @ weight.T + bias
        if not (value.norm(dim=1) > 1e-10).all():
            raise E3Error("degenerate learned visual Bridge")
        return F.normalize(value, dim=-1)

    mapped = apply(learned)
    wrong = apply(rotated)
    # All masks/Heads reuse identical frozen real features and total source rows.
    ts = torch.einsum("nd,ncd->nc", question, choices)
    raw_s = torch.einsum("nd,ncd->nc", image, choices)
    ms = torch.einsum("nd,ncd->nc", mapped, choices)
    ws = torch.einsum("nd,ncd->nc", wrong, choices)
    gate = torch.nn.Linear(768, 1)
    torch.nn.init.zeros_(gate.weight)
    torch.nn.init.zeros_(gate.bias)
    optimizer = torch.optim.AdamW(gate.parameters(), lr=0.01, weight_decay=0.0)
    covars = torch.cat((question, mapped), dim=1).detach()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        g = torch.sigmoid(gate(covars[tr]))
        logits = (ts[tr] * (1 - g) + ms[tr] * g) * 8.0
        loss = F.cross_entropy(logits, label_train)
        if not torch.isfinite(loss):
            raise E3Error("nonfinite train-only Head optimization")
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        g = torch.sigmoid(gate(covars)).squeeze(-1)
        gate_scores = ts * (1 - g[:, None]) + ms * g[:, None]
    calibrated = []
    for weight in (0., 0.25, 0.5, 0.75, 1.):
        logits = (ts[cal] * (1 - weight) + ms[cal] * weight) * 8.0
        cal_loss = float(F.cross_entropy(logits, label_cal).item())
        calibrated.append((cal_loss, weight))
    calibration_loss, selected_weight = min(calibrated)
    by_arm = {
        "text_only": ts, "unaligned_equal_fusion": .5 * (ts + raw_s),
        "rotated_equal_fusion": .5 * (ts + ws), "bridge_image_only": ms,
        "bridge_equal_fusion": .5 * (ts + ms), "train_gate": gate_scores,
        "calibrated_fusion": (1 - selected_weight) * ts + selected_weight * ms,
        "image_masked": ts,
    }
    if set(by_arm) != set(ARMS) or sum(x.numel() for x in gate.parameters()) != 769:
        raise E3Error("incorrect Cell-Head parameter budget or arm inventory")
    predictions = []
    with torch.no_grad():
        for i in held:
            arms = {k: unit_probabilities((8 * values[i]).tolist()) for k, values in by_arm.items()}
            predictions.append({"id": sources[i]["id"], "group": sources[i]["group"],
                                "split": "test", "source_input_sha256": sha(canonical(sources[i])),
                                "arms": arms})
    if any(a["arms"]["text_only"] != a["arms"]["image_masked"] for a in predictions):
        raise E3Error("false visual mask baseline")
    report = {"organ_bridge_parameter_count": 384 * 384 + 384,
              "private_cell_head_parameters": 769, "cell_optimizer_updates": steps,
              "train_cases": len(tr), "calibration_cases": len(cal), "holdout_cases": len(held),
              "calibration_candidate_weights": [0., .25, .5, .75, 1.],
              "calibration_selected_weight": selected_weight,
              "calibration_nll": calibration_loss,
              "organ_fitted_bridge_sha256": learned[2],
              "organ_shuffled_bridge_sha256": rotated[2],
              "gate_sha256": sha(canonical({k: v.detach().tolist() for k,v in gate.state_dict().items()})),
              "fit_and_prediction_wall_ns": time.perf_counter_ns() - start,
              "real_model_weights_injected_in_unit_tests": False,
              "three_future_windows_observed": False, "old_task_retention_verified": False,
              "model_origin_independently_signed": False,
              "production_accepted": False}
    return predictions, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--fit-labels", type=Path, required=True)
    parser.add_argument("--fit-labels-sha256", required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Reject target-bearing sources before acquiring ANY model weights.
    sources = read_jsonl(args.sources, args.source_sha256)
    validate_source(sources)
    fit_labels = read_jsonl(args.fit_labels, args.fit_labels_sha256)
    validate_labels(sources, fit_labels, {"train", "validation"})
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    stage = args.output / "weights-not-artifacts"
    granite = verified_acquisition(*GRANITE, stage / "granite")
    dino = verified_acquisition(*DINO, stage / "dino")
    # Import a real, existing Hepta hardened owner; no alternative plaintext
    # tokenizer/weight fallback is used for the text Stem.
    from execution import LocalEncoder, measured
    text_model = LocalEncoder(stage / "granite", granite, maximum_tokens=512)
    vision_model = FrozenVision(stage / "dino", dino)
    text_identity = text_model.identity
    vision_identity = vision_model.identity
    with measured() as telemetry:
        question, choices, image = real_features(sources, args.images, text_model, vision_model)
        text_forwards, vision_forwards = text_model.forward_calls, vision_model.calls
        predictions, fit_report = fit_and_predict(sources, fit_labels, question, choices, image)
    result = {"schema": SCHEMA + ".sealed-predictions", "arms": list(ARMS),
              "source_sha256": args.source_sha256,
              "fit_labels_sha256": args.fit_labels_sha256,
              "stem_model": {"repo": GRANITE[0], "revision": GRANITE[1], "sha256": text_identity,
                             "pooling": "cls-first-token+unit-l2"},
              "vision_model": {"repo": DINO[0], "revision": DINO[1], "sha256": vision_identity,
                               "pooling": "image-cls+unit-l2"},
              "physical_text_forward_batches": text_forwards,
              "physical_vision_forward_batches": vision_forwards,
              "true_pretrained_execution_unattested": True,
              "same_source_public_release_not_future": True,
              "fit": fit_report, "meter": telemetry, "predictions": predictions,
              "training_labels_permitted_for_fit_only": True,
              "held_labels_visible_to_inference": False,
              "independent_ground_truth_observer": False,
              "energy_joules": None, "production_accepted": False,
              "full_acquisition_plus_training_wall_ns": time.perf_counter_ns() - started}
    # Only the sealed, source-bound predictions and aggregate work report leave.
    write_new(args.output / "sealed-predictions.json", result)
    # Never upload `weights-not-artifacts` or image/answer material.

if __name__ == "__main__":
    main()
