#!/usr/bin/env python3
"""Compile concrete external Bao/Operations API controls with the pinned compiler.

Positive control must compile first. Each negative must fail with its specific
privacy/type diagnostic, not an unrelated setup error. This is not exhaustive
API enumeration, macro analysis, runtime authority, or deployment qualification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUST = ROOT / "codex-rs"
CRATES = {
    "codex_hepta_authbus",
    "codex_hepta_bao_adapter",
    "codex_hepta_contracts",
    "codex_hepta_operations",
    "codex_hepta_types",
}
IMPORTS = """
use codex_hepta_authbus::AuthBusExecutionPort;
use codex_hepta_bao_adapter::{BaoClient, BaoDurableAuthBusAdmission,
    BaoDurableAuthBusReceipt, BaoReadRequest, BaoAuthBusEvidenceProvider};
use codex_hepta_contracts::{FinalUseAuthority, SignedFinalUseGrant};
use codex_hepta_operations::{DurableOperationStore, EnteredAuthBusOperationHandle};
use codex_hepta_types::{StableId, Digest32, Generation};
"""
CALL = """
pub fn call<E: BaoAuthBusEvidenceProvider>(client: &BaoClient,
    store: &DurableOperationStore, operation: &EnteredAuthBusOperationHandle,
    port: AuthBusExecutionPort<'_>, admission: &BaoDurableAuthBusAdmission,
    authority: &FinalUseAuthority, grant: &SignedFinalUseGrant,
    request: &BaoReadRequest, evidence: &mut E) {
    let _future = client.consume_kv_v2_with_durable_authbus_operation(
        store, operation, port, admission, authority, grant, request, evidence, |_| Ok(()));
}
"""
POSITIVE = (
    CALL
    + """
pub fn receipt_id(receipt: &BaoDurableAuthBusReceipt) -> &StableId { &receipt.operation_id }
pub fn read_identity(handle: &EnteredAuthBusOperationHandle) -> (&StableId, Digest32, Generation) {
    (handle.operation_id(), handle.semantic_digest(), handle.owner_generation())
}
"""
)
NEGATIVE = {
    "no_raw_admission_id": (
        "E0609",
        """
pub fn inject(admission: &mut BaoDurableAuthBusAdmission, id: StableId) { admission.operation_id = id; }
""",
    ),
    "wrong_operation_type": (
        "E0308",
        CALL.replace(
            "operation: &EnteredAuthBusOperationHandle", "operation: &StableId"
        ),
    ),
    "no_default_handle": (
        "E0277",
        """
pub fn forge() -> EnteredAuthBusOperationHandle { Default::default() }
""",
    ),
    "no_metadata_conversion": (
        "E0277",
        """
pub fn forge(id: StableId) -> EnteredAuthBusOperationHandle { id.into() }
""",
    ),
}

# Independent access probes ensure every existing authority-bearing field is
# private; a single struct literal failure would prove only one private field.
for field in (
    "scope_id",
    "operation_id",
    "destination",
    "payload_digest",
    "semantic_digest",
    "owner_generation",
    "revision",
    "writer_fence",
):
    NEGATIVE[f"private_handle_{field}"] = (
        "E0616",
        f"pub fn inspect(handle: &EnteredAuthBusOperationHandle) {{ let _ = &handle.{field}; }}",
    )


def main() -> None:
    build = subprocess.run(
        [
            "cargo",
            "build",
            "--locked",
            "--lib",
            "-p",
            "codex-hepta-bao-adapter",
            "--message-format=json",
        ],
        cwd=RUST,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    artifacts = {}
    for line in build.stdout.splitlines():
        message = json.loads(line)
        name = message.get("target", {}).get("name")
        if message.get("reason") == "compiler-artifact" and name in CRATES:
            for filename in message["filenames"]:
                if filename.endswith(".rlib"):
                    artifacts[name] = filename
    if artifacts.keys() != CRATES:
        raise SystemExit(
            f"missing exact Cargo artifacts: {sorted(CRATES - artifacts.keys())}"
        )
    compiler = os.environ.get("RUSTC", "rustc")
    version = subprocess.check_output(
        [compiler, "--version"], cwd=RUST, text=True
    ).strip()
    common = [
        compiler,
        "--edition=2024",
        "--crate-type=lib",
        "--emit=metadata",
        "--error-format=json",
    ]
    for directory in sorted({str(Path(path).parent) for path in artifacts.values()}):
        common.extend(["-L", f"dependency={directory}"])
    for name, path in sorted(artifacts.items()):
        common.extend(["--extern", f"{name}={path}"])
    results = []
    with tempfile.TemporaryDirectory(prefix="authbus-external-api-") as temporary:
        directory = Path(temporary)
        cases = [
            ("positive_receipt_and_entry", None, POSITIVE),
            *[(name, expected, body) for name, (expected, body) in NEGATIVE.items()],
        ]
        for name, expected, body in cases:
            source = directory / f"{name}.rs"
            source.write_text(IMPORTS + body)
            run = subprocess.run(
                [
                    *common,
                    "--crate-name",
                    name,
                    str(source),
                    "-o",
                    str(directory / f"{name}.rmeta"),
                ],
                cwd=RUST,
                text=True,
                capture_output=True,
                check=False,
            )
            diagnostics = [
                json.loads(line)
                for line in run.stderr.splitlines()
                if line.startswith("{")
            ]
            codes = {
                entry["code"]["code"]
                for entry in diagnostics
                if isinstance(entry.get("code"), dict)
            }
            if expected is None and run.returncode != 0:
                raise SystemExit(f"positive control did not compile:\n{run.stderr}")
            if expected is not None and (run.returncode == 0 or expected not in codes):
                raise SystemExit(
                    f"{name} did not produce expected {expected}:\n{run.stderr}"
                )
            results.append(
                {
                    "name": name,
                    "expected_diagnostic": expected,
                    "observed_diagnostics": sorted(codes),
                    "status": "passed",
                }
            )
    print(
        json.dumps(
            {
                "compiler": version,
                "scope": "concrete external compile controls only",
                "checks": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
