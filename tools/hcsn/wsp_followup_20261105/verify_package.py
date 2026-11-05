"""Verify this follow-up's published payload and short-cache receipt identities.

This is an archive/record verifier, not a new model execution. The scientific
driver and its independent numerical verifier live in the ndu_policy directory.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def cache_records(root):
    cache = root / "qwen_cache"
    receipt = read(cache / "receipt.json")
    for field, name in (("protocol_sha256", "protocol.json"),
                        ("source_sha256", "qualify_cache.py"),
                        ("runtime_pins_sha256", "runtime_pins.json")):
        assert receipt[field] == sha((cache / name).read_bytes()), name
    assert receipt["protocol"] == read(cache / "protocol.json")
    assert receipt["status"] == "PASS_F32_SHORT_CACHE_QUALIFICATION"
    assert not receipt["capability_score_computed"]
    assert not receipt["original_bf16_or_vllm_benchmark_qualified"]
    forwards = comparisons = appended = 0
    for name in ("base", "p50c"):
        variant = read(cache / (name + ".json"))
        assert variant == receipt["variants"][name]
        assert variant["forwards"] == {
            "cached_prefill": 1, "incremental_cached": 8,
            "full_prefix_reference": 9}
        rows = variant["comparisons"]
        assert [row["prefix_tokens"] for row in rows] == list(range(7, 16))
        assert len(variant["appended_tokens"]) == 8
        for row in rows:
            assert row["finite"] and row["allclose"] and row["greedy_equal"]
            assert row["cache_sequence_length"] == row["prefix_tokens"]
            assert row["cached_argmax"] == row["reference_argmax"]
            assert 0 <= row["maximum_ratio_to_fixed_tolerance"] <= 1
        assert variant["checks"]["source_parameter_values_exactly_lifted"]
        assert variant["checks"]["learned_f32_parameters_unchanged"]
        forwards += sum(variant["forwards"].values())
        comparisons += len(rows)
        appended += len(variant["appended_tokens"])
    assert (forwards, comparisons, appended) == (36, 18, 16)
    assert receipt["original_exports_unchanged"]
    assert receipt["named_runtime_sources_and_dependency_metadata_unchanged"]
    assert all(item["exit_code"] == 0 and item["termination_reason"] is None
               for item in receipt["processes"])
    root_receipt = read(root / "ROOT_CACHE_RECORD_VERIFICATION.json")
    assert root_receipt["receipt_sha256"] == sha((cache / "receipt.json").read_bytes())
    return {"forwards_recorded": forwards, "comparisons_recorded": comparisons,
            "appended_tokens_recorded": appended,
            "no_model_forward_reexecution": True}


def verify(root):
    root = root.resolve(strict=True)
    manifest_path = root / "PAYLOAD_MANIFEST.json"
    manifest = read(manifest_path)
    assert manifest["schema"] == "hepta.wsp-followup.payload-manifest.v1"
    expected = set()
    total = 0
    for item in manifest["files"]:
        relative = Path(item["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        assert relative.as_posix() not in expected
        assert relative.as_posix() != "PAYLOAD_MANIFEST.json"
        expected.add(relative.as_posix())
        path = root / relative
        assert not path.is_symlink() and path.resolve(strict=True).is_relative_to(root)
        payload = path.read_bytes()
        assert len(payload) == item["bytes"], relative
        assert sha(payload) == item["sha256"], relative
        total += len(payload)
    found = {path.relative_to(root).as_posix() for path in root.rglob("*")
             if path.is_file() and "__pycache__" not in path.parts
             and path.name != "PAYLOAD_MANIFEST.json"}
    assert found == expected, {"unlisted": sorted(found - expected),
                               "missing": sorted(expected - found)}
    return {"schema": "hepta.wsp-followup.package-verification.v1",
            "passed": True, "payload_files": len(expected),
            "payload_bytes": total,
            "manifest_sha256": sha(manifest_path.read_bytes()),
            "qwen_cache_records": cache_records(root),
            "scope": "Payload and retained-record identity; no scientific trajectory or model rerun."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).parent)
    print(json.dumps(verify(parser.parse_args().package), sort_keys=True))
