"""E0 shadow-only 768-to-Q24 projection contract audit, NOT model execution proof."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

MAX_INPUT = 8192
MAX_OUTPUT = 512
Q24 = 1 << 24
LIMIT = 8 * Q24
HEX = frozenset("0123456789abcdef")


class GateError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def sha_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "missing or symbolic artifact")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def exact_object(value: object, names: set[str]) -> dict:
    require(type(value) is dict and set(value) == names, "unknown or missing contract fields")
    return value


def verify_contract(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    exact_object(obj, {"schema", "encoder_width", "projection_width", "head_input_width",
                       "projection_artifact", "projection_sha256", "projected_features_q24",
                       "feature_source_sha256", "source_kind"})
    require(obj["schema"] == "hepta.neuron.e0-projection-preflight.v1", "schema mismatch")
    require(obj["source_kind"] == "externally_observed_not_authenticated", "not a permitted source type")
    iw, ow, hw = (obj[x] for x in ("encoder_width", "projection_width", "head_input_width"))
    require(type(iw) is int and 1 <= iw <= MAX_INPUT, "bad encoder width")
    require(type(ow) is int and 1 <= ow <= MAX_OUTPUT, "projection output exceeds V1 input ceiling")
    require(type(hw) is int and hw == ow, "Head width mismatch")
    if iw > MAX_OUTPUT:
        require(iw != ow, "wide Encoder requires explicit projection")
    artifact = obj["projection_artifact"]
    require(type(artifact) is str and Path(artifact).is_absolute(), "projection artifact needs absolute path")
    for field in ("projection_sha256", "feature_source_sha256"):
        d = obj[field]
        require(type(d) is str and len(d) == 64 and set(d) <= HEX and d != "0" * 64, field + " invalid")
    require(sha_file(Path(artifact)) == obj["projection_sha256"], "physical projection bytes drift")
    features = obj["projected_features_q24"]
    require(type(features) is list and len(features) == ow, "projected Q24 vector width mismatch")
    require(all(type(x) is int and -LIMIT <= x <= LIMIT for x in features), "invalid Q24 value or clipping evidence")
    return {"schema": "hepta.neuron.e0-projection-preflight-result.v1",
            "contract_sha256": digest(obj), "encoder_width": iw, "neuron_input_width": ow,
            "feature_digest": digest(features), "projection_file_sha256": obj["projection_sha256"],
            "verified_claim": "local_dimensions_bytes_and_q24_only",
            "real_encoder_invocation_authenticated": False,
            "projection_applied_to_encoder_proven": False, "neuron_tick_committed": False,
            "model_performance_accepted": False, "authority": "none"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(verify_contract(args.contract), sort_keys=True))


if __name__ == "__main__":
    main()
