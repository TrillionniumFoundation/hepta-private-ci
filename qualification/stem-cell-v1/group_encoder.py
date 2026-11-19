"""Pinned, local-only frozen Granite token features for the research loop."""

import hashlib
import json
import shutil
from pathlib import Path

from group_features import FeatureIdentity, FeatureSnapshotV2, content_digest
from hf_encoder_kernel import validate_encoder_loading_info, verify_loaded_safetensors
from group_token_id_binding import token_ids_sha256

MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
         "special_tokens_map.json")


def digest_json(value):
    return content_digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode())


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def acquire(root):
    """Explicit public acquisition; lock revision and sizes before any transfer."""
    from huggingface_hub import HfApi, snapshot_download
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    info = HfApi(token=False).model_info(MODEL_ID, revision=REVISION, files_metadata=True)
    inventory = {f.rfilename: f.size for f in info.siblings if f.rfilename in FILES}
    if (info.sha != REVISION or set(inventory) != set(FILES)
            or any(type(n) is not int or n <= 0 for n in inventory.values())
            or sum(inventory.values()) > 512_000_000):
        raise ValueError("public source inventory differs from bounded model profile")
    lock = dict(model_id=MODEL_ID, revision=REVISION, files=inventory)
    (root / "source-lock.json").write_text(json.dumps(lock, sort_keys=True))
    downloaded = Path(snapshot_download(MODEL_ID, revision=REVISION, token=False,
                                       allow_patterns=list(FILES)))
    for name, size in inventory.items():
        if (downloaded / name).stat().st_size != size:
            raise ValueError("download size differs from source lock")
        shutil.copyfile(downloaded / name, root / name)
    lock["sha256"] = {name: file_digest(root / name) for name in FILES}
    (root / "material.json").write_text(json.dumps(lock, sort_keys=True))
    return root


class FrozenTokenEncoder:
    """One immutable eager CPU Encoder; cache ownership belongs to the caller."""

    def __init__(self, root, *, max_tokens=192):
        import torch
        import transformers
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        if (transformers.__version__ != "4.57.1" or type(max_tokens) is not int
                or not 1 <= max_tokens <= 256):
            raise ValueError("pinned Transformers and bounded tokens required")
        self.root, self.max_tokens, self.calls = Path(root), max_tokens, 0
        self.token_id_witnesses = {}
        self.material = json.loads((self.root / "material.json").read_text())
        if (self.material["model_id"], self.material["revision"]) != (MODEL_ID, REVISION):
            raise ValueError("unregistered public checkpoint")
        self.verify_files()
        config = AutoConfig.from_pretrained(str(self.root), local_files_only=True,
                                             trust_remote_code=False)
        if config.model_type != "modernbert" or config.hidden_size != 384:
            raise ValueError("unexpected Granite architecture")
        config.reference_compile = False
        model, info = AutoModel.from_pretrained(
            str(self.root), config=config, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, output_loading_info=True, attn_implementation="eager",
            torch_dtype=torch.float32)
        self.model = model.eval().requires_grad_(False)
        self.loading = validate_encoder_loading_info(info)
        self.tensor_verification = verify_loaded_safetensors(torch, self.model, self.root)
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.root), local_files_only=True,
                                                       trust_remote_code=False)
        self.tokenizer_digest = digest_json({n: self.material["sha256"][n]
                                            for n in FILES if "token" in n})
        self.preprocess_digest = digest_json(dict(max_tokens=max_tokens, truncate=False,
            precision="cpu-fp32", attention="eager", reference_compile=False,
            output="last_hidden_state", adapter=None,
            config_sha256=self.material["sha256"]["config.json"],
            weights_sha256=self.material["sha256"]["model.safetensors"]))

    def verify_files(self):
        if set(self.material["sha256"]) != set(FILES):
            raise ValueError("incomplete material inventory")
        if any(file_digest(self.root / n) != self.material["sha256"][n] for n in FILES):
            raise ValueError("checkpoint content changed")

    def identity(self, text, *, scope, generation):
        return FeatureIdentity(scope, generation, REVISION, self.tokenizer_digest,
                               self.preprocess_digest, content_digest(text.encode()), "text")

    def encode(self, text, identity):
        import torch
        if self.model.training or any(p.requires_grad for p in self.model.parameters()):
            raise ValueError("feature model is not frozen for inference")
        if identity != self.identity(text, scope=identity.scope, generation=identity.generation):
            raise ValueError("request identity does not bind actual encoder input")
        tokens = self.tokenizer(text, return_tensors="pt", truncation=False)
        if (not isinstance(tokens, dict) and not hasattr(tokens, "keys")
                or "input_ids" not in tokens or "attention_mask" not in tokens
                or tokens["input_ids"].ndim != 2 or tokens["input_ids"].shape[0] != 1
                or tokens["attention_mask"].shape != tokens["input_ids"].shape):
            raise ValueError("one aligned input-ID and attention-mask sequence required")
        count = tokens["input_ids"].shape[1]
        if not 1 <= count <= self.max_tokens:
            raise ValueError("token limit exceeded; no silent evidence truncation")
        with torch.no_grad():
            result = self.model(**tokens).last_hidden_state
        if result.shape != (1, count, 384):
            raise ValueError("unexpected token output geometry")
        snapshot = FeatureSnapshotV2(identity, result[0], tokens["attention_mask"][0],
                                     positions=[(i,) for i in range(count)])
        witness = token_ids_sha256(tokens["input_ids"][0].tolist())
        old = self.token_id_witnesses.get(identity)
        if old is not None and old != witness:
            raise ValueError("same Encoder identity produced changed Token IDs")
        self.token_id_witnesses[identity] = witness
        self.calls += 1
        return snapshot
