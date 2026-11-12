"""Build the pinned native Cell libraries and export actor-only MLP features.

The FP64 dictionary is an explicitly identified transport codec, not Q24 latent
quantization. Source hashes bind the provided provenance; they do not attest it.
"""

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess

from perc1.acquisition import features
from perc1.mlp_head import validate_head
from perc1.schema import canonical, require, sha
from perc1_native_cell_probe import CRATES, _source_pins

REF = "a5583f0f4a12d9618a3a5bc5ed0e7062a7463f39"


def envelope(raw_head, candidates, bindings):
    head = json.loads(raw_head)
    validate_head(head)
    require(1 <= len(candidates) <= 4, "native candidate bound")
    rows = [features(candidate["features"]) for candidate in candidates]
    width = len(rows[0])
    require(all(len(row) == width for row in rows), "native feature width changed")
    budgets = {c["features"]["remaining_budget"] for c in candidates}
    require(len(budgets) == 1, "candidate budget mismatch")
    dictionary, indices = [], []
    for row in rows:
        for value in row:
            bits = struct.unpack("<Q", struct.pack("<d", value))[0]
            if bits not in dictionary:
                dictionary.append(bits)
            indices.append(dictionary.index(bits))
    carrier = [len(rows), width, len(dictionary)]
    carrier += [
        part
        for bits in dictionary
        for part in (bits & 0x3FFFFF, (bits >> 22) & 0x3FFFFF, bits >> 44)
    ]
    carrier += indices
    require(len(carrier) <= 512, "lossless carrier exceeds original 512 scalar cap")
    raw_bits = b"perc1.native-features.f64.v1" + struct.pack("<QQ", len(rows), width)
    raw_bits += b"".join(struct.pack("<d", value) for row in rows for value in row)
    carrier_bits = b"hepta.neuron.input-features.q24.v1" + struct.pack(
        ">Q", len(carrier)
    )
    carrier_bits += b"".join(struct.pack(">q", value) for value in carrier)
    return dict(
        schema="perc1.acquisition-native-features.v1",
        rows=rows,
        candidate_ids=[c["id"] for c in candidates],
        upper_costs=[c["upper_cost"] for c in candidates],
        remaining_budget=next(iter(budgets)),
        head_sha256=sha(raw_head),
        head_canonical_sha256=sha(canonical(head)),
        feature_rows_sha256=sha(raw_bits),
        carrier_digest=sha(carrier_bits),
        source_bindings=dict(bindings),
    )


def build(repo, destination, cargo, rustc, *, ref=REF, offline=True):
    pins = _source_pins(repo, ref)
    builder_bytes = Path(__file__).read_bytes()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "src").mkdir()
    source_dir = Path(__file__).parent
    names = ["perc1_trained_native.rs"] + [
        "perc1_trained_native_" + name + ".rs"
        for name in ("model", "control", "definition")
    ]
    frozen = {name: (source_dir / name).read_bytes() for name in names}
    targets = dict(zip(names, ("main.rs", "model.rs", "control.rs", "definition.rs")))
    for name, target in zip(
        names, ("main.rs", "model.rs", "control.rs", "definition.rs")
    ):
        (destination / "src" / target).write_bytes(frozen[name])
    manifests = {}
    shared = 'serde = { version = "=1.0.229", features = ["derive"] }\nserde_json = { version = "=1.0.154", features = ["float_roundtrip"] }\n'
    manifests["Cargo.toml"] = (
        '[workspace]\nmembers = ["hepta-types", "hepta-infer-core", "hepta-neuron"]\nresolver = "3"\n[package]\nname = "perc1-trained-native"\nversion = "0.0.0"\nedition = "2024"\n[dependencies]\n'
        + shared
        + "".join("codex-" + name + ' = { path = "' + name + '" }\n' for name in CRATES)
        + "[profile.dev]\ndebug = 0\n"
    )
    for name in CRATES:
        (destination / name).mkdir()
        value = (
            '[package]\nname = "codex-'
            + name
            + '"\nversion = "0.0.0"\nedition = "2024"\n[lib]\npath = '
            + json.dumps(str(repo / "codex-rs" / name / "src/lib.rs"))
            + "\n[dependencies]\n"
        )
        value += (
            'sha2 = "=0.10.9"\n'
            if name == "hepta-types"
            else shared + 'codex-hepta-types = { path = "../hepta-types" }\n'
        )
        if name == "hepta-neuron":
            value += 'codex-hepta-infer-core = { path = "../hepta-infer-core" }\n'
        manifests[name + "/Cargo.toml"] = value
    for name, value in manifests.items():
        (destination / name).write_text(value)
    command = [
        str(cargo),
        "build",
        "--offline",
        "--jobs",
        "2",
        "--manifest-path",
        str(destination / "Cargo.toml"),
    ]
    if not offline:
        command.remove("--offline")
    completed = subprocess.run(
        command, env=dict(os.environ, RUSTC=str(rustc)), capture_output=True, text=True
    )
    for stream in ("stdout", "stderr"):
        (destination / ("build." + stream + ".log")).write_text(
            getattr(completed, stream)
        )
    unchanged = pins == _source_pins(repo, ref)
    probe_unchanged = all(
        (source_dir / name).read_bytes() == frozen[name]
        and (destination / "src" / targets[name]).read_bytes() == frozen[name]
        for name in names
    )
    builder_unchanged = Path(__file__).read_bytes() == builder_bytes
    manifests_unchanged = all(
        (destination / name).read_text() == value for name, value in manifests.items()
    )
    binary = (
        Path(os.environ.get("CARGO_TARGET_DIR", destination / "target"))
        / "debug/perc1-trained-native"
    )
    retained_binary = destination / "perc1-trained-native"
    if binary.exists() and completed.returncode == 0:
        with retained_binary.open("xb") as stream:
            stream.write(binary.read_bytes())
        retained_binary.chmod(0o755)
    record = dict(
        schema="perc1.trained-native-build.v1",
        source_ref=ref,
        sources=pins,
        sources_unchanged=unchanged,
        probe_sources_unchanged=probe_unchanged,
        builder_unchanged=builder_unchanged,
        manifests_unchanged=manifests_unchanged,
        command=command,
        returncode=completed.returncode,
        probe_sources={name: sha(raw) for name, raw in frozen.items()},
        copied_probe_sources={
            targets[name]: sha((destination / "src" / targets[name]).read_bytes())
            for name in names
        },
        builder_sha256=sha(builder_bytes),
        manifests={name: sha(text.encode()) for name, text in manifests.items()},
        rustc=subprocess.check_output([str(rustc), "--version"], text=True).strip(),
        binary_sha256=sha(retained_binary.read_bytes())
        if retained_binary.exists()
        else None,
        cargo_lock_sha256=sha((destination / "Cargo.lock").read_bytes())
        if (destination / "Cargo.lock").exists()
        else None,
    )
    (destination / "build.json").write_bytes(canonical(record) + b"\n")
    require(
        completed.returncode == 0
        and unchanged
        and probe_unchanged
        and builder_unchanged
        and manifests_unchanged,
        "native build/source freeze failed; original logs retained",
    )
    return retained_binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--cargo", type=Path, required=True)
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--source-ref", default=REF)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    print(
        build(
            args.repo,
            args.build_dir,
            args.cargo,
            args.rustc,
            ref=args.source_ref,
            offline=not args.online,
        )
    )


if __name__ == "__main__":
    main()
