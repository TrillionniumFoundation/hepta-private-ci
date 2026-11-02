"""Fixed research-encoder identities and dependency-free acquisition contracts."""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

MODEL = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
REVISION = "6eba34a2485ea31cb03600241787c3a5edab8626"
WEIGHT_SHA = "efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95"
VERSIONS = {"torch": "2.6.0+cpu", "transformers": "4.49.0", "safetensors": "0.5.3", "numpy": "2.3.5"}
FILES = ("README.md", "config.json", "preprocessor_config.json", "model.safetensors")


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def safe_url(url):
    value = urlsplit(str(url))
    return urlunsplit((value.scheme, value.hostname or "", value.path, "", ""))


def safe_error(error):
    return re.sub(r"https?://[^\s'\"<>]+", lambda m: safe_url(m[0]), str(error))[:1000]


def metadata_contract(directory):
    root = Path(directory)
    config = json.loads((root / "config.json").read_text())
    processor = json.loads((root / "preprocessor_config.json").read_text())
    expected = {"model_type": "wav2vec2", "hidden_size": 1024, "num_hidden_layers": 12,
                "num_attention_heads": 16, "intermediate_size": 4096, "conv_bias": True,
                "feat_extract_norm": "layer", "do_stable_layer_norm": True,
                "pooling_mode": "mean", "problem_type": "regression",
                "conv_kernel": [10, 3, 3, 3, 3, 2, 2], "conv_stride": [5, 2, 2, 2, 2, 2, 2],
                "conv_dim": [512] * 7,
                "id2label": {"0": "arousal", "1": "dominance", "2": "valence"}}
    if any(config.get(key) != value for key, value in expected.items()) or config.get("auto_map"):
        raise ValueError("Pinned publisher architecture contract differs; no Auto/remote implementation")
    preprocessing = {"feature_extractor_type": "Wav2Vec2FeatureExtractor", "sampling_rate": 16000,
                     "feature_size": 1, "do_normalize": True, "return_attention_mask": True,
                     "padding_side": "right", "padding_value": 0.0}
    if any(processor.get(key) != value for key, value in preprocessing.items()):
        raise ValueError("Pinned publisher preprocessing contract differs")
    card = (root / "README.md").read_text()
    if not re.search(r"(?m)^license:\s*cc-by-nc-sa-4.0\s*$", card):
        raise ValueError("Pinned model-card research-license declaration missing")
    return {"config_contract": expected, "preprocessor_contract": preprocessing,
            "license": "CC-BY-NC-SA-4.0", "license_declaration_file": "README.md",
            "license_declaration_sha256": sha(root / "README.md"),
            "legal_terms": "https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode",
            "research_only": True, "commercial_or_production_license_claimed": False}
