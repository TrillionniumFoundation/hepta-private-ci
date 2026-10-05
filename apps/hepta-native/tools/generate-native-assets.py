"""Verify the explicit pinned SDK input and generate compile-time asset bindings.

The outer build wrapper resolves manifest paths using locked Cargo metadata.
This program never discovers or modifies a Cargo cache and never fetches files.
"""

import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rust_string(value):
    value.encode("utf-8")
    hashes = "#"
    while '"' + hashes in value:
        hashes += "#"
    return "r" + hashes + '"' + value + '"' + hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--robrix-manifest-dir", type=Path, required=True)
    parser.add_argument("--liberation-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    catalog = json.loads((package / "resources/NATIVE-ASSETS.json").read_text())
    sdk = args.sdk_root.resolve(strict=True)
    robrix = args.robrix_manifest_dir.resolve(strict=True)
    pin = subprocess.check_output(
        ["git", "-C", str(sdk), "rev-parse", "HEAD"], text=True
    ).strip()
    if pin != catalog["makepadRevision"]:
        raise ValueError("SDK revision differs from the fixed asset catalog")
    subprocess.run(["git", "-C", str(sdk), "diff", "--quiet", "HEAD", "--"], check=True)
    helper = robrix.parents[1] / "tools/prepare-fonts.py"
    spec = importlib.util.spec_from_file_location("hepta_fonts", helper)
    fonts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fonts)
    cjk = fonts.prepare(Path(os.environ.get("HEPTA_CJK_FONT_CACHE", robrix.parent / "target/font-assets")), offline=True)
    cjk_paths = {a["logical"]: Path(a["inputPath"]) for a in cjk["assets"]}
    registered, records = [], []
    for asset in catalog["assets"]:
        logical = asset["logical"]
        crate, resource = logical.split("/", 1)
        if ".." in Path(resource).parts or Path(resource).is_absolute():
            raise ValueError("invalid logical asset path")
        if logical in cjk_paths:
            path = cjk_paths[logical]
        elif crate == "makepad_widgets":
            path = sdk / "widgets" / resource
        elif crate == "hepta_robrix_ui":
            path = robrix / resource
        else:
            raise ValueError("unexpected resource crate")
        data = path.read_bytes()
        if len(data) != asset["bytes"] or digest(data) != asset["sha256"]:
            raise ValueError("asset bytes differ: " + logical)
        registered.append(
            f"    ({rust_string(logical)}, include_bytes!({rust_string(str(path))})),"
        )
        records.append({**asset, "inputPath": str(path)})
    if len(registered) != 30 or len({r["logical"] for r in records}) != 30:
        raise ValueError("fixed asset inventory changed")
    notices = []
    for notice in catalog["noticeFileSha256"]:
        path = package / "resources" / notice["path"]
        data = path.read_bytes()
        if len(data) != notice["bytes"] or digest(data) != notice["sha256"]:
            raise ValueError("notice bytes differ: " + notice["path"])
        notices.append(
            f"    ({rust_string(notice['path'])}, include_bytes!({rust_string(str(path))})),"
        )
    source = catalog["liberationSource"]
    source_path = args.liberation_source.resolve(strict=True)
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != source["bytes"] or digest(source_bytes) != source["sha256"]:
        raise ValueError("corresponding source archive differs")
    manifests = [("makepad_widgets", sdk / "widgets"), ("hepta_robrix_ui", robrix)]
    rust = "const CRATE_MANIFESTS: &[(&str, &str)] = &[\n"
    rust += "\n".join(
        f"    ({rust_string(name)}, {rust_string(str(path))}),"
        for name, path in manifests
    )
    rust += "\n];\nconst ASSETS: &[(&str, &[u8])] = &[\n" + "\n".join(registered)
    rust += (
        "\n];\nconst NOTICES: &[(&str, &[u8])] = &[\n" + "\n".join(notices) + "\n];\n"
    )
    rust += f"const LIBERATION_SOURCE: &[u8] = include_bytes!({rust_string(str(source_path))});\n"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "native-assets.rs").write_text(rust)
    (args.out / "native-assets-input.json").write_text(
        json.dumps(
            {
                "schema": "hepta.native-assets-build-input.v1",
                "makepadRevision": pin,
                "catalogSha256": digest(
                    (package / "resources/NATIVE-ASSETS.json").read_bytes()
                ),
                "generatedRustSha256": digest(rust.encode()),
                "assets": records,
                "noticeFiles": catalog["noticeFileSha256"],
                "liberationSource": {**source, "inputPath": str(source_path)},
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
