"""Prepare verified native assets and an isolated, locked Robrix preview build.

No Cargo cache or canonical source is patched. A successful build is not GUI,
installed-product, update, or cross-platform qualification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

PIN = "337566c8b25d47f7e4fff6a202157b65bf183330"
GIT = "https://github.com/kevinaboos/makepad"
SOURCE = f"git+{GIT}?rev={PIN}#{PIN}"
FONT_SOURCE_URL = "https://releases.pagure.org/liberation-fonts/liberation-fonts-1.04.93.devel.src.tar.gz"
FONT_SOURCE_BYTES = 2255959
FONT_SOURCE_SHA = "fe3ea5f7a2d3bdea8b8f0d82cdc6c07d14ace67c6e06d7aa33b83fd9e640adae"
NATIVE = Path("apps/hepta-native")
ROBRIX = Path("apps/hepta-control-ui/rust/robrix-ui")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command, *, cwd=None, env=None):
    return subprocess.check_output(command, cwd=cwd, env=env, text=True)


def build_env(target: Path, asset_input: Path | None = None):
    env = dict(os.environ)
    for name in ("CARGO_BUILD_TARGET", "CARGO_ENCODED_RUSTFLAGS", "RUSTFLAGS"):
        env.pop(name, None)
    env.update(
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_JOBS="1",
        CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_PROFILE_TEST_DEBUG="0",
    )
    if asset_input is not None:
        env["HEPTA_NATIVE_ASSET_INPUT"] = str(asset_input)
    return env


def selected_inputs(metadata, root: Path):
    def unique(name):
        matches = [p for p in metadata["packages"] if p["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Require one resolved {name}, got {len(matches)}")
        return matches[0]

    native = unique("hepta-native")
    widgets = unique("makepad-widgets")
    robrix = unique("hepta-robrix-ui")
    if (
        native.get("source") is not None
        or Path(native["manifest_path"]).resolve() != root / NATIVE / "Cargo.toml"
    ):
        raise ValueError("Unexpected native package source")
    if widgets.get("source") != SOURCE or widgets.get("version") != "2.0.0":
        raise ValueError("Makepad metadata differs from the exact revision")
    if (
        robrix.get("source") is not None
        or Path(robrix["manifest_path"]).resolve() != root / ROBRIX / "Cargo.toml"
    ):
        raise ValueError("Robrix metadata must name this source topology")
    sdk = Path(widgets["manifest_path"]).resolve().parent.parent
    if Path(widgets["manifest_path"]).resolve() != sdk / "widgets/Cargo.toml":
        raise ValueError("Unexpected SDK widget manifest layout")
    return sdk, Path(robrix["manifest_path"]).resolve().parent


def metadata(root: Path, target: Path, offline: bool):
    command = [
        "cargo",
        "+1.95.0",
        "metadata",
        "--locked",
        "--all-features",
        "--format-version",
        "1",
        "--manifest-path",
        str(root / NATIVE / "Cargo.toml"),
    ]
    if offline:
        command.append("--offline")
    data = json.loads(run(command, cwd=root, env=build_env(target)))
    sdk, robrix = selected_inputs(data, root)
    if run(["git", "-C", str(sdk), "rev-parse", "HEAD"]).strip() != PIN:
        raise ValueError("SDK checkout revision mismatch")
    subprocess.run(
        ["git", "-C", str(sdk), "diff", "--exit-code", "HEAD", "--"], check=True
    )
    return sdk, robrix


def checked_font_source(path: Path | None, out: Path, download: bool):
    if path is None:
        if not download:
            raise ValueError(
                "Pass --liberation-source, or explicitly permit the fixed source download"
            )
        path = out / "liberation-fonts-1.04.93.devel.src.tar.gz"
        request = urllib.request.Request(
            FONT_SOURCE_URL, headers={"User-Agent": "Hepta-native-source-builder"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("Font source redirected away from HTTPS")
            data = response.read(FONT_SOURCE_BYTES + 1)
        if len(data) != FONT_SOURCE_BYTES or sha(data) != FONT_SOURCE_SHA:
            raise ValueError("Official font source bytes differ")
        path.write_bytes(data)
    path = path.resolve(strict=True)
    data = path.read_bytes()
    if len(data) != FONT_SOURCE_BYTES or sha(data) != FONT_SOURCE_SHA:
        raise ValueError("Font source archive identity mismatch")
    return path


def prepare_assets(
    root: Path, out: Path, target: Path, font_source: Path, offline: bool
):
    sdk, robrix = metadata(root, target, offline)
    subprocess.run(
        [
            "python3",
            str(root / "apps/hepta-control-ui/tools/prepare-fonts.py"),
            *(["--offline"] if offline else []),
        ],
        check=True,
        stdout=subprocess.PIPE,
    )

    generator = root / NATIVE / "tools/generate-native-assets.py"
    subprocess.run(
        [
            "python3",
            str(generator),
            "--sdk-root",
            str(sdk),
            "--robrix-manifest-dir",
            str(robrix),
            "--liberation-source",
            str(font_source),
            "--out",
            str(out),
        ],
        check=True,
    )
    generated = out / "native-assets.rs"
    receipt = json.loads((out / "native-assets-input.json").read_text())
    if receipt["makepadRevision"] != PIN or receipt["generatedRustSha256"] != sha(
        generated.read_bytes()
    ):
        raise ValueError("Asset generator receipt does not match bytes")
    return sdk, generated


def verify_assets(
    root: Path,
    out: Path,
    target: Path,
    font_source: Path,
    offline: bool,
    receipt_path: Path,
):
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Refusing an existing asset verification receipt")
    # Regenerate from the current locked topology, not from the previous JSON's
    # asserted file paths. The generator checks every asset/notice/source byte.
    with tempfile.TemporaryDirectory(
        prefix="native-assets-verify-", dir=out.parent
    ) as temporary:
        fresh = Path(temporary)
        sdk, _ = prepare_assets(root, fresh, target, font_source, offline)
        for name in ("native-assets.rs", "native-assets-input.json"):
            if (fresh / name).read_bytes() != (out / name).read_bytes():
                raise ValueError("Regenerated asset input differs: " + name)
    receipt = {
        "schema": "hepta.native-assets-verification.v1",
        "sdkRevision": PIN,
        "manifestSha256": sha((root / NATIVE / "Cargo.toml").read_bytes()),
        "lockSha256": sha((root / NATIVE / "Cargo.lock").read_bytes()),
        "catalogSha256": sha(
            (root / NATIVE / "resources/NATIVE-ASSETS.json").read_bytes()
        ),
        "generatorSha256": sha(
            (root / NATIVE / "tools/generate-native-assets.py").read_bytes()
        ),
        "helperSha256": sha(Path(__file__).read_bytes()),
        "cjkPreparationSha256": sha(
            (root / "apps/hepta-control-ui/tools/prepare-fonts.py").read_bytes()
        ),
        "cjkManifestSha256": sha(
            (root / ROBRIX / "resources/fonts/MANIFEST.json").read_bytes()
        ),
        "cjkLicenseSha256": sha(
            (root / ROBRIX / "resources/fonts/OFL.txt").read_bytes()
        ),
        "assetRustSha256": sha((out / "native-assets.rs").read_bytes()),
        "assetInputJsonSha256": sha((out / "native-assets-input.json").read_bytes()),
        "liberationSourceSha256": sha(font_source.read_bytes()),
        "sdkRoot": str(sdk),
        "sourceRoot": str(root),
        "regeneratedBytesMatch": True,
        "rendererQualified": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def toml_path(path: Path) -> str:
    text = str(path)
    text.encode("utf-8", errors="strict")
    return json.dumps(text, ensure_ascii=False).replace(chr(127), "\\u007f")


def platform_manifest(original: str):
    if "workspace" in tomllib.loads(original):
        raise ValueError("Unexpected standalone upstream platform workspace")
    section = ""
    lines = []
    count = 0
    for line in original.splitlines():
        if line.strip().startswith("["):
            section = line.strip()
        if "dependencies" in section:
            line, n = re.subn(
                r'path\s*=\s*"[^"]+"',
                f'git = "{GIT}", rev = "{PIN}"'
                if "{" in line
                else f'git = "{GIT}"\nrev = "{PIN}"',
                line,
            )
            count += n
        lines.append(line)
    if not count:
        raise ValueError("No pinned SDK sibling dependencies found")
    text = "\n".join(lines) + "\n\n[workspace]\n"
    parsed = tomllib.loads(text)

    def verify(table):
        for name, value in table.items():
            if isinstance(value, dict):
                if "dependencies" in name:
                    for dependency in value.values():
                        if isinstance(dependency, dict) and "path" in dependency:
                            raise ValueError("Unconverted SDK path dependency")
                verify(value)

    verify(parsed)
    return text


def overlay_lock(canonical: str):
    packages = tomllib.loads(canonical)["package"]
    matches = [
        p
        for p in packages
        if p["name"] == "makepad-platform" and p["version"] == "2.0.0"
    ]
    if len(matches) != 1 or matches[0].get("source") != SOURCE:
        raise ValueError("Canonical native lock must pin exactly one platform package")
    header = '[[package]]\nname = "makepad-platform"\nversion = "2.0.0"\n'
    expected = header + f'source = "{SOURCE}"\n'
    if canonical.count(expected) != 1:
        raise ValueError("Unexpected canonical platform lock format")
    result = canonical.replace(expected, header, 1)
    before = dict(matches[0])
    before.pop("source")
    after = [
        p
        for p in tomllib.loads(result)["package"]
        if p["name"] == "makepad-platform" and p["version"] == "2.0.0"
    ]
    if after != [before]:
        raise ValueError("Lock transform altered platform dependency semantics")
    return result


def extract_source(archive: Path, destination: Path):
    root = destination.resolve()
    with tarfile.open(archive) as source:
        for item in source:
            relative = Path(item.name)
            if relative.is_absolute() or ".." in relative.parts or not item.name:
                raise ValueError("Unsafe source archive member")
            path = root / relative
            if not path.parent.resolve().is_relative_to(root):
                raise ValueError("Source archive escaped through a link")
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_symlink():
                    raise ValueError("Source archive overwrites a symlink")
                stream = source.extractfile(item)
                if stream is None:
                    raise ValueError("Missing source archive file")
                with path.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                path.chmod(item.mode & 0o777)
            elif item.issym():
                target = Path(item.linkname)
                if target.is_absolute() or not (
                    path.parent / target
                ).resolve().is_relative_to(root):
                    raise ValueError("Source archive symlink escapes checkout")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(item.linkname)
            else:
                raise ValueError("Unsupported source archive member")


def prepare_preview(root: Path, out: Path, font_source: Path, offline: bool):
    if run(["git", "-C", str(root), "rev-parse", "--show-toplevel"]).strip() != str(
        root
    ):
        raise ValueError("Source root must be the canonical repository root")
    if run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]
    ).strip():
        raise ValueError("Preview subject requires committed source")
    source_sha = run(["git", "-C", str(root), "rev-parse", "HEAD"]).strip()
    source_tree = run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"]).strip()
    sdk, _ = metadata(root, out / "target", offline)
    if shutil.disk_usage(out).free < 3 * 1024**3:
        raise ValueError(
            "Native preview preparation requires at least 3 GiB free; no build started"
        )
    checkout, platform = out / "source", out / "makepad-platform"
    if checkout.exists() or platform.exists():
        raise ValueError(
            "Use a fresh preview output directory; existing artifacts are not reused"
        )
    checkout.mkdir()
    with tempfile.NamedTemporaryFile(dir=out, suffix=".tar") as archive:
        subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", source_sha],
            stdout=archive,
            check=True,
        )
        archive.flush()
        extract_source(Path(archive.name), checkout)
    shutil.copytree(sdk / "platform", platform)
    patch_root = checkout / NATIVE / "patches"
    identity_path = patch_root / "makepad-native-memory-only.json"
    identity = json.loads(identity_path.read_text())
    patch = patch_root / "makepad-native-memory-only.patch"
    if (
        identity["upstream"] != PIN
        or sha(patch.read_bytes()) != identity["patchSha256"]
    ):
        raise ValueError("Unexpected native platform overlay identity")
    for record in identity["files"]:
        path = Path(record["path"])
        if (
            path.is_absolute()
            or ".." in path.parts
            or sha((platform / path).read_bytes()) != record["beforeSha256"]
        ):
            raise ValueError("Unexpected native platform overlay input")
    subprocess.run(
        [
            "patch",
            "--batch",
            "--forward",
            "--fuzz=0",
            "-p1",
            "-d",
            str(platform),
            "-i",
            str(patch),
        ],
        check=True,
    )
    for record in identity["files"]:
        if sha((platform / record["path"]).read_bytes()) != record["afterSha256"]:
            raise ValueError("Native platform overlay output mismatch")
    original_platform = (platform / "Cargo.toml").read_text()
    rewritten = platform_manifest(original_platform)
    (platform / "Cargo.toml").write_text(rewritten)
    native_manifest = checkout / NATIVE / "Cargo.toml"
    original_native = native_manifest.read_text()
    if GIT in tomllib.loads(original_native).get("patch", {}):
        raise ValueError("Canonical native source already overrides Makepad")
    native_manifest.write_text(
        original_native
        + f'\n[patch."{GIT}"]\nmakepad-platform = {{ path = {toml_path(platform)} }}\n'
    )
    lock = checkout / NATIVE / "Cargo.lock"
    canonical_lock = lock.read_text()
    expected_lock = overlay_lock(canonical_lock)
    lock.write_text(expected_lock)
    # Resolve the generated topology again: its self: resource paths differ
    # from the canonical checkout and must match compile-time crate manifests.
    _, asset_input = prepare_assets(
        checkout, out / "assets", out / "target", font_source, offline
    )
    if lock.read_text() != expected_lock:
        raise ValueError(
            "Generated lock drifted beyond the sole platform source transform"
        )
    receipt = {
        "schema": "hepta.native-preview-build-input.v1",
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "sdkRevision": PIN,
        "platformPatch": identity,
        "canonicalLockSha256": sha(canonical_lock.encode()),
        "generatedLockSha256": sha(expected_lock.encode()),
        "canonicalNativeManifestSha256": sha(original_native.encode()),
        "generatedNativeManifestSha256": sha(native_manifest.read_bytes()),
        "canonicalPlatformManifestSha256": sha(original_platform.encode()),
        "generatedPlatformManifestSha256": sha(rewritten.encode()),
        "assetInputSha256": sha(asset_input.read_bytes()),
        "manifest": str(native_manifest),
        "assetInput": str(asset_input),
        "qualification": False,
    }
    (out / "native-preview-build-input.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return checkout, native_manifest, asset_input


def cjk_font_cache(requested: Path | None = None) -> Path:
    """Keep build and verification cache identity independent of --source-root.

    The verified source may be the generated checkout, while this same wrapper
    remains the caller. Explicit CLI/environment cache configuration wins.
    Never infer a cache from the previous asset receipt being verified.
    """
    configured = requested or os.environ.get("HEPTA_CJK_FONT_CACHE")
    if configured is not None:
        return Path(configured).resolve()
    wrapper_root = Path(__file__).resolve().parents[3]
    return wrapper_root / "apps/hepta-control-ui/rust/target/font-assets"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=[
            "prepare-assets",
            "verify-assets",
            "prepare-preview",
            "build-preview",
            "test-preview",
        ],
    )
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--liberation-source", type=Path)
    parser.add_argument("--download-font-source", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cjk-font-cache", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This developer preview is currently Linux-only")
    root = args.source_root.resolve(strict=True)
    os.environ["HEPTA_CJK_FONT_CACHE"] = str(cjk_font_cache(args.cjk_font_cache))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    font_source = checked_font_source(
        args.liberation_source, out, args.download_font_source
    )
    if args.mode == "verify-assets":
        if args.receipt is None:
            parser.error("verify-assets requires --receipt")
        verify_assets(
            root,
            out,
            out / "metadata-target",
            font_source,
            args.offline,
            args.receipt.absolute(),
        )
        return
    if args.mode == "prepare-assets":
        _, asset_input = prepare_assets(
            root, out, out / "metadata-target", font_source, args.offline
        )
        print(
            json.dumps(
                {
                    "assetInput": str(asset_input),
                    "assetInputSha256": sha(asset_input.read_bytes()),
                    "qualification": False,
                }
            )
        )
        return
    checkout, manifest, asset_input = prepare_preview(
        root, out, font_source, args.offline
    )
    if args.mode == "prepare-preview":
        return
    if shutil.disk_usage(out).free < 3 * 1024**3:
        raise ValueError("Native preview build requires at least 3 GiB free")
    env = build_env(out / "target", asset_input)
    if args.mode == "build-preview":
        command = [
            "cargo",
            "+1.95.0",
            "build",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--features",
            "robrix-preview",
            "--bin",
            "hepta-native",
        ]
    else:
        command = [
            "just",
            "--justfile",
            str(root / "justfile"),
            "test",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--workspace",
            "--all-targets",
            "--features",
            "robrix-preview",
        ]
        env["RUSTUP_TOOLCHAIN"] = "1.95.0"
    if args.offline:
        command.append("--offline")
    subprocess.run(
        command,
        cwd=root if args.mode == "test-preview" else checkout,
        env=env,
        check=True,
    )
    if (manifest.parent / "Cargo.lock").read_text() != overlay_lock(
        (root / NATIVE / "Cargo.lock").read_text()
    ):
        raise ValueError("Native preview build changed locked inputs")


if __name__ == "__main__":
    main()
