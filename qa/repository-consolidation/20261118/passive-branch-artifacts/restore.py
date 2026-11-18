"""Verify and restore immutable original evidence into a separate directory."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve(strict=True)
    manifest_path = Path(__file__).with_name("MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "hepta.passive-branch-artifact-preservation.v1":
        parser.error("unsupported preservation manifest")
    verified: list[tuple[Path, bytes]] = []
    seen: set[str] = set()
    for artifact in manifest["artifacts"]:
        original = Path(artifact["original_path"])
        carrier = Path(artifact["gzip_path"])
        if (
            original.is_absolute()
            or carrier.is_absolute()
            or ".." in original.parts
            or ".." in carrier.parts
            or not original.parts
            or str(original) in seen
        ):
            parser.error("invalid or duplicate original relative path")
        seen.add(str(original))
        source = (repository / carrier).resolve(strict=True)
        if not source.is_relative_to(repository):
            parser.error("carrier resolves outside the repository")
        compressed = source.read_bytes()
        if (
            len(compressed) != artifact["gzip_bytes"]
            or hashlib.sha256(compressed).hexdigest() != artifact["gzip_sha256"]
        ):
            parser.error(f"compressed identity mismatch: {carrier}")
        raw = gzip.decompress(compressed)
        git_blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        if (
            len(raw) != artifact["original_bytes"]
            or hashlib.sha256(raw).hexdigest() != artifact["original_sha256"]
            or hashlib.sha1(git_blob).hexdigest() != artifact["original_git_blob"]
        ):
            parser.error(f"original identity mismatch: {original}")
        verified.append((original, raw))
    if args.destination is not None:
        destination = args.destination.resolve()
        if destination.is_relative_to(repository) or repository.is_relative_to(
            destination
        ):
            parser.error("destination must be separate from the repository")
        if destination.exists():
            parser.error("destination must not already exist")
        destination.mkdir(parents=True, exist_ok=False)
        for original, raw in verified:
            target = destination / original
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
    print(
        json.dumps(
            {
                "verified_original_artifacts": len(verified),
                "restored": args.destination is not None,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
