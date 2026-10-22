"""Pinned local frozen encoders; real outputs, no model-quality qualification.

The checkpoint inventory is verified before and after loading. This is an
offline research owner, not a sandbox against a process able to mutate its
memory. Model/processor code comes from installed Transformers, never the Hub.
"""

import hashlib
import hmac
import json
from pathlib import Path
import threading
import time

from teacher_snapshot import inventory

CANDIDATES = json.loads(Path(__file__).with_name("real_encoder_candidates.json").read_text())
PROFILES = {"text": (), "text_image": ("image",), "text_audio": ("audio",),
            "full": ("image", "audio", "video")}
TASK_PREFIXES = {"classification": "task: classification | query: ",
                 "retrieval_query": "task: search result | query: ",
                 "retrieval_document": "title: none | text: ",
                 "similarity": "task: sentence similarity | query: "}
MAX_BATCH = 32
MAX_INPUT_ELEMENTS = 32 * 1024 * 1024


class RealEncoderError(ValueError):
    pass


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_digests(texts, source_records=None):
    """Bind caller metadata to actual text, rather than accepting asserted hashes."""
    if (not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= MAX_BATCH
            or any(not isinstance(x, str) or not x.strip() or len(x) > 16384 for x in texts)):
        raise RealEncoderError("expected 1..32 bounded nonempty text inputs")
    rows = [{} for _ in texts] if source_records is None else source_records
    if not isinstance(rows, (list, tuple)) or len(rows) != len(texts):
        raise RealEncoderError("source records must match the text batch")
    result = []
    for text, record in zip(texts, rows):
        if not isinstance(record, dict) or ("text" in record and record["text"] != text):
            raise RealEncoderError("source record text does not match encoded text")
        try:
            encoded = json.dumps({"text": text, "record": record}, ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise RealEncoderError("source record must be finite JSON") from error
        if len(encoded.encode()) > 131072:
            raise RealEncoderError("source record metadata exceeds byte budget")
        result.append(hashlib.sha256(encoded.encode()).hexdigest())
    return tuple(result)


def verify_real_snapshot(snapshot, candidate, revision, expected_inventory_sha256,
                         operator_accepted_terms):
    spec = CANDIDATES.get(candidate)
    if spec is None or revision != spec["revision"]:
        raise RealEncoderError("candidate/revision is not the pinned upstream checkpoint")
    if operator_accepted_terms is not True:
        raise RealEncoderError("explicit operator license acceptance required")
    if (not isinstance(expected_inventory_sha256, str) or len(expected_inventory_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_inventory_sha256)):
        raise RealEncoderError("external expected inventory SHA256 required")
    data = inventory(snapshot)
    if not hmac.compare_digest(data["inventory_sha256"], expected_inventory_sha256):
        raise RealEncoderError("snapshot inventory does not match external pin")
    entries = {x["path"]: x for x in data["entries"]}
    if "model.safetensors" not in entries or "config.json" not in entries:
        raise RealEncoderError("offline safetensors and config.json required")
    if entries["config.json"]["bytes"] > 1024 * 1024:
        raise RealEncoderError("bounded config.json required")
    config_bytes = (Path(snapshot) / "config.json").read_bytes()
    if hashlib.sha256(config_bytes).hexdigest() != entries["config.json"]["sha256"]:
        raise RealEncoderError("config changed after inventory")
    config = json.loads(config_bytes)
    if not isinstance(config, dict) or config.get("model_type") != spec["model_type"]:
        raise RealEncoderError("incorrect checkpoint architecture")
    weights_hash = entries["model.safetensors"]["sha256"]
    if candidate == "mmbert_small":
        receipt_path = Path(snapshot) / "conversion_receipt.json"
        entry = entries.get("conversion_receipt.json")
        if not entry or entry["bytes"] > 32768:
            raise RealEncoderError("mmBERT requires bounded audited conversion receipt")
        raw = receipt_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise RealEncoderError("conversion receipt changed after inventory")
        receipt = json.loads(raw)
        if (receipt.get("schema") != "hepta.mmbert-weights-only-conversion.v1"
                or receipt.get("revision") != revision
                or receipt.get("source_bin_sha256") != spec["upstream_bin_sha256"]
                or receipt.get("output_safetensors_sha256") != weights_hash
                or receipt.get("weights_only") is not True):
            raise RealEncoderError("invalid mmBERT derived-weight provenance")
    elif weights_hash != spec["weight_sha256"]:
        raise RealEncoderError("checkpoint weights do not match pinned upstream LFS digest")
    return data


def physical_model_accounting(model):
    """Count actual parameter elements and distinct resident tensor storages."""
    parameters = list(model.parameters())
    storages = {}
    for tensor in parameters + list(model.buffers()):
        storage = tensor.untyped_storage()
        key = (str(tensor.device), storage.data_ptr(), storage.nbytes())
        storages[key] = storage.nbytes()
    return {"loaded_parameter_count": sum(p.numel() for p in parameters),
            "trainable_parameter_count": sum(p.numel() for p in parameters if p.requires_grad),
            "resident_tensor_storage_bytes": sum(storages.values()),
            "resident_storage_count": len(storages)}


def pool_features(tokens, mask, mode):
    import torch
    from torch.nn import functional as F
    if (tokens.ndim != 3 or mask.ndim != 2 or tokens.shape[:2] != mask.shape
            or not tokens.is_floating_point() or not bool(torch.isfinite(tokens).all())
            or not bool(((mask == 0) | (mask == 1)).all())
            or not bool((mask.sum(1) > 0).all())):
        raise RealEncoderError("invalid encoder states or attention mask")
    if mode == "cls":
        if not bool((mask[:, 0] == 1).all()):
            raise RealEncoderError("CLS position must be present")
        pooled = tokens[:, 0].float()
    elif mode == "mean":
        m = mask.unsqueeze(-1).float()
        pooled = (tokens.float() * m).sum(1) / m.sum(1)
    else:
        raise RealEncoderError("unregistered pooling mode")
    if not bool((pooled.norm(dim=-1) > 1e-8).all()):
        raise RealEncoderError("zero-norm pooled features")
    return F.normalize(pooled, dim=-1)


class FrozenRealEncoder:
    """One frozen model owner for many Cells, with explicit physical profiles."""

    def __init__(self, *, candidate, snapshot, revision, expected_inventory_sha256,
                 operator_accepted_terms, device="cpu", profile="text", max_tokens=128,
                 task="classification", generation=1, scope_id="research-local"):
        if profile not in PROFILES or device not in ("cpu", "cuda"):
            raise RealEncoderError("unknown physical profile or device")
        if candidate != "embeddinggemma2_740m" and profile != "text":
            raise RealEncoderError("this candidate is text-only")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 8192 or task not in TASK_PREFIXES:
            raise RealEncoderError("invalid sequence limit or task")
        self.snapshot = str(Path(snapshot).absolute())
        verified = verify_real_snapshot(self.snapshot, candidate, revision,
                                        expected_inventory_sha256, operator_accepted_terms)
        import torch
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        from feature_bundle import FeatureIdentityV1
        if device == "cuda" and not torch.cuda.is_available():
            raise RealEncoderError("CUDA requested but unavailable")
        self.candidate, self.profile, self.device = candidate, profile, device
        self.inventory_sha256 = verified["inventory_sha256"]
        self.snapshot_artifact_bytes = verified["total_bytes"]
        self.max_tokens, self.task = max_tokens, task
        self.spec = dict(CANDIDATES[candidate])
        self.prefix = TASK_PREFIXES[task] if candidate == "embeddinggemma2_740m" else ""
        self._lock, self._calls, self._processor = threading.RLock(), 0, None
        self.last_receipt = None
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        start = time.perf_counter()
        kwargs = {"local_files_only": True, "trust_remote_code": False}
        tok_path = str(Path(self.snapshot) / "tokenizer") if candidate == "laya_encoder_only" else self.snapshot
        self._tokenizer = AutoTokenizer.from_pretrained(tok_path, **kwargs)
        if candidate == "laya_encoder_only":
            from safetensors import safe_open
            config = AutoConfig.from_pretrained(str(Path(self.snapshot) / "encoder"), **kwargs)
            self._model = AutoModel.from_config(config, trust_remote_code=False)
            with safe_open(str(Path(self.snapshot) / "model.safetensors"), framework="pt", device="cpu") as weights:
                state = {key[len("encoder."):]: weights.get_tensor(key)
                         for key in weights.keys() if key.startswith("encoder.")}
            self._model.load_state_dict(state, strict=True)
            del state
        else:
            config = AutoConfig.from_pretrained(self.snapshot, **kwargs)
            if candidate == "embeddinggemma2_740m":
                if "image" not in PROFILES[profile]:
                    config.vision_config = None
                if "audio" not in PROFILES[profile]:
                    config.audio_config = None
            self._model, loading = AutoModel.from_pretrained(
                self.snapshot, config=config, dtype=dtype, attn_implementation="sdpa",
                output_loading_info=True, **kwargs)
            allowed_unused = ("head.", "decoder.") if candidate == "mmbert_small" else ()
            if candidate == "embeddinggemma2_740m":
                if "image" not in PROFILES[profile]:
                    allowed_unused += ("vision_tower.", "embed_vision.")
                if "audio" not in PROFILES[profile]:
                    allowed_unused += ("audio_tower.", "embed_audio.")
            if (loading.get("missing_keys") or loading.get("mismatched_keys") or loading.get("error_msgs")
                    or any(not key.startswith(allowed_unused) for key in loading.get("unexpected_keys", []))):
                raise RealEncoderError("checkpoint did not fully initialize the declared encoder: " + str(loading))
        self._model.to(device=device, dtype=dtype).requires_grad_(False).eval()
        # Catch file mutation during loading; do not describe an unsealed local
        # path as independent publisher attestation.
        if inventory(self.snapshot)["inventory_sha256"] != expected_inventory_sha256:
            raise RealEncoderError("snapshot changed during model load")
        self.load_ms = (time.perf_counter() - start) * 1000
        self.accounting = physical_model_accounting(self._model)
        model_id = {"candidate": candidate, "revision": revision,
                    "inventory_sha256": verified["inventory_sha256"], "profile": profile,
                    "dtype": str(dtype), "pooling": self.spec["pooling"]}
        preprocess = {"model_identity": model_id, "task": task, "prefix": self.prefix,
                      "max_tokens": max_tokens, "padding": "longest", "truncation": True,
                      "torch": torch.__version__}
        import transformers
        preprocess["transformers"] = transformers.__version__
        self.identity = FeatureIdentityV1(
            encoder_sha256=canonical_sha256(model_id), checkpoint_revision=revision,
            preprocess_sha256=canonical_sha256(preprocess), generation=generation, scope_id=scope_id)

    def encode_text(self, texts, *, source_records=None):
        sources = source_digests(texts, source_records)
        with self._lock:
            start = time.perf_counter()
            inputs = self._tokenizer([self.prefix + x for x in texts], padding=True,
                                     truncation=True, max_length=self.max_tokens,
                                     return_tensors="pt", return_token_type_ids=False)
            return self._forward(inputs, sources, [("text",)] * len(texts), start)

    def encode_records(self, records, *, media_root, source_records=None):
        """EG2 text plus local image/audio/video, sealed before preprocessing.

        Native token modality markers are retained; no invented region boxes or
        time alignment are attached to contextualized states.
        """
        if self.candidate != "embeddinggemma2_740m":
            raise RealEncoderError("media encoding is supported only by EmbeddingGemma2")
        from teacher_forward import validate_records
        from teacher_media_seal import sealed_media_inputs
        from transformers import AutoProcessor
        conversations, digest = validate_records(records, media_root, self.candidate)
        rows = tuple(dict(row) for row in records)
        if any("text" not in row or not set(row).issubset({"text", *PROFILES[self.profile]}) for row in rows):
            raise RealEncoderError("record modality is outside the loaded physical profile")
        source_meta = [{} for _ in rows] if source_records is None else source_records
        text_hashes = source_digests([row["text"] for row in rows], source_meta)
        row_sources = []
        for conversation in conversations:
            bound = []
            for part in conversation[0]["content"]:
                sha = hashlib.sha256()
                if part["type"] == "text":
                    sha.update(part["text"].encode())
                else:
                    with Path(part["url"]).open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            sha.update(chunk)
                bound.append((part["type"], sha.hexdigest()))
            row_sources.append(bound)
        if canonical_sha256(row_sources) != digest:
            raise RealEncoderError("media changed while binding individual source records")
        sources = tuple(canonical_sha256({"text_source": value, "media_sources": bound})
                        for value, bound in zip(text_hashes, row_sources))
        with self._lock:
            start = time.perf_counter()
            if self._processor is None:
                self._processor = AutoProcessor.from_pretrained(
                    self.snapshot, local_files_only=True, trust_remote_code=False)
            with sealed_media_inputs(records=list(rows), media_root=media_root, candidate=self.candidate,
                                     expected_source_digest=digest, original_conversations=conversations,
                                     validate_records=validate_records) as frozen:
                for conversation in frozen:
                    conversation[0]["content"][0]["text"] = self.prefix + conversation[0]["content"][0]["text"]
                inputs = self._processor.apply_chat_template(frozen, tokenize=True,
                    processor_kwargs={"padding": True}, return_dict=True, return_tensors="pt")
            return self._forward(inputs, sources, [tuple(row) for row in rows], start)

    def _forward(self, inputs, sources, modalities, started):
        import torch
        from feature_bundle import FeatureBundleV1, MAX_ELEMENTS, MAX_TOKENS, MODALITIES
        allowed = {"input_ids", "attention_mask", "pixel_values", "image_position_ids",
                   "input_features", "input_features_mask", "pixel_values_videos",
                   "video_position_ids", "num_frames_per_video"}
        if not hasattr(inputs, "keys") or not set(inputs).issubset(allowed):
            raise RealEncoderError("unexpected processor fields")
        ids, mask = inputs.get("input_ids"), inputs.get("attention_mask")
        if (not isinstance(ids, torch.Tensor) or not isinstance(mask, torch.Tensor)
                or ids.ndim != 2 or ids.shape != mask.shape or ids.shape[0] != len(sources)
                or not 0 < ids.shape[1] <= self.max_tokens or ids.dtype != torch.int64
                or not bool((ids >= 0).all())
                or not bool(((mask == 0) | (mask == 1)).all())
                or not bool((mask.sum(1) > 0).all())):
            raise RealEncoderError("invalid or unbounded token tensor")
        batch, sequence = ids.shape
        feature_elements = batch * (self.spec["width"] * (sequence + 1) + 2 * sequence + 5)
        if sequence > MAX_TOKENS or feature_elements > MAX_ELEMENTS:
            raise RealEncoderError("requested token bundle exceeds snapshot budget before forward")
        if (any(not isinstance(x, torch.Tensor) or x.device.type != "cpu" for x in inputs.values())
                or sum(x.numel() for x in inputs.values()) > MAX_INPUT_ELEMENTS
                or any(x.is_floating_point() and not bool(torch.isfinite(x).all()) for x in inputs.values())):
            raise RealEncoderError("nonfinite or oversized processor tensors")
        if any(m.training for m in self._model.modules()) or any(p.requires_grad for p in self._model.parameters()):
            raise RealEncoderError("shared encoder must remain frozen and in eval mode")
        kinds = torch.zeros_like(ids, dtype=torch.int64)
        if self.candidate == "embeddinggemma2_740m":
            for modality in ("image", "audio", "video"):
                token_id = getattr(self._model.config, modality + "_token_id", None)
                if token_id is not None:
                    kinds[ids == token_id] = MODALITIES.index(modality)
        kinds[mask == 0] = -1
        missing = torch.tensor([[name not in present for name in MODALITIES] for present in modalities])
        uploaded = {key: value.to(self.device) for key, value in inputs.items()}
        calls = [0]
        def hook(_module, _args, _output):
            calls[0] += 1
        handle = self._model.register_forward_hook(hook)
        if self.device == "cuda":
            torch.cuda.synchronize()
        forward_start = time.perf_counter()
        try:
            with torch.inference_mode():
                tokens = self._model(**uploaded).last_hidden_state
                pooled = pool_features(tokens, uploaded["attention_mask"], self.spec["pooling"])
            if self.device == "cuda":
                torch.cuda.synchronize()
        finally:
            handle.remove()
        forward_ms = (time.perf_counter() - forward_start) * 1000
        if calls[0] != 1 or tokens.shape[-1] != self.spec["width"]:
            raise RealEncoderError("one owner forward with expected native width required")
        self._calls += calls[0]
        token_features = tokens.detach().float().cpu() * mask.unsqueeze(-1)
        bundle = FeatureBundleV1.from_tensors(
            identity=self.identity, source_record_digests=sources,
            global_features=pooled.detach().float().cpu(), token_features=token_features,
            token_valid=mask.bool(), modality_ids=kinds, missing_mask=missing)
        self.last_receipt = {
            "schema": "hepta.real-encoder-forward.v1", "candidate": self.candidate,
            "feature_bundle_sha256": bundle.bundle_digest,
            "profile": self.profile, "device": self.device,
            "checkpoint_revision": self.identity.checkpoint_revision,
            "checkpoint_inventory_sha256": self.inventory_sha256,
            "snapshot_artifact_bytes": self.snapshot_artifact_bytes,
            "loaded_scope": "encoder_only" if self.candidate == "laya_encoder_only" else self.profile,
            "checkpoint_parameter_count": self.spec["checkpoint_parameters"],
            **self.accounting, "load_ms": self.load_ms,
            "resident_storage_excludes": ["activations", "allocator_overhead", "tokenizer",
                                          "features", "cell_heads", "optimizer"],
            "model_forward_calls": calls[0], "model_forward_calls_total": self._calls,
            "forward_ms": forward_ms, "encode_ms": (time.perf_counter() - started) * 1000,
            "batch_size": len(sources), "token_count": int(mask.sum()),
            "physical_backend_kernel_count_attested": False,
            "model_performance_qualified": False, "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
        return bundle
