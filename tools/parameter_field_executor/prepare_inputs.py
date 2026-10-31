"""Retrieve the nine original public inputs by immutable identity, without decoding."""

import hashlib
import json
import os
from pathlib import Path
import resource
import time
import urllib.request


SOURCE = Path(__file__).resolve().parents[2]
CONTRACT = SOURCE / "operational/parameter_field_recovery07/INPUT_CONTRACT.json"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"


def download(url, destination, size, expected):
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=90) as response:
        with destination.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError("Public input exceeds registered byte length")
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
    if count != size or digest.hexdigest() != expected:
        raise ValueError("Public input differs from its original fixed identity")
    return {"path": str(destination), "bytes": count, "sha256": digest.hexdigest()}


def main():
    started, cpu = time.monotonic(), time.process_time()
    contract = json.loads(CONTRACT.read_text())
    root = Path(contract["assets_root"])
    if root.exists() or SOURCE != Path(contract["source_root"]):
        raise ValueError("Input preparation requires fresh canonical destinations")
    root.mkdir(parents=True, exist_ok=False)
    output = Path("/work/preparation")
    output.mkdir(exist_ok=True)
    base = (
        "https://raw.githubusercontent.com/"
        + REPOSITORY
        + "/"
        + contract["public_assets_commit"]
        + "/"
    )
    declared = contract["public_assets_manifest"]
    manifest_path = output / "ORIGINAL_INPUT_MANIFEST.json"
    manifest = download(
        base + declared["path"], manifest_path, declared["bytes"], declared["sha256"]
    )
    rows = json.loads(manifest_path.read_text())["files"]
    expected = contract["assets"]
    if [
        {key: row[key] for key in ("path", "bytes", "sha256")} for row in rows
    ] != expected:
        raise ValueError("Public input manifest differs from the nine original inputs")
    actual = []
    for row in rows:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Noncanonical original input path")
        if "repository_path" in row:
            url = base + row["repository_path"]
        else:
            url = "https://storage.googleapis.com/cvdf-datasets/mnist/" + relative.name
            if row["public_download_url"] != url:
                raise ValueError("Unexpected original MNIST input source")
        actual.append(download(url, root / relative, row["bytes"], row["sha256"]))
    result = {
        "schema": "hepta.execution07.public-input-preparation.1",
        "source_commit": os.environ["GITHUB_SHA"],
        "public_assets_commit": contract["public_assets_commit"],
        "manifest": manifest,
        "files": actual,
        "scientific_values_decoded": False,
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "cost_scope": "This input preparation process only, excluding interpreter startup, runtime installation and final receipt serialization.",
    }
    with (output / "INPUTS_PREPARED.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps(
            {
                "original_inputs_byte_verified": len(actual),
                "scientific_values_decoded": False,
            }
        )
    )


if __name__ == "__main__":
    main()
