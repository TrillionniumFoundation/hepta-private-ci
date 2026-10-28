"""Pure static source assembly for the reviewed AWS DPoP compatibility proposal."""

import ast
import copy
import difflib
import io
import json
from pathlib import PurePosixPath
import tarfile
import tomllib
import zipfile

from hepta_pon_dependency_proposal import ROOT, sha256


EVIDENCE = ROOT / "qa/pon-aws-crypto-proposal-20261028-r9"


VENDOR = "codex-rs/third_party/aws-config-1.8.12-hepta-p256014"


INPUTS = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel.lock")


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"

TRANSPORT = ROOT / "qa/pon-aws-crypto-resolution-20261028-r11/source-inputs.zip"
TRANSPORT_SHA256 = "30985518acf4714a613407650a0a4ffeda6ff1dca3cdf8dd43c3bc5ab84e9cc0"
TRANSPORT_NAMES = {
    "overrides/BUILD.bazel",
    "overrides/src/login/dpop.rs",
    "upstream/index-records.json",
    "upstream/aws-config-main-c975.Cargo.toml.txt",
    *("original/" + name for name in INPUTS),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(raw):
    return {"bytes": len(raw), "sha256": sha256(raw)}


def retained_evidence(name):
    """Read original bytes without making an archived template an active package."""
    if name not in TRANSPORT_NAMES:
        path = EVIDENCE / safe_relative(name)
        require(path.is_file() and not path.is_symlink(), "missing retained input")
        return path.read_bytes()
    require(
        TRANSPORT.is_file() and not TRANSPORT.is_symlink(), "missing source transport"
    )
    raw = TRANSPORT.read_bytes()
    require(
        len(raw) == 335041 and sha256(raw) == TRANSPORT_SHA256,
        "source transport identity mismatch",
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(
            len(archive.infolist()) == len(TRANSPORT_NAMES)
            and set(archive.namelist()) == TRANSPORT_NAMES,
            "source transport member mismatch",
        )
        return archive.read(name)


def frozen_inputs():
    """Return actual pre-import hosted inputs for historical proposal controls."""
    return {name: retained_evidence("original/" + name) for name in INPUTS}


def safe_relative(name):
    path = PurePosixPath(name)
    require(
        bool(path.parts)
        and path.as_posix() == name
        and not path.is_absolute()
        and not any(part in {".", ".."} for part in path.parts)
        and "\\" not in name
        and ":" not in name,
        "unsafe source path",
    )
    return path


def archive_members(raw, prefix):
    payload = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        members = archive.getmembers()
        require(len(members) <= 1000, "source archive member limit")
        require(
            sum(member.size for member in members) <= 5_000_000,
            "source archive total limit",
        )
        for member in members:
            path = safe_relative(member.name)
            require(
                member.isfile() and member.size <= 1_000_000,
                "source must be a bounded regular file",
            )
            require(
                path.parts[0] == prefix and len(path.parts) > 1,
                "source prefix mismatch",
            )
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            require(relative not in payload, "duplicate source path")
            with archive.extractfile(member) as stream:
                content = stream.read(member.size + 1)
            require(len(content) == member.size, "source size mismatch")
            payload[relative] = content
    return payload


def source_proposal():
    specification = json.loads((EVIDENCE / "source-spec.json").read_text())
    require(
        specification["schema"] == "hepta-aws-crypto-source-proposal-v1"
        and set(specification["baseline_files"]) == set(INPUTS),
        "unreviewed source specification or original input coverage",
    )
    require(specification["vendor_path"] == VENDOR, "vendor destination mismatch")
    original = {}
    for entry in specification["source_archives"]:
        path = safe_relative(entry["path"])
        archive = EVIDENCE / path
        require(
            archive.is_file() and not archive.is_symlink(),
            "archive must be a regular file",
        )
        raw = archive.read_bytes()
        require(identity(raw) == entry["identity"], "source archive identity mismatch")
        members = archive_members(raw, "aws-config-1.8.12")
        require(not original.keys() & members.keys(), "overlapping source archives")
        original.update(members)
    require(
        {name: identity(raw) for name, raw in original.items()}
        == specification["original_source_files"],
        "complete original source inventory mismatch",
    )
    require(
        specification["omit_from_vendor"] == ["Cargo.lock"],
        "unreviewed source omission",
    )
    proposed = {name: raw for name, raw in original.items() if name != "Cargo.lock"}
    expected_overrides = {
        "Cargo.toml",
        "src/login/dpop.rs",
        "src/login/dpop_migration_tests.rs",
        "BUILD.bazel",
        "HEPTA_PATCH.md",
    }
    require(
        set(specification["overrides"]) == expected_overrides, "unreviewed override set"
    )
    for name, expected in specification["overrides"].items():
        safe_relative(name)
        raw = retained_evidence("overrides/" + name)
        require(identity(raw) == expected, "source override identity mismatch: " + name)
        proposed[name] = raw

    expected_manifest = tomllib.loads(original["Cargo.toml"].decode())
    expected_manifest["package"]["publish"] = False
    expected_manifest["dependencies"]["p256"]["version"] = "0.14.0"
    expected_manifest["dependencies"]["rand"]["version"] = "0.10.3"
    expected_manifest["dependencies"]["rand"]["features"].append("sys_rng")
    expected_manifest["dev-dependencies"]["ring"] = {"version": "0.17.14"}
    require(
        tomllib.loads(proposed["Cargo.toml"].decode()) == expected_manifest,
        "unreviewed provider manifest change",
    )
    original_tests = original["src/login/dpop.rs"].split(
        b"#[cfg(test)]\nmod tests {", 1
    )[1]
    require(
        original_tests in proposed["src/login/dpop.rs"],
        "original DPoP test block changed",
    )
    build = ast.parse(proposed["BUILD.bazel"].decode())
    libraries = [
        node.value
        for node in build.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "rust_library"
    ]
    require(len(libraries) == 1, "provider must have one explicit Bazel library")
    feature_definitions = [
        keyword.value
        for keyword in libraries[0].keywords
        if keyword.arg == "crate_features"
    ]
    require(len(feature_definitions) == 1, "Bazel provider features must be explicit")
    features = ast.literal_eval(feature_definitions[0])
    require(
        isinstance(features, list)
        and len(features) == 6
        and set(features)
        == {
            "credentials-login",
            "credentials-process",
            "default",
            "default-https-client",
            "rt-tokio",
            "sso",
        },
        "Bazel provider features differ from original production metadata",
    )
    return specification, original, proposed


def change_workspace(raw):
    original = tomllib.loads(raw.decode())
    expected = copy.deepcopy(original)
    member = VENDOR.removeprefix("codex-rs/")
    require(
        member not in expected["workspace"]["members"],
        "provider patch is already applied",
    )
    require(
        expected["workspace"]["dependencies"]["aws-config"] == "1",
        "unreviewed aws-config baseline",
    )
    require(
        expected["workspace"]["dependencies"]["aws-sigv4"] == "1",
        "unreviewed aws-sigv4 baseline",
    )
    require(
        "aws-config" not in expected["patch"]["crates-io"],
        "provider patch already exists",
    )
    index = expected["workspace"]["members"].index("third_party/i18n-config-0.4.8")
    expected["workspace"]["members"].insert(index, member)
    expected["workspace"]["dependencies"]["aws-config"] = "=1.8.12"
    expected["workspace"]["dependencies"]["aws-sigv4"] = "=1.6.4"
    expected["patch"]["crates-io"]["aws-config"] = {"path": member}
    changed = raw
    for before, after in (
        (
            b'    "third_party/i18n-config-0.4.8",\n',
            f'    "{member}",\n    "third_party/i18n-config-0.4.8",\n'.encode(),
        ),
        (b'\naws-config = "1"\n', b'\naws-config = "=1.8.12"\n'),
        (b'\naws-sigv4 = "1"\n', b'\naws-sigv4 = "=1.6.4"\n'),
        (
            b"[patch.crates-io]\n",
            f'[patch.crates-io]\n# Minimal upstream-compatible DPoP migration; all credential features retained.\naws-config = {{ path = "{member}" }}\n'.encode(),
        ),
    ):
        require(
            changed.count(before) == 1,
            "workspace declaration is not the reviewed exact line",
        )
        changed = changed.replace(before, after)
    require(
        tomllib.loads(changed.decode()) == expected,
        "unreviewed workspace semantics changed",
    )
    return changed


def retain_files(destination, files):
    for name, raw in sorted(files.items()):
        target = destination / safe_relative(name)
        require(
            not target.is_symlink()
            and not any(parent.is_symlink() for parent in target.parents),
            "refusing a symlink in the retained path",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists(), "refusing to overwrite a retained file")
        target.write_bytes(raw)


def static_review(baseline=None):
    specification, original, proposed = source_proposal()
    records = json.loads(retained_evidence("upstream/index-records.json"))
    registry = {
        entry["record"]["name"] + "-" + entry["record"]["vers"] + ".crate": entry[
            "record"
        ]
        for entry in records["records"]
    }
    checked_archives = {}
    for path in sorted((EVIDENCE / "upstream").glob("*.crate")):
        require(not path.is_symlink(), "registry archive must be a regular file")
        raw = path.read_bytes()
        require(
            path.name in registry and sha256(raw) == registry[path.name]["cksum"],
            "official archive differs from the frozen index: " + path.name,
        )
        checked_archives[path.name] = identity(raw)
    old_vectors = archive_members(
        (EVIDENCE / "upstream/aws-sigv4-1.3.7.crate").read_bytes(), "aws-sigv4-1.3.7"
    )
    new_vectors = archive_members(
        (EVIDENCE / "upstream/aws-sigv4-1.6.4.crate").read_bytes(), "aws-sigv4-1.6.4"
    )
    listed = json.loads(
        (EVIDENCE / "upstream/sigv4-original-vector-equivalence.json").read_text()
    )["vectors"]
    expected_vectors = {
        name: raw
        for name, raw in old_vectors.items()
        if len(PurePosixPath(name).parts) > 1 and not name.endswith(".rs")
    }
    require(
        len(listed) == len(expected_vectors) == 808
        and {entry["path"] for entry in listed} == set(expected_vectors),
        "SigV4 vector inventory differs",
    )
    for entry in listed:
        raw = expected_vectors[entry["path"]]
        require(
            raw == new_vectors.get(entry["path"])
            and identity(raw) == {key: entry[key] for key in ("bytes", "sha256")},
            "original SigV4 fixture changed: " + entry["path"],
        )
    if baseline is None:
        baseline = {name: (ROOT / name).read_bytes() for name in INPUTS}
    require(set(baseline) == set(INPUTS), "original input coverage differs")
    for name, expected in specification["baseline_files"].items():
        require(
            identity(baseline[name]) == expected,
            "source baseline differs: " + name,
        )
    workspace = change_workspace(baseline[INPUTS[0]])
    patch = []
    for name in sorted(set(original) | set(proposed)):
        before, after = original.get(name, b""), proposed.get(name, b"")
        if before == after or name == "Cargo.lock":
            continue
        patch.extend(
            difflib.unified_diff(
                before.decode().splitlines(True),
                after.decode().splitlines(True),
                fromfile="upstream/" + name,
                tofile="candidate/" + name,
                n=0,
            )
        )
    require(
        "".join(patch).encode() == (EVIDENCE / "provider-source.patch").read_bytes(),
        "reviewed provider patch differs",
    )
    expected_workspace_patch = "".join(
        difflib.unified_diff(
            baseline[INPUTS[0]].decode().splitlines(True),
            workspace.decode().splitlines(True),
            fromfile="a/codex-rs/Cargo.toml",
            tofile="b/codex-rs/Cargo.toml",
            n=0,
        )
    )
    require(
        expected_workspace_patch.encode()
        == (EVIDENCE / "workspace.patch").read_bytes(),
        "reviewed workspace patch differs",
    )
    return {
        "schema": "hepta-aws-crypto-source-static-review-v1",
        "original_files": len(original),
        "proposed_vendor_files": len(proposed),
        "original_omissions": ["Cargo.lock"],
        "existing_files_changed": sorted(
            name
            for name in original.keys() & proposed.keys()
            if original[name] != proposed[name]
        ),
        "new_files": sorted(proposed.keys() - original.keys()),
        "all_original_provider_feature_definitions_preserved": True,
        "original_dpop_test_block_byte_identical": True,
        "published_archives_match_frozen_registry": checked_archives,
        "sigv4_original_fixture_files_preserved": 808,
        "workspace_semantic_mutations_only": [
            "one explicit upstream test member",
            "exact aws-config and aws-sigv4 versions",
            "one aws-config path patch",
        ],
        "workspace_proposal": identity(workspace),
        "local_native_execution": False,
        "compiled_or_native_qualified": False,
        "bigint_blocker_closed": False,
    }
