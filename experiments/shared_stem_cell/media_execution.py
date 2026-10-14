"""Real local CLIP/Whisper towers -> existing frozen-tower connector experiment.

PNG/JPEG, 16 kHz PCM16 mono WAV and explicitly timestamped source frames are
accepted. Frame lists are not an MP4 decoder. No implicit downloads, synthetic
fallback, arbitrary model classes or claims of general multimodal reasoning.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
from pathlib import Path
import wave

import numpy as np
from PIL import Image
import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.controls import modality_trial

MODALITIES = {"text", "image", "audio", "video"}
MAX_MEDIA_BYTES = 16 * 1024**2


def reference(root, item):
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        raise e.InputError("exact media reference required")
    path = Path(item["path"])
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise e.InputError("media path must remain in staged dataset")
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise e.InputError("linked media path")
    return e.bound_file(target, item["sha256"], MAX_MEDIA_BYTES)


def image_bytes(raw):
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in {"PNG", "JPEG"} or source.width * source.height > 4_194_304:
            raise e.InputError("bounded PNG/JPEG image required")
        if getattr(source, "n_frames", 1) != 1:
            raise e.InputError("animated images require an explicit frame manifest")
        source.load()
        return source.convert("RGB")


def audio_bytes(raw):
    with wave.open(io.BytesIO(raw), "rb") as source:
        n = source.getnframes()
        if (source.getnchannels() != 1 or source.getsampwidth() != 2
                or source.getframerate() != 16000 or source.getcomptype() != "NONE"
                or not 320 <= n <= 480000):
            raise e.InputError("20 ms..30 s, 16 kHz PCM16 mono WAV required; no resampling")
        data = source.readframes(n)
        if len(data) != 2 * n:
            raise e.InputError("truncated WAV samples")
        return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


@dataclass(frozen=True)
class MediaCase:
    case_id: str
    group: str
    split: str
    scope: str
    observed_at: int | None
    inputs: dict

    @property
    def input_digest(self):
        return e.sha(e.canonical([self.scope, self.inputs]))


def read_cases(root, descriptor, classes, temporal=False):
    raw = reference(root, descriptor)
    cases, labels, groups, contents, times = [], {}, {}, {}, {}
    media_bytes_read = 0
    for line in raw.splitlines():
        if not line.strip():
            raise e.InputError("blank media dataset row")
        row = e.decode(line)
        if not isinstance(row, dict) or set(row) != {
            "case_id", "group", "split", "scope", "observed_at", "inputs", "label"
        }:
            raise e.InputError("media dataset fields")
        e.integer(classes, 2, 256, "classes")
        e.integer(row["label"], 0, classes - 1, "label")
        for key in ("case_id", "group", "scope"):
            if not isinstance(row[key], str) or not 1 <= len(row[key].encode()) <= 256:
                raise e.InputError("bounded media identity")
        if row["split"] not in {"train", "calibration", "holdout", "retention"}:
            raise e.InputError("media split")
        inputs = row["inputs"]
        if not isinstance(inputs, dict) or not inputs or not set(inputs) <= MODALITIES:
            raise e.InputError("known nonempty modality map required")
        fingerprints = [e.sha(e.canonical(inputs))]
        for name, item in inputs.items():
            if name == "text":
                if not isinstance(item, str) or not 1 <= len(item.encode()) <= 4096:
                    raise e.InputError("bounded nonempty text")
            elif name == "video":
                if not isinstance(item, list) or not 2 <= len(item) <= 16:
                    raise e.InputError("2..16 explicit source frames required")
                previous = -1
                for frame in item:
                    if not isinstance(frame, dict) or set(frame) != {"path", "sha256", "timestamp_us"}:
                        raise e.InputError("video source/time binding")
                    stamp = e.integer(frame["timestamp_us"], 0, 2**63 - 1, "frame timestamp")
                    if stamp <= previous or (row["observed_at"] is not None and stamp > row["observed_at"]):
                        raise e.InputError("reversed or future frame")
                    previous = stamp
                    payload = reference(root, {k: frame[k] for k in ("path", "sha256")})
                    media_bytes_read += len(payload)
                    if media_bytes_read > 128 * 1024**2:
                        raise e.InputError("whole media trial byte budget exceeded")
                    image_bytes(payload)
                    fingerprints.append(frame["sha256"])
            else:
                payload = reference(root, item)
                media_bytes_read += len(payload)
                if media_bytes_read > 128 * 1024**2:
                    raise e.InputError("whole media trial byte budget exceeded")
                (image_bytes if name == "image" else audio_bytes)(payload)
                fingerprints.append(item["sha256"])
        if row["observed_at"] is not None:
            e.integer(row["observed_at"], 0, 2**63 - 1, "observed_at")
            times.setdefault(row["split"], []).append(row["observed_at"])
        elif temporal:
            raise e.InputError("temporal media needs actual observed times")
        if row["case_id"] in labels:
            raise e.InputError("duplicate media case")
        for mapping, keys in ((groups, [row["group"]]), (contents, fingerprints)):
            for key in keys:
                if key in mapping and mapping[key] != row["split"]:
                    raise e.InputError("cross-fold source/group leakage")
                mapping[key] = row["split"]
        labels[row["case_id"]] = row["label"]
        cases.append(MediaCase(**{k: v for k, v in row.items() if k != "label"}))
    if not 4 <= len(cases) <= 256 or not {"train", "calibration", "holdout"} <= {c.split for c in cases}:
        raise e.InputError("bounded train/calibration/holdout media required")
    if len({c.scope for c in cases}) != 1:
        raise e.InputError("one scope per media execution")
    if temporal and not max(times["train"]) < min(times["calibration"]) <= max(times["calibration"]) < min(times["holdout"]):
        raise e.InputError("media chronology")
    return tuple(cases), labels


class LocalTowers:
    """Load whole stock models and verify all tensors; no dropped decoder keys."""
    simulated = False

    def __init__(self, root, models):
        from transformers import CLIPModel, CLIPProcessor, WhisperForConditionalGeneration, WhisperFeatureExtractor
        if not isinstance(models, dict) or not models or not set(models) <= {"clip", "whisper"}:
            raise e.InputError("explicit clip/whisper model manifests required")
        self.root, self.manifests = root, models
        self.models, self.processors, self.identities, self.calls = {}, {}, {}, {}
        self.materializations = {}
        for name, manifest in models.items():
            path = root / manifest["path"]
            if Path(manifest["path"]).is_absolute() or ".." in Path(manifest["path"]).parts:
                raise e.InputError("model must be staged locally")
            self.identities[name] = e.verify_snapshot(path, manifest)
            factory, processor = ((CLIPModel, CLIPProcessor) if name == "clip" else
                                  (WhisperForConditionalGeneration, WhisperFeatureExtractor))
            loaded, info = factory.from_pretrained(path, local_files_only=True,
                use_safetensors=True, trust_remote_code=False, output_loading_info=True,
                attn_implementation="eager")
            loaded = loaded.cpu().float().eval().requires_grad_(False)
            self.materializations[name] = e.verify_materialized(loaded, info, path, manifest)
            self.models[name] = loaded
            self.processors[name] = processor.from_pretrained(path, local_files_only=True,
                                                               trust_remote_code=False)
            self.calls[name] = 0
        self.close()

    @torch.no_grad()
    def encode(self, name, item, root):
        family = "whisper" if name == "audio" else "clip"
        if family not in self.models:
            raise e.InputError("required frozen tower not provisioned")
        model, processor = self.models[family], self.processors[family]
        if name == "text":
            tokens = processor.tokenizer(item, truncation=False, return_tensors="pt")
            if tokens["input_ids"].shape[1] > min(64, model.config.text_config.max_position_embeddings):
                raise e.InputError("text tower token ceiling; no truncation")
            result = model.text_model(**tokens).last_hidden_state[0]
            stamps = torch.arange(len(result), dtype=torch.int64)
        elif name in {"image", "video"}:
            refs = [item] if name == "image" else [{k: f[k] for k in ("path", "sha256")} for f in item]
            pictures = [image_bytes(reference(root, ref)) for ref in refs]
            pixels = processor.image_processor(images=pictures, return_tensors="pt")["pixel_values"]
            values = model.vision_model(pixel_values=pixels)
            result = values.last_hidden_state[0] if name == "image" else values.pooler_output
            stamps = (torch.arange(len(result), dtype=torch.int64) if name == "image" else
                      torch.tensor([f["timestamp_us"] for f in item], dtype=torch.int64))
        else:
            samples = audio_bytes(reference(root, item))
            if (processor.sampling_rate != 16000 or processor.hop_length != 160
                    or processor.n_samples != 480000 or model.config.max_source_positions != 1500):
                raise e.InputError("unqualified audio timing profile")
            features = processor(samples, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
            values = model.model.encoder(input_features=features["input_features"]).last_hidden_state[0]
            valid = min(len(values), (len(samples) + 319) // 320)
            # Explicit 32-landmark mean pooling over 20-ms encoder positions.
            # This is a lossy declared representation, not token-equivalent audio.
            count = min(32, valid)
            edges = [i * valid // count for i in range(count + 1)]
            result = torch.stack([values[edges[i]:edges[i+1]].mean(0) for i in range(count)])
            stamps = torch.tensor([edges[i] * 20000 for i in range(count)], dtype=torch.int64)
        self.calls[family] += 1
        if result.ndim != 2 or not 1 <= len(result) <= 64 or not bool(torch.isfinite(result).all()):
            raise e.InputError("invalid bounded tower result")
        return result.detach().cpu().float().contiguous(), stamps

    @torch.no_grad()
    def encode_choices(self, texts, image_ref, root):
        """One image and four answer-content strings, with original CLIP projections."""
        if ("clip" not in self.models or not isinstance(texts, list) or len(texts) != 4
                or any(not isinstance(t, str) or not 1 <= len(t.encode()) <= 4096 for t in texts)):
            raise e.InputError("four bounded candidate strings and frozen CLIP required")
        model, processor = self.models["clip"], self.processors["clip"]
        tokens = processor.tokenizer(texts, padding=True, truncation=False, return_tensors="pt")
        if tokens["input_ids"].shape[1] > min(77, model.config.text_config.max_position_embeddings):
            raise e.InputError("candidate tokens exceed fixed CLIP context; no truncation")
        image = image_bytes(reference(root, image_ref))
        pixels = processor.image_processor(images=[image], return_tensors="pt")["pixel_values"]
        text = model.get_text_features(**tokens)
        self.calls["clip"] += 1
        visual = model.get_image_features(pixel_values=pixels)
        self.calls["clip"] += 1
        if (text.ndim != 2 or visual.ndim != 2 or text.shape[0] != 4 or visual.shape != (1, text.shape[1])
                or not 1 <= text.shape[1] <= 1024 or not bool(torch.isfinite(text).all())
                or not bool(torch.isfinite(visual).all())
                or bool((text.norm(dim=-1) <= 1e-12).any()) or bool((visual.norm(dim=-1) <= 1e-12).any())):
            raise e.InputError("finite nonzero projected CLIP features required")
        text = text / text.norm(dim=-1, keepdim=True)
        visual = visual / visual.norm(dim=-1, keepdim=True)
        return torch.cat([text, visual.expand(4, -1)], -1).detach().cpu().float().contiguous()

    def close(self):
        for name, manifest in self.manifests.items():
            e.verify_snapshot(self.root / manifest["path"], manifest)


def extract(towers, cases, root):
    names = sorted({name for case in cases for name in case.inputs})
    observations, widths = {}, {}
    for row, case in enumerate(cases):
        for name, item in case.inputs.items():
            value, stamps = towers.encode(name, item, root)
            if (value.dtype != torch.float32 or value.ndim != 2 or value.device.type != "cpu"
                    or not 1 <= value.shape[0] <= 64 or not 1 <= value.shape[1] <= 8192
                    or not bool(torch.isfinite(value).all()) or stamps.dtype != torch.int64
                    or stamps.shape != value.shape[:1] or bool((stamps < 0).any())
                    or (len(stamps) > 1 and not bool((stamps[1:] > stamps[:-1]).all()))):
                raise e.InputError("invalid exact tower shape/time")
            if name in widths and widths[name] != value.shape[1]:
                raise e.InputError("tower width drift")
            widths[name] = value.shape[1]
            observations[row, name] = (value, stamps)
    tensors = {}
    for name in names:
        slots = max(len(v[0]) for (row, n), v in observations.items() if n == name)
        x = torch.zeros(len(cases), slots, widths[name])
        mask = torch.zeros(len(cases), slots, dtype=torch.bool)
        times = torch.zeros(len(cases), slots, dtype=torch.int64)
        for row in range(len(cases)):
            if (row, name) in observations:
                value, stamps = observations[row, name]
                x[row, :len(value)] = value
                mask[row, :len(value)] = True
                times[row, :len(value)] = stamps
        tensors[name] = (x, mask, times)
    return tensors


def run(manifest_path, output, *, _tower_factory=LocalTowers):
    manifest_raw = manifest_path.read_bytes()
    config = e.decode(manifest_raw)
    if config.get("schema") != "hepta.shared-stem-media.v1" or type(config.get("temporal", False)) is not bool:
        raise e.InputError("media execution manifest")
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", config)
    root = manifest_path.parent
    try:
        profile = config.get("fusion_profile", "legacy_fixed")
        if profile not in {"legacy_fixed", "calibrated_checkpoints_v1"}:
            raise e.InputError("unknown fusion training profile")
        cases, labels = read_cases(root, config["dataset"], config["classes"], config.get("temporal", False))
        with e.measured() as load:
            towers = _tower_factory(root, config["models"])
        with e.measured() as encoding:
            values = extract(towers, cases, root)
        train = [i for i, case in enumerate(cases) if case.split == "train"]
        test = [i for i, case in enumerate(cases) if case.split in {"holdout", "retention"}]
        select = lambda ids: {k: tuple(t[ids] for t in v) for k, v in values.items()}
        fit_labels = torch.tensor([labels[cases[i].case_id] for i in train])
        selection_seal = None
        if profile == "calibrated_checkpoints_v1":
            from experiments.shared_stem_cell.calibrated_fusion import fit_calibrated, execute_calibrated
            calibration = [i for i, case in enumerate(cases) if case.split == "calibration"]
            candidates, selection = fit_calibrated(select(train), fit_labels, select(calibration),
                torch.tensor([labels[cases[i].case_id] for i in calibration]), classes=config["classes"],
                steps=config.get("steps", 20), seed=config.get("seed", 17))
            selection["binding"] = {"manifest_sha256": e.sha(manifest_raw),
                "model_identities": towers.identities, "dataset": config["dataset"],
                "train_ids": [cases[i].case_id for i in train],
                "calibration_ids": [cases[i].case_id for i in calibration]}
            selection_seal = e.write_once(output / "calibration-selection.json", selection)
            sealed_selection = e.decode(e.bound_file(output / "calibration-selection.json", selection_seal))
            result = execute_calibrated(candidates, sealed_selection, select(test), [cases[i].split for i in test])
        else:
            result = modality_trial(select(train), fit_labels, select(test), classes=config["classes"],
                steps=config.get("steps", 20), seed=config.get("seed", 17),
                test_partitions=[cases[i].split for i in test])
        towers.close()
        read_cases(root, config["dataset"], config["classes"], config.get("temporal", False))
        if manifest_path.read_bytes() != manifest_raw:
            raise e.InputError("media manifest changed during execution")
        payload = {"calibration_selection_sha256": selection_seal, "frozen_predictions": result["frozen_predictions"],
                   "modality_interventions": result["modality_interventions"],
                   "case_ids": [cases[i].case_id for i in test],
                   "input_digests": [cases[i].input_digest for i in test],
                   "predictions": result["predictions"]}
        seal = e.write_once(output / "predictions.json", payload)
        sealed = e.decode(e.bound_file(output / "predictions.json", seal))
        from experiments.shared_stem_cell.control_evaluation import summarize
        scores, learning = [], {}
        for split in sorted({cases[i].split for i in test}):
            selected = [j for j, i in enumerate(test) if cases[i].split == split]
            targets = [labels[cases[test[j]].case_id] for j in selected]
            groups = [cases[test[j]].group for j in selected]
            learning[split] = {}
            for arm, values in sealed["predictions"].items():
                if arm not in sealed["frozen_predictions"]:
                    raise e.InputError("same-initialization modality control missing")
                before = sealed["frozen_predictions"][arm]
                learning[split][arm] = summarize(
                    {"learned": [values[j] for j in selected], "frozen": [before[j] for j in selected]},
                    targets, groups, classes=config["classes"], control="frozen")
        for arm, probabilities in sealed["predictions"].items():
            p = torch.tensor(probabilities)
            if p.shape != (len(test), config["classes"]) or not bool(torch.isfinite(p).all()):
                raise e.InputError("incomplete media prediction arm")
            for split in sorted({cases[i].split for i in test}):
                selected = [j for j, i in enumerate(test) if cases[i].split == split]
                y = torch.tensor([labels[cases[test[j]].case_id] for j in selected])
                scores.append({"arm": arm, "split": split, "cases": len(selected),
                               "accuracy": float((p[selected].argmax(-1) == y).float().mean())})
        interventions = sealed["modality_interventions"]
        if interventions is None:
            raise e.InputError("same-model modality probe missing")
        probe_scores = {}
        for split in sorted({cases[i].split for i in test}):
            positions = [j for j, i in enumerate(test) if cases[i].split == split]
            probe_scores[split] = summarize(
                {arm: [rows[j] for j in positions] for arm, rows in interventions["predictions"].items()},
                [labels[cases[test[j]].case_id] for j in positions],
                [cases[test[j]].group for j in positions], classes=config["classes"], control="as_observed")
        source_mapping = {arm: [None if j is None else cases[test[j]].case_id for j in detail["rows"]]
                          for arm, detail in interventions["source_rows"].items()}
        from experiments.shared_stem_cell.process_peak import linux_lifetime_peak_rss_bytes
        report = {"process_lifetime_peak_rss_bytes": linux_lifetime_peak_rss_bytes(),
            "peak_is_isolated_per_modality_arm": False, "fusion_profile": profile, "calibration_selection_sha256": selection_seal, "prediction_sha256": seal, "scores": scores, "same_init_learning": learning, "connector_costs": result["costs"],
            "modality_intervention_scores": probe_scores, "intervention_source_case_ids": source_mapping,
            "intervention_costs": interventions["costs"], "intervention_scope": interventions["intervention_scope"],
            "model_identities": towers.identities,
            "model_materializations": getattr(towers, "materializations", None),
            "model_load": load, "encoding": encoding,
            "tower_forward_calls": towers.calls, "simulated_towers": towers.simulated,
            "representation": "CLIP text/patch tokens, ordered pooled video frames; Whisper 32 time-bin means",
            "temporal_claim": config.get("temporal", False), "independent_evaluation": False,
            "multimodal_reasoning_established": False, "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.manifest, args.output)
