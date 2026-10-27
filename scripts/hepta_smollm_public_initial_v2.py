#!/usr/bin/env python3
"""Reconstruct public V2 genesis from the seven pinned upstream files.

Run with Python 3.12 using --chain, --materials and a fresh --output directory.
This bounded preparation runs no Torch, inference, training, selection or install.
The historical V1 contract remains unchanged and is never substituted by V2.
"""

import argparse
import array
import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request

PROFILES = (
    Path(__file__).resolve().parents[1] / "codex-rs/hepta-learning-artifacts/profiles"
)
PREFIX = "smollm2-public-initial-v2"
CONTRACT = "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def fetch_materials(runtime, materials):
    materials.mkdir(mode=0o700, parents=False, exist_ok=False)
    files = {}
    for name, (size, expected) in sorted(runtime.PUBLIC_FILES.items()):
        digest = hashlib.sha256()
        total = 0
        url = (
            f"https://huggingface.co/{runtime.MODEL}/resolve/{runtime.REVISION}/{name}"
        )
        with (
            urllib.request.urlopen(url, timeout=30) as response,
            (materials / name).open("xb") as target,
        ):
            while block := response.read(min(1024 * 1024, size - total + 1)):
                total += len(block)
                require(total <= size, f"upstream size exceeds pin: {name}")
                digest.update(block)
                target.write(block)
        require(
            total == size and digest.hexdigest() == expected,
            f"upstream bytes differ: {name}",
        )
        files[name] = dict(revision=runtime.REVISION, sha256=expected, size=size)
    runtime.save(
        materials / "material-manifest.json",
        dict(files=files, model=runtime.MODEL, revision=runtime.REVISION),
    )


def derive(chain, materials, output, download):
    require(sys.byteorder == "little", "the V2 source profile is little-endian")
    source_manifest = json.loads((PROFILES / f"{PREFIX}.sources.json").read_bytes())
    require(
        source_manifest["schema"] == "hepta-smollm-public-initial-sources-v2",
        "source schema",
    )
    for relative, expected in source_manifest["files"].items():
        path = chain / relative
        require(path.resolve() == path and path.is_file(), "source path")
        raw = path.read_bytes()
        require(
            len(raw) == expected["size"]
            and hashlib.sha256(raw).hexdigest() == expected["sha256"],
            f"source differs from the public V2 profile: {relative}",
        )
    # All project imports below follow verification of their complete static
    # source/config dependency set. The Python runtime is separately qualified.
    sys.path.insert(0, str(chain / "scripts"))
    import llm_initial_trainable_setup_v2 as setup
    import llm_parent_material as parent
    import llm_runtime_pilot as runtime

    if download:
        fetch_materials(runtime, materials)
    manifest, config = runtime.verify_materials(materials)
    shapes = runtime.contract_module().architecture_shapes(runtime.architecture(config))
    index = {}
    with (materials / "model.safetensors").open("rb") as source:
        (header_len,) = struct.unpack("<Q", source.read(8))
        require(0 < header_len < 2 * 1024 * 1024, "model header bound")
        header = json.loads(source.read(header_len), object_pairs_hook=runtime.unique)
        header.pop("__metadata__", None)
        require(set(header) == set(shapes), "complete tensor inventory")
        for name, shape in shapes.items():
            value = header[name]
            require(
                value["dtype"] == "BF16" and value["shape"] == shape,
                "source tensor profile",
            )
            first, end = value["data_offsets"]
            count = 1
            for size in shape:
                count *= size
            require(end - first == count * 2, "source tensor byte count")
            source.seek(8 + header_len + first)
            remaining = end - first
            digest = hashlib.sha256()
            while remaining:
                raw = source.read(min(remaining, 65_536))
                require(bool(raw) and len(raw) % 2 == 0, "source tensor truncated")
                remaining -= len(raw)
                words = array.array("H", raw)
                digest.update(
                    array.array("I", (word << 16 for word in words)).tobytes()
                )
            index[name] = dict(
                dtype="float32",
                shape=shape,
                byte_length=count * 4,
                sha256=digest.hexdigest(),
            )
    plan = runtime.experiment_plan(manifest)
    require(
        runtime.canonical(plan) + b"\n"
        == (PROFILES / f"{PREFIX}.plan.json").read_bytes(),
        "public plan bytes differ",
    )
    tokenizer = runtime.read_json(materials / "tokenizer_config.json")
    contract, raw, cid = runtime.contract_from_inventory(
        index, tokenizer["chat_template"], config, manifest, plan
    )
    require(
        cid == CONTRACT and raw == (PROFILES / f"{PREFIX}.target.json").read_bytes(),
        "public V2 contract differs",
    )
    # V2 changes the independently selected contract/compatibility namespace,
    # while deliberately reusing the exact existing all-positive-zero factors.
    artifact = setup.canonical_zero_parent()
    factors = parent.factor_bytes(artifact, contract)
    adapter, aid = runtime.contract_module().freeze_wrapped_adapter(
        setup._wrapped(contract, cid, factors), contract, cid
    )
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, value in [
        ("target-contract.json", raw),
        ("wrapped-adapter.json", adapter),
        ("artifact.safetensors", artifact),
    ]:
        (output / name).write_bytes(value)
    runtime.save(output / "experiment-plan.json", plan)
    runtime.save(
        output / "parent-material.json",
        dict(
            schema="hepta-smollm-parent-material-v1",
            generation=1,
            operation_id="public-v2-material-derivation-no-execution",
            directory=str(output),
            contract=cid,
            adapter=aid,
            file_sha256=hashlib.sha256(artifact).hexdigest(),
        ),
    )
    runtime.save(
        output / "derivation.json",
        dict(
            schema="hepta-smollm-public-material-derivation-v2",
            contract=cid,
            compatibility=hashlib.sha256(
                (PROFILES / f"{PREFIX}.profile").read_bytes()
            ).hexdigest(),
            backbone=contract["backbone"]["index_root"],
            tokenizer=contract["tokenizer"]["files_root"],
            upstream_verified=True,
            actual_inference=False,
            training=False,
            installation=False,
            product_qualification=False,
            plan=runtime.identity(plan),
        ),
    )
    print((output / "derivation.json").read_text(), end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["chain", "materials", "output"]:
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--fetch-materials",
        action="store_true",
        help="download and verify the seven fixed files into a new materials directory",
    )
    args = parser.parse_args()
    require(
        all(p.is_absolute() for p in [args.chain, args.materials, args.output]),
        "absolute paths required",
    )
    derive(args.chain, args.materials, args.output, args.fetch_materials)


if __name__ == "__main__":
    main()
