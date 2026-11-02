"""Byte-exact bounded transport for the retained physical waveform NPZ."""

import argparse
import hashlib
import json
from pathlib import Path
from .contracts import sha, write


def pack(inputs):
    source = inputs / "WAVEFORMS.npz"
    identity = json.loads((inputs / "PCM_IDENTITY.json").read_text())
    if sha(source) != identity["waveforms_npz_sha256"] or source.stat().st_size > 20_000_000:
        raise ValueError("Prepared waveform transport identity/size differs")
    parts = []
    with source.open("rb") as stream:
        while block := stream.read(4_500_000):
            name = f"WAVEFORMS.part{len(parts):03d}"
            with (inputs / name).open("xb") as output:
                output.write(block)
            parts.append({"name": name, "bytes": len(block), "sha256": hashlib.sha256(block).hexdigest()})
    write(inputs / "TRANSPORT.json", {"schema": "hcsn-v13-waveform-transport.v1", "parts": parts,
        "whole_bytes": source.stat().st_size, "whole_sha256": sha(source),
        "original_not_duplicated_in_git": True, "restored_before_inference": True})


def restore(inputs, destination):
    manifest = json.loads((inputs / "TRANSPORT.json").read_text())
    identity = json.loads((inputs / "PCM_IDENTITY.json").read_text())
    if manifest["whole_sha256"] != identity["waveforms_npz_sha256"] or manifest["whole_bytes"] > 20_000_000:
        raise ValueError("Whole transport does not bind prepared physical PCM")
    h, size, seen = hashlib.sha256(), 0, set()
    with destination.open("xb") as output:
        for record in manifest["parts"]:
            name = record["name"]
            if Path(name).name != name or name in seen:
                raise ValueError("Unsafe or duplicate transport part")
            seen.add(name)
            block = (inputs / name).read_bytes()
            if len(block) != record["bytes"] or hashlib.sha256(block).hexdigest() != record["sha256"]:
                raise ValueError("Actual transport part differs")
            output.write(block); h.update(block); size += len(block)
    if size != manifest["whole_bytes"] or h.hexdigest() != manifest["whole_sha256"]:
        raise ValueError("Restored physical waveform NPZ differs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pack", "restore"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    pack(args.inputs) if args.mode == "pack" else restore(args.inputs, args.destination)
