"""Verify five immutable Hugging Face revision/LFS pointers (not model execution)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import URLError

from replacement_gate import EXPECTED, validate_registry

MAX_JSON = 8 * 1024 * 1024


def check_metadata(name: str, spec: dict, record: dict) -> dict:
    """Require the EXACT requested revision and published LFS weight digest."""
    if not isinstance(record, dict) or record.get("sha") != spec["revision"]:
        raise ValueError(f"{name}: upstream revision not exact")
    raw = record.get("siblings")
    if not isinstance(raw, list) or len(raw) > 2000:
        raise ValueError(f"{name}: no bounded upstream file manifest")
    rows = {}
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("rfilename"), str):
            raise ValueError(f"{name}: malformed upstream entry")
        key = entry["rfilename"]
        if key in rows:
            raise ValueError(f"{name}: repeated upstream filename")
        rows[key] = entry
    weight = rows.get(spec["weight_file"])
    if not isinstance(weight, dict):
        raise ValueError(f"{name}: weights absent")
    lfs = weight.get("lfs")
    if (not isinstance(lfs, dict) or
            lfs.get("sha256") != spec["weight_sha256"] or
            type(weight.get("size")) is not int or
            not 100_000_000 <= weight["size"] <= 4_000_000_000):
        raise ValueError(f"{name}: immutable weights digest/size disagree")
    if "config.json" not in rows:
        raise ValueError(f"{name}: config.json missing")
    if not ("tokenizer.json" in rows or "tokenizer/tokenizer.json" in rows):
        raise ValueError(f"{name}: tokenizer missing")
    return {"model": name, "repository": spec["repository"],
            "revision": spec["revision"], "weights_sha256": spec["weight_sha256"],
            "weight_size_bytes": weight["size"],
            "upstream_file_count": len(rows),
            "live_hub_metadata_checked": True,
            "model_bytes_downloaded_and_verified": False,
            "real_inference_executed": False,
            "license_terms_independently_reviewed": False,
            "production_activation_allowed": False}


def audit(registry: dict, fetcher=None) -> dict:
    errors = validate_registry(registry)
    if errors:
        raise ValueError("invalid local model register: " + "; ".join(errors))
    if fetcher is None:
        fetcher = _get_json
    entries = []
    for model in EXPECTED:
        spec = registry["models"][model]
        repo, revision = spec["repository"], spec["revision"]
        url = f"https://huggingface.co/api/models/{repo}/revision/{quote(revision)}?blobs=true"
        record = fetcher(url)
        entries.append(check_metadata(model, spec, record))
    return {"schema": "hepta.neuron.hub-pins-preflight.v1", "models": entries,
            "real_checkpoint_execution_proved": False,
            "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
            "production_activation_allowed": False}


def _get_json(url):
    request = Request(url, headers={"User-Agent": "Hepta-neuron-pin-audit/1.0"})
    try:
        with urlopen(request, timeout=90) as response:
            data = response.read(MAX_JSON + 1)
    except URLError as error:
        raise ValueError(f"upstream metadata unreachable: {error}") from error
    if len(data) > MAX_JSON:
        raise ValueError("upstream metadata exceeds bounded response")
    return json.loads(data)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", default=str(Path(__file__).with_name("replacement_models.json")))
    p.add_argument("--out")
    args = p.parse_args()
    try:
        result = audit(json.loads(Path(args.registry).read_text()))
        serialized = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if args.out:
            target = Path(args.out)
            with target.open("x") as stream:
                stream.write(serialized)
        print(serialized)
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error),
                          "production_activation_allowed": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
