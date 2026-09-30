#!/usr/bin/env python3
"""Verify the closed production Matrix transport trusted-computing boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/modules/channel.matrix/TRANSPORT_TCB.json"
SCHEMA = "hepta.channel-matrix-transport-tcb.v1"
RESULT_SCHEMA = "hepta.channel-matrix-transport-tcb-validation.v1"
REGISTRY_FIELDS = {
    "schema",
    "schemaVersion",
    "productionTransport",
    "trustModes",
    "identityFields",
    "requiredQualificationBindings",
    "testTransportPolicy",
}
PRODUCTION_FIELDS = {
    "type",
    "crate",
    "facadePath",
    "privateImplementationPath",
    "compositionPath",
    "authorityPath",
    "implementationPaths",
}
TRUST_FIELDS = {
    "safeRust",
    "unsafeRust",
    "ffi",
    "dynamicLibrary",
    "remoteSidecarPhysicalSend",
}
EXPECTED_TRUST = {
    "safeRust": "allowed_only_with_crate_forbid_unsafe",
    "unsafeRust": "forbidden",
    "ffi": "forbidden",
    "dynamicLibrary": "forbidden",
    "remoteSidecarPhysicalSend": "forbidden",
}
EXPECTED_IDENTITY_FIELDS = (
    "binding_revision",
    "device_id",
    "generation",
    "homeserver_id",
    "matrix_user_id",
    "room_id",
    "session_generation",
)
EXPECTED_BINDINGS = (
    "agentd_sha256",
    "configuration_sha256",
    "homeserver_image_digest",
    "matrixd_sha256",
    "process_identity_ledger_sha256",
    "runner_image",
    "target_triple",
    "test_binary_sha256",
)
MAX_BYTES = 512 * 1024
IMPLEMENTATION = re.compile(
    r"impl\s+MatrixOutboundTransport\s+for\s+MatrixSdkClient"
)
FORBIDDEN_TRANSPORT_TOKENS = (
    "libloading",
    "dlopen",
    'extern "C"',
    "Library::new",
)


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _read_text(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError(f"invalid TCB source: {relative}")
    return path.read_text(encoding="utf-8")


def _read_registry(path: Path) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate transport TCB key: {key}")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid transport TCB registry")
    row = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(row, dict):
        raise ValueError("transport TCB registry must be an object")
    return row


def _production_rust_paths(root: Path) -> list[Path]:
    source = root / "codex-rs/hepta-matrix-sdk/src"
    paths = []
    for path in sorted(source.rglob("*.rs")):
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        if (
            "/tests/" in lowered
            or path.name.endswith("_tests.rs")
            or path.name in {"gap_fill.rs"}
            or path.is_symlink()
        ):
            continue
        paths.append(path)
    return paths


def validate(
    root_value: Path = ROOT,
    registry_value: Path | None = None,
) -> dict[str, Any]:
    root = root_value.resolve(strict=True)
    registry_path = (
        registry_value
        if registry_value is not None
        else root / "docs/modules/channel.matrix/TRANSPORT_TCB.json"
    )
    registry_path = registry_path.resolve(strict=True)
    row = _read_registry(registry_path)
    if (
        set(row) != REGISTRY_FIELDS
        or row.get("schema") != SCHEMA
        or type(row.get("schemaVersion")) is not int
        or row["schemaVersion"] != 1
        or row.get("testTransportPolicy")
        != "public_trait_fixtures_only_not_product_composition"
    ):
        raise ValueError("unsupported transport TCB registry")
    transport = row.get("productionTransport")
    trust = row.get("trustModes")
    if (
        not isinstance(transport, dict)
        or set(transport) != PRODUCTION_FIELDS
        or transport.get("type") != "MatrixSdkClient"
        or transport.get("crate") != "codex-hepta-matrix-sdk"
        or not isinstance(trust, dict)
        or set(trust) != TRUST_FIELDS
        or trust != EXPECTED_TRUST
    ):
        raise ValueError("transport TCB identity or trust-mode drift")
    identity_fields = row.get("identityFields")
    bindings = row.get("requiredQualificationBindings")
    if (
        not isinstance(identity_fields, list)
        or tuple(identity_fields) != EXPECTED_IDENTITY_FIELDS
        or not isinstance(bindings, list)
        or tuple(bindings) != EXPECTED_BINDINGS
    ):
        raise ValueError("transport identity or qualification bindings drift")

    implementation_paths = transport.get("implementationPaths")
    if (
        not isinstance(implementation_paths, list)
        or implementation_paths != sorted(implementation_paths)
        or len(implementation_paths) != len(set(implementation_paths))
        or set(implementation_paths)
        != {transport["facadePath"], transport["privateImplementationPath"]}
    ):
        raise ValueError("invalid production transport implementation inventory")
    required_paths = [
        transport["facadePath"],
        transport["privateImplementationPath"],
        transport["compositionPath"],
        transport["authorityPath"],
        "codex-rs/hepta-matrix-sdk/src/lib.rs",
        "codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs",
    ]
    texts = {relative: _read_text(root, relative) for relative in required_paths}
    lib = texts["codex-rs/hepta-matrix-sdk/src/lib.rs"]
    boundary = texts["codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs"]
    facade = texts[transport["facadePath"]]
    runner = texts[transport["compositionPath"]]
    authority = texts[transport["authorityPath"]]

    if "#![forbid(unsafe_code)]" not in lib:
        raise ValueError("Matrix SDK crate no longer forbids unsafe code")
    if "pub use outbound_v2::MatrixSendPermit" in lib:
        raise ValueError("private MatrixSendPermit escaped the crate")
    if (
        "pub struct MatrixRawSendSeal" not in boundary
        or "_private: ()," not in boundary
        or "pub _private" in boundary
        or "trait MatrixAuthorizedTransport" not in boundary
        or "pub trait MatrixAuthorizedTransport" in boundary
        or "impl<T: MatrixOutboundTransport + ?Sized> MatrixAuthorizedTransport for T"
        not in boundary
    ):
        raise ValueError("sealed authorized transport boundary drift")
    if (
        "pub struct MatrixSdkClient" not in facade
        or "inner: implementation::MatrixSdkClient" not in facade
        or "pub fn client(" in facade
    ):
        raise ValueError("Matrix SDK facade exposes raw client authority")
    if (
        "MatrixSdkClient::login_or_restore" not in runner
        or "run_outbox_sender(" not in runner
        or "sidecar.as_ref()" not in runner
    ):
        raise ValueError("product composition does not use the registered transport")
    for field in EXPECTED_IDENTITY_FIELDS:
        if field not in authority:
            raise ValueError(f"transport identity binding disappeared: {field}")

    observed_impls: set[str] = set()
    source_hashes: list[dict[str, Any]] = []
    for path in _production_rust_paths(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if IMPLEMENTATION.search(text):
            observed_impls.add(relative)
        for token in FORBIDDEN_TRANSPORT_TOKENS:
            if token in text:
                raise ValueError(
                    f"production transport introduced forbidden dynamic boundary {token}: {relative}"
                )
        source_hashes.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _digest(path),
            }
        )
    if observed_impls != set(implementation_paths):
        raise ValueError(
            f"unregistered production Matrix transport implementation: {sorted(observed_impls)}"
        )
    if not source_hashes:
        raise ValueError("empty Matrix transport source inventory")
    return {
        "schema": RESULT_SCHEMA,
        "result": "pass",
        "registrySha256": _digest(registry_path),
        "productionTransport": transport,
        "observedImplementationPaths": sorted(observed_impls),
        "sourceHashes": source_hashes,
        "trustModes": trust,
        "identityFields": identity_fields,
        "requiredQualificationBindings": bindings,
        "authorityGranted": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        row = validate(args.root, args.registry)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        row = {
            "schema": RESULT_SCHEMA,
            "result": "fail",
            "error": str(exc),
            "authorityGranted": False,
            "activation": False,
            "promotion": False,
            "release": False,
        }
        print(json.dumps(row, sort_keys=True))
        return 2
    encoded = json.dumps(row, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output.absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
