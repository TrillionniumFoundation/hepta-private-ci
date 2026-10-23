"""Local-only tokenizer adapter candidate; not an upstream Laya release."""
import json
from pathlib import Path

PROFILE = "laya-0.4.14-local-readonly-extra-special-token-map-v1"


def tokenizer_kwargs(tokenizer_directory):
    root = Path(tokenizer_directory)
    if not root.is_dir():
        raise ValueError("candidate requires an existing local tokenizer directory")
    config = json.loads((root / "tokenizer_config.json").read_text())
    if config.get("tokenizer_class") != "PreTrainedTokenizerFast":
        raise ValueError("candidate only supports pinned PreTrainedTokenizerFast artifacts")
    result = {"local_files_only": True, "trust_remote_code": False}
    extra = config.get("extra_special_tokens")
    if isinstance(extra, list):
        if any(not isinstance(token, str) or not token for token in extra):
            raise ValueError("extra special tokens must be nonempty strings")
        if len(extra) != len(set(extra)):
            raise ValueError("extra special tokens must be distinct")
        result["extra_special_tokens"] = {f"extra_{i}": value for i, value in enumerate(extra)}
    elif extra is not None:
        if not isinstance(extra, dict) or any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in extra.items()
        ):
            raise ValueError("extra special tokens must be a valid mapping or list")
        result["extra_special_tokens"] = extra
    return result


def load_readonly_tokenizer(tokenizer_directory):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(str(tokenizer_directory), **tokenizer_kwargs(tokenizer_directory))
