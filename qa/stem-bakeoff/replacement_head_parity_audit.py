"""Independent *format* audit of five physical equal-Head research artifacts.

Hashes and raw rows are checked, but self-reported model calls / learned
projection provenance are NOT authenticated. No model promotion is possible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any

from replacement_gate import EXPECTED, SPLITS, score_rows, validate_registry

SHA64 = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "hepta.neuron.replacement-frozen-head-parity.v1"
HEAD_BYTES_MAX = 32 * 1024
JSON_BYTES_MAX = 2 * 1024 * 1024


def _regular_bounded(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("parity evidence must be a bounded ordinary file")
    with path.open("rb") as f:
        data = f.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise ValueError("missing or oversize parity evidence")
    return data


def _unique_pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate JSON key in untrusted parity evidence")
        out[k] = v
    return out


def _strict_json(data: bytes) -> dict:
    parsed = json.loads(data, object_pairs_hook=_unique_pairs,
                        parse_constant=lambda c: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(parsed, dict):
        raise ValueError("parity evidence must be JSON object")
    return parsed


def verify_head_artifact(blob: bytes, declared_sha: str) -> bool:
    """Parse the safetensors byte envelope without running code or importing Torch."""
    if not isinstance(declared_sha, str) or SHA64.fullmatch(declared_sha) is None:
        return False
    if not 8 < len(blob) <= HEAD_BYTES_MAX or hashlib.sha256(blob).hexdigest() != declared_sha:
        return False
    header_len = struct.unpack("<Q", blob[:8])[0]
    if header_len < 8 or header_len > 4096 or len(blob) <= 8 + header_len:
        return False
    try:
        header = _strict_json(blob[8:8 + header_len])
    except (ValueError, UnicodeError, TypeError, json.JSONDecodeError):
        return False
    if set(header) != {"weight", "bias"}:
        return False
    payload = blob[8 + header_len:]
    spans = []
    for key, shape in (("weight", [4, 256]), ("bias", [4])):
        record = header[key]
        nbytes = math.prod(shape) * 4
        if (not isinstance(record, dict) or set(record) != {"dtype", "shape", "data_offsets"}
                or record["dtype"] != "F32" or record["shape"] != shape
                or not isinstance(record["data_offsets"], list)
                or len(record["data_offsets"]) != 2
                or any(type(v) is not int for v in record["data_offsets"])):
            return False
        start, end = record["data_offsets"]
        if start < 0 or end - start != nbytes or end > len(payload):
            return False
        spans.append((start, end))
        if not all(math.isfinite(v) for (v,) in struct.iter_unpack("<f", payload[start:end])):
            return False
    spans.sort()
    return len(payload) == 4112 and spans[0][0] == 0 and (
        spans[0][1] == spans[1][0] and spans[1][1] == len(payload))


def audit_arm(name: str, parity: Any, original: Any, head_bytes: bytes,
              registry: dict) -> list[str]:
    errors = []
    if not isinstance(parity, dict) or not isinstance(original, dict):
        return [f"{name}: original model report and equal-Head report both required"]
    if (parity.get("schema") != SCHEMA or parity.get("candidate") != name
            or parity.get("mode") != "SHADOW_ONLY" or parity.get("authority") != "DENY_ALL"
            or parity.get("production_activation_allowed") is not False
            or parity.get("independent_observer_attested") is not False
            or parity.get("target_host_qualified") is not False
            or parity.get("original_policy_unchanged") is not True):
        errors.append(f"{name}: parity provenance or authority status drift")
    weight_sha = registry["models"][name]["weight_sha256"]
    if (parity.get("checkpoint_weight_sha256") != weight_sha or
            not isinstance(original.get("checkpoint"), dict) or
            original["checkpoint"].get("loaded_weight_sha256") != weight_sha or
            parity.get("frozen_selected_rows_sha256") != original.get("frozen_selected_rows_sha256") or
            parity.get("source_archive_sha256") != original.get("source_archive_sha256")):
        errors.append(f"{name}: frozen original checkpoint or source rows are not bound")
    if (parity.get("projection") != "frozen_gaussian_256d_v1"
            or parity.get("projection_seed") != 2307
            or not isinstance(parity.get("projection_sha256"), str)
            or not SHA64.fullmatch(parity["projection_sha256"])
            or type(parity.get("original_feature_width")) is not int
            or not 256 <= parity["original_feature_width"] <= 4096
            or parity.get("output_width") != 256 or parity.get("context_tokens") != 192
            or parity.get("trained_head_parameter_count") != 1028
            or parity.get("head_artifact_format") != "safetensors-f32-linear"
            or parity.get("head_reloaded_identical_logits") is not True
            or parity.get("head_artifact_bytes") != len(head_bytes)
            or not verify_head_artifact(head_bytes, parity.get("head_artifact_sha256"))):
        errors.append(f"{name}: exact frozen projection or 1028-param persisted Head evidence missing")
    training = parity.get("head_training")
    if (not isinstance(training, dict) or training.get("seed") != 7
            or training.get("optimizer") != "AdamW" or training.get("steps") != 200
            or training.get("learning_rate") != .05
            or training.get("head_parameters") != 1028
            or parity.get("temperature") not in (0.5, 1., 2., 4.)):
        errors.append(f"{name}: optimizer and calibration budget differ")
    if (parity.get("evaluation_scope") != "historical_2014_en_only_frozen_encoder_vs_task_head"
            or parity.get("real_encoder_forward_calls") != original.get("observed_forward_calls")
            or parity.get("original_full_policy_forward_calls") !=
               (original.get("observed_forward_calls") if name.startswith("laya_") else 0)):
        errors.append(f"{name}: real forward count or historical-only scope drift")
    scores = parity.get("scores")
    original_scores = original.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(SPLITS):
        errors.append(f"{name}: complete parity predictions missing")
        return errors
    if not isinstance(original_scores, dict) or set(original_scores) != set(SPLITS):
        errors.append(f"{name}: original policy/encoder predictions missing")
        return errors
    for split in SPLITS:
        try:
            entry = scores[split]
            if not isinstance(entry, dict) or set(entry) != {"rows", "metrics"}:
                raise ValueError("raw prediction schema invalid")
            rows = entry["rows"]
            if entry["metrics"] != score_rows(rows):
                raise ValueError("reported metrics do not equal raw predictions")
            original_rows = original_scores[split]["rows"]
            select = lambda r: (r["source_id"], r["source_group_id"], r["label"], r["is_ood"], r["language"])
            if [select(r) for r in rows] != [select(r) for r in original_rows]:
                raise ValueError("parity sample or gold row differs from original run")
            if any(r["is_ood"] is not (split == "ood") or r["language"] != "en" for r in rows):
                raise ValueError("historical OOD/language flags changed")
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            errors.append(f"{name}:{split}: {exc}")
    return errors


def audit_all(registry: dict, observations: dict) -> dict:
    errors = validate_registry(registry)
    if set(observations) != set(EXPECTED):
        errors.append("all five independently retained original and equal-Head artifacts required")
    for name in EXPECTED:
        record = observations.get(name)
        if record is None:
            errors.append(f"{name}: physical pair missing")
        else:
            errors.extend(audit_arm(name, *record, registry))
    return {"schema": "hepta.neuron.replacement-frozen-head-audit.v1",
            "preflight": "BLOCKED" if errors else "REVIEW_REQUIRED",
            "blockers": sorted(set(errors)), "authority": "DENY_ALL",
            "production_activation_allowed": False,
            "all_six_production_blockers_closed": False,
            "real_head_artifacts_count": len(observations),
            "limitations": ["reported original-model and input tensors not independently attested",
                            "no equal full-model finetuning; only frozen 256d Head parity",
                            "2014 English source; no multilingual/retrieval or prospective outcome",
                            "target-host 64..4096 Cell and signed lifecycle evidence absent"]}


def load_artifacts(root: Path, exact_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", exact_sha):
        raise ValueError("exact Git SHA required for five-Head artifact identity")
    observations = {}
    for name in EXPECTED:
        directory = root / f"neuron-physical-{name}-{exact_sha}"
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            report = _strict_json(_regular_bounded(directory / "equal-head-output.json", JSON_BYTES_MAX))
            original = _strict_json(_regular_bounded(directory / "physical-output.json", JSON_BYTES_MAX))
            artifact = _regular_bounded(directory / "equal-head.safetensors", HEAD_BYTES_MAX)
        except (OSError, ValueError, UnicodeError):
            continue
        observations[name] = (report, original, artifact)
    return observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(Path(__file__).with_name("replacement_models.json")))
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        registry = _strict_json(_regular_bounded(Path(args.registry), 32 * 1024))
        audit = audit_all(registry, load_artifacts(args.input_directory, args.expected_sha))
    except (OSError, ValueError, TypeError) as exc:
        audit = {"preflight": "BLOCKED", "blockers": [str(exc)],
                 "production_activation_allowed": False, "authority": "DENY_ALL"}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(audit, sort_keys=True))
    return 0 if audit["preflight"] == "REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
