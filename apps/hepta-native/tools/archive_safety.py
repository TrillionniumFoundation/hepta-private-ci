"""Closed, bounded validation for the unsigned native package format.

Checksums detect accidental/substituted content only when the expected package
identity is independently bound by CI. They are not signing or release authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.ui-native-unsigned-package.v2"
MANIFEST = "unsigned-package-manifest.json"
MAX_MEMBERS = 64
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * MAX_MEMBER_BYTES + 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z")
ROOTS = {"linux": "HeptaNative.AppDir", "macos": "Hepta Native.app", "windows": "HeptaNative"}
BINARIES = ("hepta-native", "hepta-native-updater", "hepta-native-credential")
WINDOWS_IDENTITY_SCRIPT = "Register-HeptaNativeIdentity.ps1"
DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_path(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or len(name) > 512:
        raise ValueError("package path is absent or exceeds its bound")
    if any(ord(char) < 32 or ord(char) >= 127 or char in '<>:"\\|?*' for char in name):
        raise ValueError(f"nonportable package path: {name!r}")
    parts = name.split("/")
    if any(not part or part in {".", ".."} or len(part) > 128
           or part.endswith((" ", ".")) or part.split(".", 1)[0].casefold() in DEVICES
           for part in parts):
        raise ValueError(f"ambiguous package path: {name!r}")
    return PurePosixPath(*parts)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


def validated_members(source: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = source.infolist()
    if not members or len(members) > MAX_MEMBERS:
        raise ValueError("package member population exceeds policy")
    seen, roots, total = set(), set(), 0
    for member in members:
        path = safe_path(member.filename)
        if len(path.parts) < 2:
            raise ValueError("package member must be below one product root")
        identity = member.filename.casefold()
        if identity in seen:
            raise ValueError("duplicate or case-aliased package member")
        seen.add(identity)
        roots.add(path.parts[0])
        mode = member.external_attr >> 16
        if (stat.S_IFMT(mode) not in {0, stat.S_IFREG} or member.is_dir()
                or mode & 0o7000 or member.flag_bits & 1):
            raise ValueError("non-regular, privileged or encrypted package member")
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError("unsupported package compression")
        if member.file_size < 0 or member.file_size > MAX_MEMBER_BYTES:
            raise ValueError("package member size exceeds policy")
        total += member.file_size
    if total > MAX_TOTAL_BYTES or len(roots) != 1:
        raise ValueError("package size or top-level roots violate policy")
    for name in seen:
        parts = name.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise ValueError("package file/directory prefix collision")
    return members


def member_digest(source: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    digest, count = hashlib.sha256(), 0
    with source.open(member) as stream:
        while block := stream.read(64 * 1024):
            count += len(block)
            if count > member.file_size or count > MAX_MEMBER_BYTES:
                raise ValueError("package member expanded beyond its declared bound")
            digest.update(block)
    if count != member.file_size:
        raise ValueError("package member is truncated")
    return digest.hexdigest()


def binary_paths(platform: str) -> set[str]:
    if platform == "linux":
        return {f"usr/bin/{name}" for name in BINARIES}
    if platform == "macos":
        return {"Contents/MacOS/hepta-native", "Contents/Helpers/hepta-native-updater",
                "Contents/Helpers/hepta-native-credential"}
    return {f"{name}.exe" for name in BINARIES}


def platform_metadata(platform: str) -> set[str]:
    if platform == "linux":
        return {"usr/share/applications/hepta-native.desktop", "PACKAGING.md"}
    if platform == "macos":
        return {"Contents/Info.plist", "PACKAGING.md"}
    return {"app.manifest", WINDOWS_IDENTITY_SCRIPT, "PACKAGING.md"}


def validate_open_archive(source: zipfile.ZipFile) -> tuple[dict, list[zipfile.ZipInfo]]:
    members = validated_members(source)
    by_name = {member.filename: member for member in members}
    root = PurePosixPath(members[0].filename).parts[0]
    manifest_path = f"{root}/{MANIFEST}"
    info = by_name.get(manifest_path)
    if info is None or info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError("missing or oversized package manifest")
    manifest = json.loads(source.read(info), object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported unsigned package schema")
    platform = manifest.get("platform")
    if not isinstance(platform, str) or ROOTS.get(platform) != root:
        raise ValueError("package platform/root mismatch")
    architecture = manifest.get("architecture")
    if not isinstance(architecture, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", architecture):
        raise ValueError("invalid package architecture")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version) or version == "0.0.0":
        raise ValueError("package requires a non-placeholder product version")
    for field, expected in (("unsignedDevelopmentArtifact", True),
                            ("productionSigningObserved", False),
                            ("notarizationObserved", False), ("releaseAuthorized", False)):
        if manifest.get(field) is not expected:
            raise ValueError(f"unsigned package cannot promote {field}")
    if manifest.get("windowsAppUserModelIdRegistrationIncluded") is not (platform == "windows"):
        raise ValueError("Windows identity registration declaration is inconsistent")
    if manifest.get("linuxPortalFirstPicker") is not (platform == "linux"):
        raise ValueError("Linux portal declaration is inconsistent")
    files, binaries = manifest.get("fileSha256"), manifest.get("binarySha256")
    if not isinstance(files, dict) or not isinstance(binaries, dict):
        raise ValueError("missing closed package inventories")
    if set(binaries) != binary_paths(platform):
        raise ValueError("package binary population is not the three product executables")
    if set(files) != binary_paths(platform) | platform_metadata(platform):
        raise ValueError("package file population differs from the platform contract")
    for relative, expected in files.items():
        safe_path(relative)
        if not isinstance(expected, str) or not HEX.fullmatch(expected):
            raise ValueError("invalid package file digest")
    expected_names = {f"{root}/{relative}" for relative in files} | {manifest_path}
    if expected_names != set(by_name):
        raise ValueError("package contains missing or unlisted files")
    for relative, expected in binaries.items():
        if files.get(relative) != expected:
            raise ValueError("binary and file inventories disagree")
    for relative, expected in files.items():
        if member_digest(source, by_name[f"{root}/{relative}"]) != expected:
            raise ValueError(f"packaged file digest mismatch: {relative}")
    return manifest, members


def validate_archive(archive: Path) -> dict:
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("package archive must be a regular non-symlink file")
    with zipfile.ZipFile(archive) as source:
        return validate_open_archive(source)[0]


def extract_verified_archive(archive: Path, destination: Path) -> Path:
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("package archive must be a regular non-symlink file")
    # Never recursively delete an operator-selected path. Every attempt has a
    # new destination; validation and extraction share the same open archive.
    if destination.exists() or destination.is_symlink():
        raise ValueError("package extraction destination must not already exist")
    if destination.parent.resolve() != destination.parent.absolute():
        raise ValueError("package extraction parent contains a symlink")
    with zipfile.ZipFile(archive) as source:
        manifest, members = validate_open_archive(source)
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            target = destination.joinpath(*safe_path(member.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as incoming, target.open("xb") as outgoing:
                count, digest = 0, hashlib.sha256()
                while block := incoming.read(64 * 1024):
                    count += len(block)
                    if count > member.file_size:
                        raise ValueError("member changed during extraction")
                    digest.update(block)
                    outgoing.write(block)
            if count != member.file_size:
                raise ValueError("truncated package extraction")
            relative = "/".join(safe_path(member.filename).parts[1:])
            if relative == MANIFEST:
                copied = json.loads(target.read_bytes(), object_pairs_hook=unique_object)
                if copied != manifest:
                    raise ValueError("manifest changed during extraction")
            elif digest.hexdigest() != manifest["fileSha256"][relative]:
                raise ValueError("member digest changed during extraction")
            target.chmod((member.external_attr >> 16) & 0o777 or 0o644)
    return destination / PurePosixPath(members[0].filename).parts[0]
