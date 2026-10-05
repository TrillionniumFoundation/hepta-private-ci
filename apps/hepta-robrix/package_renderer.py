#!/usr/bin/env python3
"""Stage a normal renderer and its pinned presentation resources, without installing."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


MAKEPAD_REVISION = "493d23a7630f487d29912dd73f2cbb5b639b74ca"
SOURCE = Path(__file__).resolve().parent


def stage(binary: Path, makepad: Path, output: Path) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(makepad), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != MAKEPAD_REVISION:
        raise ValueError("Makepad checkout differs from the renderer lock")
    subprocess.run(["git", "-C", str(makepad), "diff", "--exit-code"], check=True)
    for font in json.loads((SOURCE / "licenses/original-font-notices.json").read_text()):
        data = (makepad / "widgets/resources" / font["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != font["sha256"]:
            raise ValueError(f"original font bytes changed: {font['file']}")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(binary, output / "hepta-robrix")
    (output / "hepta-robrix").chmod(0o755)
    for namespace, resources in (
        ("makepad_widgets", makepad / "widgets/resources"),
        ("robrix", SOURCE / "resources"),
    ):
        shutil.copytree(resources, output / "resources" / namespace / "resources")
    shutil.copytree(SOURCE / "licenses", output / "licenses")
    shutil.copyfile(makepad / "LICENSE", output / "licenses/Makepad-MIT.txt")
    shutil.copyfile(SOURCE / "LICENSE-MIT", output / "licenses/Robrix-MIT.txt")
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_symlink():
            raise ValueError("presentation bundle contains a symlink")
        if path.is_file():
            data = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
    (output / "bundle-manifest.json").write_text(
        json.dumps(
            {
                "schema": "hepta.native.renderer-bundle.v1",
                "makepad_revision": revision,
                "files": files,
                "installs_services": False,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--makepad-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    stage(arguments.binary.resolve(), arguments.makepad_source.resolve(), arguments.output)


if __name__ == "__main__":
    main()
