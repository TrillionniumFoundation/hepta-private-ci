#!/usr/bin/env python3
"""Prepare fixed public material with the original Chain worker; grant no authority."""

import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request

if __package__:
    from .hepta_ci_smollm_common import (
        DENIED,
        ROOT,
        VERSIONS,
        command,
        load_runtime,
        parent,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )
    from .hepta_ci_smollm_resources import require_provisioning, resource_snapshot
else:
    from hepta_ci_smollm_common import (
        DENIED,
        ROOT,
        VERSIONS,
        command,
        load_runtime,
        parent,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )
    from hepta_ci_smollm_resources import require_provisioning, resource_snapshot


def prepare(args):
    require(
        sys.platform == "linux" and platform.machine() == "x86_64",
        "this model lane is Linux x86_64 only",
    )
    require(
        sys.version_info[:2] == (3, 12), "existing Python 3.12 CPU profile required"
    )
    require(
        all(
            importlib.metadata.version(key) == value for key, value in VERSIONS.items()
        ),
        "pinned CPU environment required",
    )
    chain, output, materials = (
        args.chain.resolve(strict=True),
        args.output,
        args.materials,
    )
    require(
        output.is_absolute() and materials.is_absolute(),
        "absolute fresh output/material paths required",
    )
    for path in (output, materials):
        require(
            not path.exists() and not path.is_symlink(),
            "do not overwrite or reuse an earlier attempt",
        )
        require(
            not path.resolve().is_relative_to(ROOT)
            and not path.resolve().is_relative_to(chain),
            "outputs must be outside both checkouts",
        )
    require(
        not output.is_relative_to(materials) and not materials.is_relative_to(output),
        "separate evidence and material directories required",
    )
    output.mkdir(mode=0o700)
    resources = resource_snapshot(output)
    save(output / "resource-preflight.json", resources)
    require_provisioning(resources)
    before = source_pair(chain)
    runtime, inherited = load_runtime(chain)
    family = runtime.verify_family(runtime.read_json(runtime.FAMILY_PATH))
    save(
        output / "precommit.json",
        {
            "source_pair": before,
            "run_context": run_context(),
            "public_model": family["reference"],
            "runtime_versions": {
                d.metadata["Name"]: d.version
                for d in importlib.metadata.distributions()
            },
            "python": sys.version,
            "training_steps_per_generation": 10,
            "training_threads": 2,
            "training_retries": 0,
            "holdout_retries": 0,
            "controlled_contract_only": True,
            **dict.fromkeys(DENIED, False),
        },
    )
    materials.mkdir(mode=0o700)
    for name, pin in family["material_pins"]["files"].items():
        require(Path(name).name == name, "flat public material filename required")
        url = (
            f"https://huggingface.co/{runtime.MODEL}/resolve/{runtime.REVISION}/{name}"
        )
        target = materials / name
        # The outer CI process owner bounds the complete download. Each read is
        # timeout- and byte-bounded; pins are checked before any model is loaded.
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            target.open("xb") as stream,
        ):
            require(response.url.startswith("https://"), "HTTPS redirect required")
            remaining = pin["size"]
            while remaining:
                chunk = response.read(min(1024 * 1024, remaining))
                require(bool(chunk), "truncated public material")
                stream.write(chunk)
                remaining -= len(chunk)
            require(not response.read(1), "oversized public material")
        require(sha(target) == pin["sha256"], "public material digest mismatch")
    manifest = {
        "model": runtime.MODEL,
        "revision": runtime.REVISION,
        "files": family["material_pins"]["files"],
    }
    save(materials / "material-manifest.json", manifest)
    runtime.verify_materials(materials)
    save(output / "material-manifest.json", manifest)
    training = {
        "schema": "hepta-smollm-training-input-v1",
        "scope": "public-smoke-fixtures",
        "records": [
            {key: row[key] for key in ("prompt", "expected_output")}
            for row in runtime.tasks()
            if row["partition"] == "training"
        ],
    }
    save(output / "training-input.json", training)
    for generation in (1, 2, 3):
        argv = [
            sys.executable,
            str(chain / "scripts/llm_inherited_runtime.py"),
            "train",
            "--materials",
            str(materials),
            "--output",
            str(output / f"gen{generation}"),
            "--operation-id",
            f"controlled-pair-{generation}",
            "--input",
            str(output / "training-input.json"),
            "--input-sha256",
            sha(output / "training-input.json"),
            "--threads",
            "2",
            "--steps",
            "10",
        ]
        if generation == 1:
            argv += ["--bootstrap"]
        else:
            previous, _ = parent(output, generation - 1, inherited)
            argv += ["--parent", str(previous), "--parent-sha256", sha(previous)]
        save(output / f"gen{generation}-command.json", argv)
        subprocess.run(
            argv, check=True
        )  # one dispatch; original Chain supervisor owns the worker
        parent(output, generation, inherited)
    baseline, _ = parent(output, 2, inherited)
    candidate, _ = parent(output, 3, inherited)
    shared = {
        "python": os.path.abspath(sys.executable),
        "chain": str(chain),
        "materials": str(materials),
    }
    save(
        output / "native-input.json",
        dict(
            shared,
            schema="hepta-smollm-neural-native-check-v1",
            parent=str(candidate),
            parent_sha256=sha(candidate),
            output=str(output / "native"),
        ),
    )
    save(
        output / "comparison-input.json",
        dict(
            shared,
            schema="hepta-smollm-neural-comparison-native-v1",
            baseline_parent=str(baseline),
            baseline_parent_sha256=sha(baseline),
            candidate_parent=str(candidate),
            candidate_parent_sha256=sha(candidate),
            output=str(output / "comparison"),
        ),
    )
    require(source_pair(chain) == before, "paired source changed during preparation")
    save(
        output / "prepared.json",
        {
            "source_pair": before,
            "run_context": run_context(),
            "parent_sha256": {"2": sha(baseline), "3": sha(candidate)},
            "commands": {kind: command(kind) for kind in ("native", "comparison")},
            **dict.fromkeys(DENIED, False),
        },
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("--chain", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--materials", type=Path)
    args = parser.parse_args()
    require(args.output.is_absolute(), "absolute observation directory required")
    if args.phase == "prepare":
        require(args.materials is not None, "material output path required")
        prepare(args)
    else:
        if __package__:
            from .hepta_ci_smollm_readback import verify
        else:
            from hepta_ci_smollm_readback import verify
        verify(args)


if __name__ == "__main__":
    main()
