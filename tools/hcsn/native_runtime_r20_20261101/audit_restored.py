"""Run the unchanged frozen record audit using verified relocated ELF bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from . import audit_records


class ArtifactPath:
    """Preserve a recorded basename while reading its exact relocated artifact."""
    def __init__(self, recorded, restored):
        self.name = recorded.name
        self.restored = restored

    def read_bytes(self):
        return self.restored.read_bytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--binary-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = root / "BINARY_ARTIFACTS.json"
    mapping = {}
    for row in json.loads(manifest.read_text())["binaries"]:
        sha = row["sha256"]
        assert re.fullmatch("[0-9a-f]{64}", sha)
        restored = args.binary_directory / sha
        data = restored.read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == sha
        for name in row["origin_paths"]:
            if name in mapping:
                assert mapping[name] == restored
            mapping[name] = restored

    def relocated(value):
        recorded = Path(value)
        return ArtifactPath(recorded, mapping[str(recorded)]) if str(recorded) in mapping else recorded

    # Only historical artifact locations are adapted. The original checker,
    # source hash, record bytes, reference values and comparisons stay unchanged.
    original_path = audit_records.Path
    try:
        audit_records.Path = relocated
        result = audit_records.audit(args.directory)
    finally:
        audit_records.Path = original_path
    result["artifact_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    result["path_adapter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["path_adapter_scope"] = "Verified byte-identical ELF relocation only; no scientific records or original auditor source modified."
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
