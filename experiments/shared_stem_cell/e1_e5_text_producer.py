"""E1 operator-staged real-weight text feature producer; no network or synthetic fallback.

Requires all three complete, locally vetted model snapshots and label-free
joint task requests. This module is NOT a production inference Worker.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from execution import InputError, LocalEncoder, bound_file, canonical, decode, measured, sha, verify_snapshot, write_once
from e1_e5_trial import MODELS, digest, vector


def _checked_text(value):
    if not isinstance(value, str) or not value or len(value.encode()) > 16384:
        raise InputError("unbounded or empty text")
    return value


def typed_payload(row):
    if type(row) is not dict or set(row) != {"case_id", "scope", "state", "question", "options", "evidence", "input_sha256"}:
        raise InputError("full state/question/choices/evidence needed")
    if (not isinstance(row["case_id"], str) or not row["case_id"] or
            not isinstance(row["scope"], str) or not row["scope"]):
        raise InputError("invalid typed case")
    state, question, evidence = (_checked_text(row[x]) for x in ("state", "question", "evidence"))
    choices = row["options"]
    if not isinstance(choices, list) or len(choices) != 2:
        raise InputError("strict two-choice relation study")
    choices = [_checked_text(v) for v in choices]
    source = ["hepta.stem.e1-e5.typed-input.v1", row["scope"], state, question, choices, evidence]
    if sha(canonical(source)) != row["input_sha256"]:
        raise InputError("actual joint task input differs from source digest")
    full = {"state": state, "question": question, "options": choices, "evidence": evidence}
    query = {"state": state, "question": question, "options": choices}
    # Canonical JSON prevents provider-specific accidental omission of state/options.
    return canonical(full).decode().strip(), canonical(query).decode().strip(), evidence


class TextTower:
    def __init__(self, key, root, descriptor):
        self.key, self.root, self.descriptor = key, root, descriptor
        self.width, self.pooling, self.source = MODELS[key]
        self.count = self.api_calls = self.tokens = 0
        self.maximum_tokens = descriptor["maximum_tokens"]
        if type(self.maximum_tokens) is not int or not 8 <= self.maximum_tokens <= 8192:
            raise InputError("bad max tokens")
        # The full snapshot identity is re-hashed after each model inference phase.
        self.model_manifest = {"revision": descriptor["revision"], "files": descriptor["files"],
                               "kind": "encoder"}
        self.manifest_sha = verify_snapshot(root, self.model_manifest)
        if key == "embeddinggemma2_text":
            # Lazy import: lacking an approved runtime is a HARD failure.
            from sentence_transformers import SentenceTransformer
            self.st = SentenceTransformer(str(root), device="cpu", local_files_only=True,
                                          trust_remote_code=False,
                                          model_kwargs={"torch_dtype": torch.float32},
                                          config_kwargs={"vision_config": None, "audio_config": None})
            self.st.eval()
            if (not isinstance(getattr(self.st, "prompts", None), dict) or
                    not {"Classification", "SearchQuery", "Document"} <= set(self.st.prompts)):
                raise InputError("missing official task prompt interface")
            self.tokenizer = self.st.tokenizer
        else:
            self.encoder = LocalEncoder(root, self.model_manifest, self.maximum_tokens)
            self.tokenizer = self.encoder.tokenizer

    def encode(self, values, role):
        if role not in {"joint", "query", "evidence"} or not 1 <= len(values) <= 16:
            raise InputError("unregistered typed encoding batch")
        prompt = {"joint": "Classification", "query": "SearchQuery", "evidence": "Document"}[role]
        payload = []
        for text in values:
            text = _checked_text(text)
            prefix = self.st.prompts[prompt] if self.key == "embeddinggemma2_text" else ""
            ids = self.tokenizer(prefix + text, truncation=False, add_special_tokens=True)["input_ids"]
            if not ids or len(ids) > self.maximum_tokens:
                raise InputError("tokenized text exceeds exact limit; no truncation")
            self.tokens += len(ids)
            payload.append(text)
        if self.key == "embeddinggemma2_text":
            with torch.inference_mode():
                vec = self.st.encode(payload, prompt_name=prompt, batch_size=len(payload),
                                     truncate_dim=256, normalize_embeddings=True,
                                     convert_to_tensor=True, show_progress_bar=False)
            self.api_calls += 1
            value = torch.as_tensor(vec, dtype=torch.float32).cpu()
        else:
            tokens = self.tokenizer(payload, padding=True, truncation=False, return_tensors="pt")
            with torch.inference_mode():
                hidden = self.encoder.model(**tokens).last_hidden_state
                if self.pooling == "cls_l2":
                    pooled = hidden[:, 0]
                elif self.pooling == "masked_mean_l2":
                    mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                    pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
                else:
                    raise InputError("unsupported model-specific pooling")
                value = F.normalize(pooled.float(), p=2, dim=-1).cpu()
            self.count += 1  # observed one physical model invocation, not backend subcalls
        if value.shape != (len(payload), self.width) or not bool(torch.isfinite(value).all()):
            raise InputError("unexpected actual model feature shape")
        if bool(((torch.linalg.vector_norm(value, dim=1) - 1).abs() > .005).any()):
            raise InputError("non-normalized real Encoder features")
        return [vector(row.tolist(), self.width, "actual text feature") for row in value]

    def close(self):
        verify_snapshot(self.root, self.model_manifest)
        if self.key != "embeddinggemma2_text":
            self.encoder.close()


def produce(manifest: Path, manifest_hash: str, output_dir: Path):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    raw = bound_file(manifest, manifest_hash)
    cfg = decode(raw)
    if (type(cfg) is not dict or set(cfg) != {"schema", "requests", "models"}
            or cfg["schema"] != "hepta.stem-e1-e5.text-producer.v1"
            or set(cfg["models"]) != set(MODELS)):
        raise InputError("unqualified producer plan")
    ref = cfg["requests"]
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise InputError("unbound request file")
    path = Path(ref["path"])
    if path.is_absolute() or ".." in path.parts:
        raise InputError("unapproved request path")
    cases = decode(bound_file(manifest.parent / path, ref["sha256"]))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 2048:
        raise InputError("unbounded label-free case panel")
    seen = set()
    payloads = []
    for row in cases:
        if row["case_id"] in seen:
            raise InputError("duplicate producer input")
        seen.add(row["case_id"])
        payloads.append(typed_payload(row))
    for key in MODELS:
        spec = cfg["models"][key]
        fields = {"source", "snapshot", "revision", "files", "weights_sha256", "maximum_tokens", "license_approved"}
        if not isinstance(spec, dict) or set(spec) != fields or spec["source"] != MODELS[key][2] or spec["license_approved"] is not True:
            raise InputError("all three models must pass preflight")
        name = Path(spec["snapshot"])
        if name.is_absolute() or ".." in name.parts or not digest(spec["weights_sha256"]):
            raise InputError("unsafe model identity")
        model_root = manifest.parent / name
        forbidden = {".py", ".pyc", ".pkl", ".pickle", ".pt", ".pth", ".bin",
                     ".so", ".dylib", ".dll", ".exe", ".sh", ".bat", ".ps1"}
        if (model_root.is_symlink() or not model_root.is_dir() or
                any((model_root / part).is_symlink() for part in spec["files"]) or
                any(Path(part).suffix.lower() in forbidden for part in spec["files"])):
            raise InputError("unreviewed executable/pickle weight or symlink in model source")
        verify_snapshot(model_root, {"revision": spec["revision"], "files": spec["files"], "kind": "encoder"})
    output_dir.mkdir(parents=True, exist_ok=False)
    result = []
    try:
        for key in MODELS:
            spec = cfg["models"][key]
            expected = {"source", "snapshot", "revision", "files", "weights_sha256", "maximum_tokens", "license_approved"}
            if not isinstance(spec, dict) or set(spec) != expected or spec["source"] != MODELS[key][2]:
                raise InputError("invalid source model")
            if spec["license_approved"] is not True:
                raise InputError("model license not approved for study")
            root = manifest.parent / spec["snapshot"]
            if (Path(spec["snapshot"]).is_absolute() or ".." in Path(spec["snapshot"]).parts
                    or not root.is_dir() or root.is_symlink()):
                raise InputError("unapproved local model snapshot path")
            # This hash is the externally pinned bundle hash, distinct from each member.
            if not digest(spec["weights_sha256"]):
                raise InputError("bundle identity required")
            with measured() as meter:
                tower = TextTower(key, root, spec)
                output = [[], [], []]
                for start in range(0, len(cases), 8):
                    chunk = payloads[start:start + 8]
                    for index, role in enumerate(("joint", "query", "evidence")):
                        output[index].extend(tower.encode([x[index] for x in chunk], role))
                tower.close()
            receipt = {"schema": "hepta.stem-e1-e5.real-local-text-receipt.v1", "model_id": key,
                       "upstream_source": MODELS[key][2], "revision": spec["revision"],
                       "snapshot_manifest_sha256": tower.manifest_sha,
                       "externally_claimed_weight_bundle_sha256": spec["weights_sha256"],
                       "dataset_sha256": ref["sha256"], "rows": len(cases),
                       "observed_model_forward_invocations": tower.count if key != "embeddinggemma2_text" else None,
                       "sentence_transformer_encode_calls": tower.api_calls if key == "embeddinggemma2_text" else None,
                       "nontruncated_token_total": tower.tokens,
                       "measured": meter, "independent_origin_verified": False,
                       "native_worker": False, "production_promotion_permitted": False}
            receipt_sha = write_once(output_dir / (key + ".receipt.json"), receipt)
            for i, c in enumerate(cases):
                result.append({"case_id": c["case_id"], "model_id": key,
                               "input_sha256": c["input_sha256"],
                               "vector": output[0][i], "query_vector": output[1][i],
                               "evidence_vector": output[2][i], "revision": spec["revision"],
                               "weights_sha256": spec["weights_sha256"],
                               "producer_receipt_sha256": receipt_sha})
        source_digest = write_once(output_dir / "features.json", result)
        write_once(output_dir / "disposition.json", {
            "schema": "hepta.stem-e1-e5.text-producer-disposition.v1",
            "source_manifest_sha256": manifest_hash, "feature_rows_sha256": source_digest,
            "model_weights_executed": True, "model_origin_independently_authenticated": False,
            "owner_signed": False, "multimodal_capability_measured": False,
            "production_promotion_permitted": False})
        return source_digest
    except Exception as exc:
        write_once(output_dir / "failure.json", {"schema": "hepta.stem-e1-e5.text-producer-failure.v1",
            "exception": type(exc).__name__, "message": str(exc),
            "partial_results_must_be_retained": True, "production_promotion_permitted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print("real_feature_bank_sha256=" + produce(args.manifest, args.manifest_sha256, args.output_dir))
