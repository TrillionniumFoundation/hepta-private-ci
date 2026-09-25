#!/usr/bin/env python3
"""Build and verify unsigned ui.native development packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

APP = Path(__file__).resolve().parents[1]
BINARIES = ("hepta-native", "hepta-native-updater", "hepta-native-credential")
PLATFORMS = {"linux", "macos", "windows"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def copy_executable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o755)


def source_binary(release_dir: Path, name: str, platform: str) -> Path:
    suffix = ".exe" if platform == "windows" else ""
    path = release_dir / f"{name}{suffix}"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or unsafe release binary: {path}")
    return path


def package_layout(platform: str, staging: Path) -> tuple[Path, dict[str, str]]:
    if platform == "linux":
        root = staging / "HeptaNative.AppDir"
        paths = {name: f"usr/bin/{name}" for name in BINARIES}
    elif platform == "macos":
        root = staging / "Hepta Native.app"
        paths = {
            "hepta-native": "Contents/MacOS/hepta-native",
            "hepta-native-updater": "Contents/Helpers/hepta-native-updater",
            "hepta-native-credential": "Contents/Helpers/hepta-native-credential",
        }
    else:
        root = staging / "HeptaNative"
        paths = {name: f"{name}.exe" for name in BINARIES}
    return root, paths


def copy_platform_metadata(platform: str, root: Path) -> None:
    if platform == "linux":
        target = root / "usr/share/applications/hepta-native.desktop"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(APP / "packaging/linux/hepta-native.desktop", target)
    elif platform == "macos":
        target = root / "Contents/Info.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(APP / "packaging/macos/Info.plist", target)
    else:
        shutil.copyfile(APP / "packaging/windows/app.manifest", root / "app.manifest")
    shutil.copyfile(APP / "packaging/README.md", root / "PACKAGING.md")


def write_deterministic_zip(root: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as output:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = PurePosixPath(root.name) / PurePosixPath(
                path.relative_to(root).as_posix()
            )
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = stat.S_IMODE(path.stat().st_mode)
            info.external_attr = (stat.S_IFREG | mode) << 16
            output.writestr(info, path.read_bytes())


def _validated_members(source: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = source.infolist()
    names = [member.filename for member in members]
    if len(names) != len(set(names)):
        raise ValueError("package archive contains duplicate paths")
    roots = set()
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError(f"unsafe archive path: {member.filename}")
        roots.add(path.parts[0])
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode) or (mode and not stat.S_ISREG(mode)):
            raise ValueError(
                f"package archive contains a non-regular entry: {member.filename}"
            )
    if len(roots) != 1:
        raise ValueError("package archive must contain exactly one top-level root")
    return members


def validate_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as source:
        members = _validated_members(source)
        names = [member.filename for member in members]
        manifests = [
            name for name in names if name.endswith("/unsigned-package-manifest.json")
        ]
        if len(manifests) != 1:
            raise ValueError("package archive must contain one manifest")
        manifest = json.loads(source.read(manifests[0]))
        prefix = str(PurePosixPath(manifests[0]).parent)
        for relative, expected in manifest["binarySha256"].items():
            observed = sha256(source.read(f"{prefix}/{relative}"))
            if observed != expected:
                raise ValueError(f"packaged binary digest mismatch: {relative}")
        return manifest


def extract_verified_archive(archive: Path, destination: Path) -> Path:
    validate_archive(archive)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        members = _validated_members(source)
        root_name = PurePosixPath(members[0].filename).parts[0]
        for member in members:
            relative = PurePosixPath(member.filename)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(member))
            mode = (member.external_attr >> 16) & 0o777
            if mode:
                target.chmod(mode)
    return destination / root_name


def build_package(
    platform: str, architecture: str, release_dir: Path, out_dir: Path
) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    if (
        not architecture
        or len(architecture) > 64
        or re.fullmatch(r"[A-Za-z0-9._-]+", architecture) is None
    ):
        raise ValueError("architecture must be a bounded stable identifier")
    staging = out_dir / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    root, relative_paths = package_layout(platform, staging)
    root.mkdir(parents=True)
    binary_digests = {}
    for name, relative in relative_paths.items():
        source = source_binary(release_dir, name, platform)
        destination = root / relative
        copy_executable(source, destination)
        binary_digests[relative] = file_sha256(destination)
    copy_platform_metadata(platform, root)
    manifest = {
        "schema": "hepta.ui-native-unsigned-package.v1",
        "platform": platform,
        "architecture": architecture,
        "unsignedDevelopmentArtifact": True,
        "productionSigningObserved": False,
        "notarizationObserved": False,
        "releaseAuthorized": False,
        "binarySha256": binary_digests,
    }
    manifest_path = root / "unsigned-package-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = out_dir / f"hepta-native-{platform}-{architecture}-unsigned.zip"
    write_deterministic_zip(root, archive)
    validated = validate_archive(archive)
    if validated != manifest:
        raise ValueError("package manifest changed during archive round trip")
    extracted_root = extract_verified_archive(archive, out_dir / "extracted")
    receipt = {
        "schema": "hepta.ui-native-package-receipt.v1",
        "platform": platform,
        "architecture": architecture,
        "archive": archive.name,
        "archiveSha256": file_sha256(archive),
        "stagingRoot": root.relative_to(out_dir).as_posix(),
        "extractedRoot": extracted_root.relative_to(out_dir).as_posix(),
        "manifest": manifest,
    }
    receipt_path = out_dir / "package-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="hepta-native-package-") as raw:
        temp = Path(raw)
        for platform in sorted(PLATFORMS):
            release = temp / platform / "release"
            release.mkdir(parents=True)
            for name in BINARIES:
                suffix = ".exe" if platform == "windows" else ""
                path = release / f"{name}{suffix}"
                path.write_bytes(f"{platform}:{name}\n".encode())
                path.chmod(0o755)
            first = build_package(
                platform, "test-arch", release, temp / platform / "dist-a"
            )
            second = build_package(
                platform, "test-arch", release, temp / platform / "dist-b"
            )
            if first["archiveSha256"] != second["archiveSha256"]:
                raise AssertionError("packaging self-test is not reproducible")
            for receipt, directory in [(first, "dist-a"), (second, "dist-b")]:
                base = temp / platform / directory
                if not (base / receipt["stagingRoot"]).is_dir():
                    raise AssertionError("packaging self-test lost staging root")
                if not (base / receipt["extractedRoot"]).is_dir():
                    raise AssertionError(
                        "packaging self-test lost verified extracted root"
                    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=sorted(PLATFORMS))
    parser.add_argument("--architecture")
    parser.add_argument("--release-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("ui.native packaging self-test passed")
        return
    required = [args.platform, args.architecture, args.release_dir, args.out_dir]
    if any(value is None for value in required):
        parser.error("platform, architecture, release-dir and out-dir are required")
    receipt = build_package(
        args.platform,
        args.architecture,
        args.release_dir.resolve(),
        args.out_dir.resolve(),
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
