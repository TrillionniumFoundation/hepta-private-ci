"""Restore the exact retained Linux native research binary without rebuilding."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import platform

HERE = Path(__file__).resolve().parent


def restore():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("Retained binary is Linux x86_64; rebuild and freeze a new run on another platform")
    manifest = json.loads((HERE / "NATIVE_BUILD.json").read_text())
    binary = HERE / manifest["binary"]
    if binary.resolve().parent != (HERE / "native").resolve():
        raise ValueError("Native output must stay in the package-owned native directory")
    raw = gzip.decompress((HERE / "evidence/native/hepta-first-passage-ndu.gz").read_bytes())
    if hashlib.sha256(raw).hexdigest() != manifest["binary_sha256"]:
        raise ValueError("Retained executable does not match the frozen build identity")
    if binary.exists():
        if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["binary_sha256"]:
            raise ValueError("Refusing to replace an existing different executable")
    else:
        binary.parent.mkdir(exist_ok=True)
        temporary = binary.with_suffix(".incomplete")
        with temporary.open("xb") as stream:
            stream.write(raw)
        temporary.chmod(0o755)
        os.replace(temporary, binary)
    print(json.dumps({"binary": str(binary), "sha256": manifest["binary_sha256"],
                      "source_manifest_sha256": manifest["source_manifest_sha256"]}))


if __name__ == "__main__":
    restore()
