"""Independent stdlib-only reconstruction of V4 source allocation and guards."""

import argparse
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
from unittest.mock import patch


SALT = "hepta-field-v4-20261027-panel-origin-qualification-1"
COUNTS = dict(zip(("gradient", "rehearsal", "probe", "guard", "task", "clean"),
                  (2000, 512, 256, 512, 1024, 2048)))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def review(repo, assets, v2_path):
    root = repo / "experiments/multimodal_output_portfolio"
    fresh = root / "field_bridge_v4_20261027"
    v2raw = v2_path.read_bytes()
    assert sha(v2raw) == "c574b21f216deabe1dc3f90ab9d57276c9e54aea75dcc781d317435ebcdeb1ef"
    v2 = json.loads(v2raw)
    v3packed = (root / "field_bridge_v3_20261027/SOURCE_IDENTITIES.json.gz").read_bytes()
    v3raw = gzip.decompress(v3packed)
    assert sha(v3raw) == "8cb6a2dbdcf468d15ea75602c05916c5b71a535f2b8a60a91104946253f7a636"
    v3 = json.loads(v3raw)
    packed = (fresh / "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    registry = json.loads(raw)
    manifest = json.loads((fresh / "SOURCE_ALLOCATION.json").read_text())
    canonical = json.dumps({k: v for k, v in manifest.items() if k != "manifest_sha256"},
                           sort_keys=True, separators=(",", ":")).encode()
    assert sha(canonical) == manifest["manifest_sha256"]
    assert sha(packed) == manifest["registry_gzip_sha256"] and sha(raw) == manifest["registry_sha256"]
    v2hash = {h for role in v2["source_splits"].values() for h in role["pixel_sha256"]}
    v3hash = {identity.rsplit(":", 1)[1] for role in v3["roles"].values() for identity in role["identities"]}
    assert len(v2hash) == 29000 and len(v3hash) == 28048 and not v2hash & v3hash
    excluded = v2hash | v3hash
    decoded, files = {}, {}
    for record in manifest["dataset_files"]:
        data = (assets / record["name"]).read_bytes()
        assert len(data) == record["bytes"] and sha(data) == record["sha256"]
        decoded[record["name"]] = gzip.decompress(data)
        files[record["name"]] = {"bytes": len(data), "sha256": sha(data)}
    hashes, labels = {}, {}
    for origin, prefix, count in (("train", "train", 60000), ("test", "t10k", 10000)):
        images, classes = decoded[prefix + "-images-idx3-ubyte.gz"], decoded[prefix + "-labels-idx1-ubyte.gz"]
        assert struct.unpack(">IIII", images[:16]) == (2051, count, 28, 28)
        assert struct.unpack(">II", classes[:8]) == (2049, count)
        assert len(images) == 16 + count * 784 and len(classes) == 8 + count
        hashes[origin] = [sha(images[16 + i * 784:16 + (i + 1) * 784]) for i in range(count)]
        labels[origin] = classes[8:]
    seen_labels, conflicts = {}, set()
    for origin in ("train", "test"):
        for digest, label in zip(hashes[origin], labels[origin], strict=True):
            if seen_labels.setdefault(digest, label) != label:
                conflicts.add(digest)
    eligible = {}
    for origin in ("train", "test"):
        first_index = {}
        for index, digest in enumerate(hashes[origin]):
            first_index.setdefault(digest, index)
        allowed = set(first_index) - excluded - conflicts
        if origin == "train":
            allowed -= set(hashes["test"])
        order = sorted(allowed, key=lambda h: (sha((SALT + ":" + origin + ":" + h).encode()), h))
        eligible[origin] = [f"mnist:{origin}:{first_index[h]}:{h}" for h in order]
    assert {k: len(v) for k, v in eligible.items()} == {"train": 9000, "test": 3952}
    cursor, roles, assigned = 0, {}, []
    for role, count in COUNTS.items():
        name = "qualification_" + role
        expected = eligible["train"][cursor:cursor + count]
        actual = registry["roles"][name]["identities"]
        assert actual == expected and len(set(actual)) == count
        digest = sha("\n".join(actual).encode())
        assert digest == manifest["roles"][name]["identity_sha256"]
        roles[name] = {"images": count, "pairs": count // 2, "identity_sha256": digest}
        assigned.extend(identity.rsplit(":", 1)[1] for identity in actual)
        cursor += count
    assert cursor == 6352 and len(set(assigned)) == 6352 and not set(assigned) & excluded
    assert manifest["unassigned_by_origin"] == {"train": 2648, "test": 3952}
    sys.path.insert(0, str(repo))
    module = importlib.import_module("experiments.multimodal_output_portfolio.field_bridge_v4_20261027.source_roles")
    cases = ((["qualification_task"], "adaptation"), (["qualification_clean"], "adaptation"),
             (["qualification_probe"], "endpoints"), (["primary"], "endpoints"),
             (["audit_task"], "endpoints"), (["qualification_task"], "unknown"),
             ([], "endpoints"), (["qualification_task", "qualification_task"], "endpoints"))
    with patch.object(module, "verify_registry", side_effect=AssertionError("Registry I/O reached")), \
            patch.object(module, "read_assets", side_effect=AssertionError("Asset I/O reached")):
        for names, phase in cases:
            try:
                module.load_corpus_roles("/no-assets-required", names, phase=phase)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid phase/role request did not reject before I/O")
    return {
        "schema": "hepta.field-bridge.v4.independent-source-review.1", "passed": True,
        "scope": "Source identities/metadata and invalid-phase guards only; no tensors or model outcomes opened",
        "source_manifest_sha256": manifest["manifest_sha256"], "source_registry_gzip_sha256": sha(packed),
        "source_registry_sha256": sha(raw), "script_sha256": sha(Path(__file__).read_bytes()),
        "source_roles_py_sha256": sha((fresh / "source_roles.py").read_bytes()),
        "v2_prior_images": len(v2hash), "v3_prior_images": len(v3hash),
        "independent_exact_allocation_reconstruction": True, "roles": roles,
        "v4_images": cursor, "cross_role_pixel_overlap": 0, "prior_pixel_overlap": 0,
        "remaining_by_origin": {"train": 2648, "test": 3952},
        "conflicting_pixel_identities_excluded": len(conflicts), "dataset_files": files,
        "invalid_phase_guard_cases_passed": len(cases), "torch_imported": "torch" in sys.modules,
        "model_calls": 0, "observer_calls": 0, "native_calls": 0, "network_calls": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for argument in ("repo", "assets", "v2-registry", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    result = review(args.repo, args.assets, args.v2_registry)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "v4_images": result["v4_images"],
                      "invalid_phase_guard_cases_passed": result["invalid_phase_guard_cases_passed"],
                      "torch_imported": result["torch_imported"]}))
