"""One frozen owner forward, with selectable retained detail and event binding."""

from dataclasses import asdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import time

import torch

from feature_bundle import (FeatureBundleV1, FeatureIdentityV1, MAX_ELEMENTS,
                            MAX_TOKENS, MODALITIES)
from real_encoder import (FrozenRealEncoder, MAX_INPUT_ELEMENTS, PROFILES,
                          canonical_sha256, pool_features, source_digests)
from shared_feature_contract import SharedFeatureBatch, SharedFeatureError, SourceEvent

PREPROCESS_PACKAGES = ("torch", "transformers", "tokenizers", "numpy", "Pillow", "torchvision",
                       "librosa", "soundfile", "scipy", "soxr", "torchcodec", "av")


def preprocessing_runtime():
    result = {}
    for name in PREPROCESS_PACKAGES:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


class SharedFeatureEncoder:
    """Reuse a pinned model owner; Cell-specific prompts never enter this API."""

    def __init__(self, owner):
        if not isinstance(owner, FrozenRealEncoder) or owner.candidate not in (
                "granite97m", "embeddinggemma2_740m"):
            raise SharedFeatureError("a pinned Granite or EmbeddingGemma2 owner is required")
        self.owner = owner
        self._identity = owner.identity
        self._runtime_versions = preprocessing_runtime()
        paths = (Path(__file__), Path(__file__).with_name("shared_feature_contract.py"))
        self.extractor_sha256 = canonical_sha256({"preprocessing_runtime": self._runtime_versions,
            "source_files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}})
        self._configuration = self._configuration_digest()
        self.last_receipt = None

    def _configuration_digest(self):
        owner = self.owner
        return canonical_sha256({name: getattr(owner, name) for name in (
            "candidate", "profile", "device", "inventory_sha256", "max_tokens", "task",
            "spec", "prefix")})

    def _preflight(self, events, retention, expected_identity):
        if (type(expected_identity) is not FeatureIdentityV1
                or self.owner.identity != expected_identity or self._identity != expected_identity
                or self._configuration_digest() != self._configuration):
            raise SharedFeatureError("stale encoder/preprocessing/generation identity")
        if (retention not in ("global", "tokens") or not isinstance(events, (list, tuple))
                or not events or any(type(event) is not SourceEvent for event in events)):
            raise SharedFeatureError("typed events and a declared feature retention mode required")
        return tuple(events)

    def extract_text(self, texts, *, events, expected_identity, retention="global"):
        """Character spans refer only to actual original text, excluding prefixes."""
        owner = self.owner
        with owner._lock:
            started = time.perf_counter()
            events = self._preflight(events, retention, expected_identity)
            sources = source_digests(texts, [asdict(event) for event in events])
            offsets = retention == "tokens" and owner._tokenizer.is_fast
            inputs = owner._tokenizer([owner.prefix + text for text in texts], padding=True,
                truncation=True, max_length=owner.max_tokens, return_tensors="pt",
                return_token_type_ids=False, return_offsets_mapping=offsets)
            raw_spans = inputs.pop("offset_mapping", None)
            spans = valid = None
            if raw_spans is not None:
                spans = raw_spans.clone().to(torch.int64)
                prefix = len(owner.prefix)
                valid = ((spans[:, :, 0] >= prefix) & (spans[:, :, 1] > spans[:, :, 0])
                         & inputs["attention_mask"].bool())
                spans -= prefix
                spans[~valid] = 0
                lengths = torch.tensor([len(text) for text in texts]).unsqueeze(1)
                if bool(((spans[:, :, 1] > lengths) & valid).any()):
                    raise SharedFeatureError("tokenizer offsets exceed original source text")
            return self._forward(inputs, sources, [("text",)] * len(texts), events,
                                 retention, started, spans, valid)

    def extract_records(self, records, *, media_root, events, expected_identity,
                        retention="global"):
        """Use sealed local EG2 media; source times do not imply token timestamps."""
        owner = self.owner
        if owner.candidate != "embeddinggemma2_740m":
            raise SharedFeatureError("media requires the shared EmbeddingGemma2 owner")
        from teacher_forward import validate_records
        from teacher_media_seal import sealed_media_inputs
        from teacher_snapshot import inventory
        from transformers import AutoProcessor
        with owner._lock:
            started = time.perf_counter()
            events = self._preflight(events, retention, expected_identity)
            conversations, content_digest = validate_records(records, media_root, owner.candidate)
            rows = tuple(dict(row) for row in records)
            if any("text" not in row or not set(row).issubset({"text", *PROFILES[owner.profile]})
                   for row in rows):
                raise SharedFeatureError("record modality exceeds loaded profile")
            text_sources = source_digests([row["text"] for row in rows],
                                          [asdict(event) for event in events])
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
            if canonical_sha256(row_sources) != content_digest:
                raise SharedFeatureError("media changed during event-source binding")
            sources = tuple(canonical_sha256({"text_source": text, "media_sources": media})
                            for text, media in zip(text_sources, row_sources))
            if owner._processor is None:
                if inventory(owner.snapshot)["inventory_sha256"] != owner.inventory_sha256:
                    raise SharedFeatureError("processor snapshot changed before loading")
                owner._processor = AutoProcessor.from_pretrained(
                    owner.snapshot, local_files_only=True, trust_remote_code=False)
            with sealed_media_inputs(records=list(rows), media_root=media_root,
                    candidate=owner.candidate, expected_source_digest=content_digest,
                    original_conversations=conversations, validate_records=validate_records) as frozen:
                for conversation in frozen:
                    conversation[0]["content"][0]["text"] = (
                        owner.prefix + conversation[0]["content"][0]["text"])
                inputs = owner._processor.apply_chat_template(frozen, tokenize=True,
                    processor_kwargs={"padding": True}, return_dict=True, return_tensors="pt")
            return self._forward(inputs, sources, [tuple(row) for row in rows], events,
                                 retention, started)

    def _forward(self, inputs, sources, modalities, events, retention, started,
                 char_spans=None, char_valid=None):
        owner = self.owner
        allowed = {"input_ids", "attention_mask", "pixel_values", "image_position_ids",
                   "input_features", "input_features_mask", "pixel_values_videos",
                   "video_position_ids", "num_frames_per_video"}
        if not hasattr(inputs, "keys") or not set(inputs).issubset(allowed):
            raise SharedFeatureError("unexpected processor fields")
        ids, mask = inputs.get("input_ids"), inputs.get("attention_mask")
        if (not isinstance(ids, torch.Tensor) or not isinstance(mask, torch.Tensor)
                or ids.ndim != 2 or ids.shape != mask.shape or ids.shape[0] != len(sources)
                or ids.dtype != torch.int64 or not 0 < ids.shape[1] <= owner.max_tokens
                or not bool((ids >= 0).all()) or not bool(((mask == 0) | (mask == 1)).all())
                or not bool((mask.sum(1) > 0).all())):
            raise SharedFeatureError("invalid or unbounded token tensor")
        batch, sequence = ids.shape
        retained = batch * (owner.spec["width"] + len(MODALITIES))
        if retention == "tokens":
            retained += batch * sequence * (owner.spec["width"] + 5)
            if sequence > MAX_TOKENS:
                raise SharedFeatureError("retained token count exceeds feature budget")
        if retained > MAX_ELEMENTS:
            raise SharedFeatureError("retained feature budget exceeded before forward")
        if (any(not isinstance(value, torch.Tensor) or value.device.type != "cpu"
                for value in inputs.values())
                or sum(value.numel() for value in inputs.values()) > MAX_INPUT_ELEMENTS
                or any(value.is_floating_point() and not bool(torch.isfinite(value).all())
                       for value in inputs.values())):
            raise SharedFeatureError("nonfinite or oversized processor tensor")
        if any(m.training for m in owner._model.modules()) or any(
                parameter.requires_grad for parameter in owner._model.parameters()):
            raise SharedFeatureError("shared model must remain frozen and in evaluation mode")
        uploaded = {name: value.to(owner.device) for name, value in inputs.items()}
        calls = [0]
        def entered(_module, _args):
            calls[0] += 1
        handle = owner._model.register_forward_pre_hook(entered)
        if owner.device == "cuda":
            torch.cuda.synchronize()
        forward_start = time.perf_counter()
        try:
            with torch.inference_mode():
                tokens = owner._model(**uploaded).last_hidden_state
                pooled = pool_features(tokens, uploaded["attention_mask"], owner.spec["pooling"])
            if owner.device == "cuda":
                torch.cuda.synchronize()
        finally:
            handle.remove()
            owner._calls += calls[0]
        forward_ms = (time.perf_counter() - forward_start) * 1000
        if calls[0] != 1 or tokens.shape != (*ids.shape, owner.spec["width"]):
            raise SharedFeatureError("one native-width model forward required")
        views = {}
        if retention == "tokens":
            kinds = torch.zeros_like(ids)
            if owner.candidate == "embeddinggemma2_740m":
                for name in ("image", "audio", "video"):
                    token_id = getattr(owner._model.config, name + "_token_id", None)
                    if token_id is not None:
                        kinds[ids == token_id] = MODALITIES.index(name)
            kinds[mask == 0] = -1
            views = {"token_features": tokens.detach().float().cpu() * mask.unsqueeze(-1),
                     "token_valid": mask.bool(), "modality_ids": kinds}
        bundle = FeatureBundleV1.from_tensors(identity=owner.identity,
            source_record_digests=sources, global_features=pooled.detach().float().cpu(),
            missing_mask=torch.tensor([[name not in present for name in MODALITIES]
                                       for present in modalities]), **views)
        result = SharedFeatureBatch.seal(bundle, events, extractor_sha256=self.extractor_sha256,
                                         char_spans=char_spans, char_valid=char_valid)
        self.last_receipt = {
            "schema": "hepta.shared-event-feature-forward.v1", "candidate": owner.candidate,
            "checkpoint_revision": owner.identity.checkpoint_revision,
            "checkpoint_inventory_sha256": owner.inventory_sha256,
            "encoder_identity": asdict(owner.identity),
            "preprocessing_runtime": dict(self._runtime_versions),
            "feature_extractor_sha256": self.extractor_sha256,
            "feature_identity_sha256": result.feature_identity_digest,
            "feature_bundle_sha256": result.bundle_digest, "retention": retention,
            "model_forward_calls": calls[0], "model_forward_calls_total": owner._calls,
            "forward_ms": forward_ms,
            "encode_ms": (time.perf_counter() - started) * 1000,
            "batch_size": batch, "token_count": int(mask.sum()),
            "retained_tensor_bytes": result.retained_tensor_bytes,
            "loaded_model": dict(owner.accounting), "device": owner.device,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
        owner.last_receipt = dict(self.last_receipt)
        return result
