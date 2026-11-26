"""Prepare a content-pinned profile using reads only; never import the physics."""
import argparse

from profile_io import canonical, digest, read_relative, require, sha, write_new
from small_hcsn_profile import FAMILY, FORMATS, MAX_CHECKPOINT_BYTES, SCHEMA
from source_binding import CAPSULE_SHA256, FrozenSources, PROVENANCE_SHA256, RUNTIME, SCIENTIFIC_SHA256


def pin(root, path, expected, cap, expected_bytes=None):
    raw = read_relative(root, path, cap)
    require(sha(raw) == digest(expected), "supplied artifact digest differs")
    if expected_bytes is not None:
        require(len(raw) == expected_bytes, "supplied artifact byte count differs")
    return {"path": path, "bytes": len(raw), "sha256": sha(raw)}


def prepare(root, capsule_root, scientific_paths, checkpoint_path, checkpoint_sha256,
            checkpoint_bytes, format_name, protocol_sha256=None, coordinate_candidate_sha256=None):
    require(format_name in FORMATS, "unsupported checkpoint format")
    if format_name == "actual_hcsn_v2_selected":
        digest(protocol_sha256)
        require(coordinate_candidate_sha256 is None, "formal origin cannot be a coordinate candidate")
    elif format_name == "actual_p2p_v2_full":
        digest(coordinate_candidate_sha256)
        require(protocol_sha256 is None, "P2P origin is a coordinate candidate")
    else:
        require(protocol_sha256 is None and coordinate_candidate_sha256 is None,
                "research edit parent identities are embedded in the complete candidate")
    manifest = {
        "schema": SCHEMA, "family": FAMILY, "scope": "research_numeric_inference", "format": format_name,
        "checkpoint": pin(root, checkpoint_path, checkpoint_sha256, MAX_CHECKPOINT_BYTES, checkpoint_bytes),
        "capsule": {"root": capsule_root, "archive_sha256": CAPSULE_SHA256,
                    "provenance": pin(root, capsule_root + "/source_provenance.json",
                                      PROVENANCE_SHA256, 1024 * 1024)},
        "scientific_sources": {name: pin(root, scientific_paths[name], expected, 1024 * 1024)
                               for name, expected in SCIENTIFIC_SHA256.items()},
        "runtime": dict(RUNTIME),
        "origin": {"protocol_sha256": protocol_sha256,
                   "coordinate_candidate_sha256": coordinate_candidate_sha256},
    }
    FrozenSources(root, manifest)  # Capture and hash every frozen source; no .load() call.
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("material-root", "capsule-root", "common", "optimized", "checkpoint",
                 "checkpoint-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--checkpoint-bytes", type=int, required=True)
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--coordinate-candidate-sha256")
    args = parser.parse_args()
    manifest = prepare(args.material_root, args.capsule_root,
                       {"common.py": args.common, "optimized.py": args.optimized},
                       args.checkpoint, args.checkpoint_sha256, args.checkpoint_bytes, args.format,
                       args.protocol_sha256, args.coordinate_candidate_sha256)
    print(canonical(write_new(args.output, canonical(manifest) + b"\n", 1024 * 1024)).decode())


if __name__ == "__main__":
    main()
