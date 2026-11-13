#!/usr/bin/env python3
"""Apply the deterministic platform.types phase-A closure patch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"missing phase-A anchor in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def append_before(path: str, anchor: str, addition: str) -> None:
    text = read(path)
    if addition in text:
        return
    if anchor not in text:
        raise RuntimeError(f"missing append anchor in {path}: {anchor!r}")
    write(path, text.replace(anchor, addition + anchor, 1))


def load_json(path: str) -> dict:
    return json.loads(read(path))


def save_json(path: str, value: dict) -> None:
    write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


# 1. Reject inherited JavaScript object properties as unknown numeric profiles.
replace_once(
    "codex-rs/hepta-types/bindings/generate_bindings.py",
    '''export function numericProfile(profileId) {{
  const row = NUMERIC_PROFILES[profileId];
  if (!row) throw new Error("unknown numeric profile");
  return row;
}}''',
    '''export function numericProfile(profileId) {{
  if (typeof profileId !== "string" || !Object.hasOwn(NUMERIC_PROFILES, profileId)) {{
    throw new Error("unknown numeric profile");
  }}
  return NUMERIC_PROFILES[profileId];
}}''',
)
append_before(
    "codex-rs/hepta-types/bindings/verify_generated.mjs",
    'const profile = numericProfile("signed-q32-nearest-ties-even-v1");\n',
    '''for (const profileId of ["constructor", "toString", "__proto__", "unknown-profile"]) {
  let rejected = false;
  try { numericProfile(profileId); } catch (_) { rejected = true; }
  if (!rejected) throw new Error(`generated JavaScript binding admitted unknown numeric profile: ${profileId}`);
}
''',
)
subprocess.run(
    ["python3", "codex-rs/hepta-types/bindings/generate_bindings.py"],
    cwd=ROOT,
    check=True,
)

# 2. Canonicalize Lane-A presentation order while validating a closed set rather
# than treating JSON array order as a semantic property.
expected_modules = [
    "platform.types",
    "platform.wire",
    "kernel.authority",
    "kernel.operations",
    "kernel.evidence",
    "auth.authbus",
    "secrets.heptabao",
]
for json_path, key in (
    ("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json", "modules"),
    ("docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json", "protocols"),
):
    value = load_json(json_path)
    rows = value[key]
    by_name = {row["module"]: row for row in rows}
    if set(by_name) != set(expected_modules) or len(rows) != len(expected_modules):
        raise RuntimeError(f"{json_path}: unexpected Lane-A module set")
    value[key] = [by_name[name] for name in expected_modules]
    save_json(json_path, value)

replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''    modules = matrix.get("modules")
    if (
        not isinstance(modules, list)
        or [row.get("module") for row in modules if isinstance(row, dict)]
        != EXPECTED_MODULES
    ):
        raise VerificationError("closed-world module order mismatch")
    for row in modules:
''',
    '''    modules = matrix.get("modules")
    module_names = (
        [row.get("module") for row in modules if isinstance(row, dict)]
        if isinstance(modules, list)
        else []
    )
    if (
        not isinstance(modules, list)
        or len(module_names) != len(EXPECTED_MODULES)
        or len(set(module_names)) != len(module_names)
        or set(module_names) != set(EXPECTED_MODULES)
    ):
        raise VerificationError("closed-world module set mismatch")
    by_name = {row["module"]: row for row in modules}
    ordered_modules = [by_name[module] for module in EXPECTED_MODULES]
    for row in ordered_modules:
''',
)
replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''    by_name = {row["module"]: row for row in modules}
    exact = {
''',
    '''    exact = {
''',
)
replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    validate_capability_map(matrix, capability, root)
    native = validate_native_bindings(root)
''',
    '''    normalized_matrix = dict(matrix)
    normalized_matrix["modules"] = ordered_modules
    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    validate_capability_map(normalized_matrix, capability, root)
    operations_capability = read_json(root / OPS_CAPABILITY_MAP_PATH.relative_to(ROOT))
    validate_operations_capability_map(normalized_matrix, operations_capability, root)
    native = validate_native_bindings(root)
''',
)
append_before(
    "qualification/module-execution-dossiers/test_lane_a_foundation.py",
    "    def test_every_current_capability_has_one_evidence_mapping(self) -> None:\n",
    '''    def test_matrix_validation_is_order_independent(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"] = list(reversed(value["modules"]))
        verify.validate_matrix(value)

''',
)

# 3. Repair the split kernel.operations capability registry used by the Lane-A
# verifier. Keep the reference model in the shared map and detailed durable
# capabilities in the module extension map.
reference_summary = "bounded deterministic operation-state reference model"
matrix = load_json("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json")
operations_row = next(row for row in matrix["modules"] if row["module"] == "kernel.operations")
operations_row["currentCapabilities"] = [
    reference_summary,
    "bounded in-memory outbox claim and acknowledgement model",
    "generation-fenced idempotent terminal observation",
    "atomic durable operation ledger and source outbox co-commit",
    "bounded leased outbox claims with generation fencing and crash-reopen takeover",
    "final-use authority dispatch admission with indeterminate recovery and terminal reconciliation",
    "destination-owner transaction dedupe primitive with immutable apply receipts",
    "bounded retention tombstones and backlog metrics",
    "explicit Agentd daemon lifecycle composition with observer-only reconciler and fail-closed default",
]
save_json("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json", matrix)

capability = load_json("docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
capability["entries"] = [
    row
    for row in capability["entries"]
    if row.get("module") != "kernel.operations" or row.get("summary") == reference_summary
]
capability["entryCount"] = len(capability["entries"])
save_json("docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json", capability)

ops_path = "docs/lane-a-foundation/kernel.operations/CAPABILITY_EVIDENCE_V2.json"
ops = load_json(ops_path)
existing_ids = {row["capabilityId"] for row in ops["entries"]}
new_ops_entries = [
    {
        "capabilityId": "kernel.operations.in-memory-outbox.v1",
        "summary": "bounded in-memory outbox claim and acknowledgement model",
        "publicSymbols": ["OperationOutbox", "claim_with_lease", "acknowledge"],
        "sourceEvidence": [
            {
                "path": "codex-rs/hepta-operations/src/outbox.rs",
                "mustContain": ["MAX_MODEL_OUTBOX_RECORDS", "claim_with_lease", "acknowledge"],
            }
        ],
        "positiveTests": [
            {
                "path": "codex-rs/hepta-operations/src/outbox_tests.rs",
                "mustContain": ["claim_with_lease"],
            }
        ],
        "negativeTests": [
            {
                "path": "codex-rs/hepta-operations/src/outbox_tests.rs",
                "mustContain": ["StaleLease"],
            }
        ],
        "durability": "none",
        "activation": "library_only",
        "productionCaller": None,
        "receiptStatus": "native_workflow_required",
    },
    {
        "capabilityId": "kernel.operations.generation-fenced-terminal.v1",
        "summary": "generation-fenced idempotent terminal observation",
        "publicSymbols": ["OperationLedger::observe_terminal"],
        "sourceEvidence": [
            {
                "path": "codex-rs/hepta-operations/src/ledger.rs",
                "mustContain": ["pub fn observe_terminal", "owner_generation"],
            }
        ],
        "positiveTests": [
            {
                "path": "codex-rs/hepta-operations/src/ledger_tests.rs",
                "mustContain": ["observe_terminal"],
            }
        ],
        "negativeTests": [
            {
                "path": "codex-rs/hepta-operations/src/ledger_tests.rs",
                "mustContain": ["GenerationMismatch"],
            }
        ],
        "durability": "none",
        "activation": "library_only",
        "productionCaller": None,
        "receiptStatus": "native_workflow_required",
    },
    {
        "capabilityId": "kernel.operations.agentd-lifecycle-composition.v1",
        "summary": "explicit Agentd daemon lifecycle composition with observer-only reconciler and fail-closed default",
        "publicSymbols": ["AgentdProductionWriterHost", "run_production_operation_reconciler"],
        "sourceEvidence": [
            {
                "path": "codex-rs/hepta-agentd/src/production_writer_host.rs",
                "mustContain": ["AgentdProductionWriterHost", "ProductionFinalUseOutboxDispatcher"],
            },
            {
                "path": "codex-rs/hepta-agentd/src/runtime.rs",
                "mustContain": ["run_production_operation_reconciler", "CompletedRuntimeTask::Operations"],
            },
        ],
        "positiveTests": [
            {
                "path": "codex-rs/hepta-agentd/src/production_writer_host_tests.rs",
                "mustContain": ["AgentdProductionWriterHost"],
            }
        ],
        "negativeTests": [
            {
                "path": "codex-rs/hepta-agentd/src/production_writer_host_tests.rs",
                "mustContain": ["Indeterminate"],
            }
        ],
        "durability": "sqlite_wal_full_transactional",
        "activation": "explicit_daemon_runtime_source_composed_external_authority_not_enrolled",
        "productionCaller": None,
        "receiptStatus": "native_workflow_required",
    },
]
for entry in new_ops_entries:
    if entry["capabilityId"] not in existing_ids:
        ops["entries"].append(entry)
ops["entryCount"] = len(ops["entries"])
save_json(ops_path, ops)

replace_once(
    "scripts/lane_a_foundation_core.py",
    '''CAPABILITY_MAP_PATH = LANE / "CAPABILITY_EVIDENCE_MAP.json"
BOUNDARY_POLICY_PATH = LANE / "BOUNDARY_POLICY.md"
''',
    '''CAPABILITY_MAP_PATH = LANE / "CAPABILITY_EVIDENCE_MAP.json"
OPS_CAPABILITY_MAP_PATH = LANE / "kernel.operations/CAPABILITY_EVIDENCE_V2.json"
REFERENCE_OPERATIONS_SUMMARY = "bounded deterministic operation-state reference model"
BOUNDARY_POLICY_PATH = LANE / "BOUNDARY_POLICY.md"
''',
)
replace_once(
    "scripts/lane_a_foundation_core.py",
    '''    expected = [
        (module["module"], capability)
        for module in matrix["modules"]
        for capability in module["currentCapabilities"]
    ]
''',
    '''    expected = [
        (module["module"], capability)
        for module in matrix["modules"]
        for capability in module["currentCapabilities"]
        if module["module"] != "kernel.operations"
        or capability == REFERENCE_OPERATIONS_SUMMARY
    ]
''',
)
replace_once(
    "scripts/lane_a_foundation_core.py",
    '''    if observed != expected:
        raise VerificationError(
            "capability map does not exactly cover ordered current capabilities"
        )


def git_blob_sha(data: bytes) -> str:
''',
    '''    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise VerificationError(
            "capability map does not exactly cover current capabilities"
        )


def validate_operations_capability_map(
    matrix: dict[str, Any], value: dict[str, Any], root: Path = ROOT
) -> None:
    entries = value.get("entries")
    if (
        value.get("schemaVersion") != 1
        or value.get("module") != "kernel.operations"
        or value.get("role") != "durable_current_capability_extension"
        or not isinstance(entries, list)
        or value.get("entryCount") != len(entries)
    ):
        raise VerificationError("kernel.operations capability extension header mismatch")
    operations = next(
        (row for row in matrix["modules"] if row.get("module") == "kernel.operations"),
        None,
    )
    if operations is None:
        raise VerificationError("kernel.operations missing from Lane A matrix")
    expected = {
        summary
        for summary in operations["currentCapabilities"]
        if summary != REFERENCE_OPERATIONS_SUMMARY
    }
    observed: set[str] = set()
    ids: set[str] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise VerificationError("kernel.operations capability row must be an object")
        capability_id = row.get("capabilityId")
        summary = row.get("summary")
        if (
            not isinstance(capability_id, str)
            or not capability_id
            or capability_id in ids
            or not isinstance(summary, str)
            or not summary
            or summary in observed
        ):
            raise VerificationError("invalid/duplicate kernel.operations capability row")
        ids.add(capability_id)
        observed.add(summary)
        if row.get("receiptStatus") != "native_workflow_required":
            raise VerificationError(f"{capability_id}: invalid receipt status")
        symbols = row.get("publicSymbols")
        if not isinstance(symbols, list) or not symbols:
            raise VerificationError(f"{capability_id}: public symbols required")
        for field in ("sourceEvidence", "positiveTests", "negativeTests"):
            anchors = row.get(field)
            if not isinstance(anchors, list) or not anchors:
                raise VerificationError(f"{capability_id}: {field} required")
            for anchor in anchors:
                validate_anchor(f"{capability_id}/{field}", anchor, root)
    if observed != expected:
        raise VerificationError(
            "kernel.operations capability extension does not exactly cover current capabilities"
        )


def git_blob_sha(data: bytes) -> str:
''',
)
replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''        capabilities = read_json(CAPABILITY_MAP_PATH)
        bindings = read_json(NATIVE_BINDINGS_PATH)
        receipt = {
''',
    '''        capabilities = read_json(CAPABILITY_MAP_PATH)
        operations_capabilities = read_json(OPS_CAPABILITY_MAP_PATH)
        bindings = read_json(NATIVE_BINDINGS_PATH)
        receipt = {
''',
)
replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''            "capabilityMapSha256": hashlib.sha256(canonical(capabilities)).hexdigest(),
            "nativeBindingsSha256": hashlib.sha256(canonical(bindings)).hexdigest(),
''',
    '''            "capabilityMapSha256": hashlib.sha256(canonical(capabilities)).hexdigest(),
            "operationsCapabilityMapSha256": hashlib.sha256(
                canonical(operations_capabilities)
            ).hexdigest(),
            "nativeBindingsSha256": hashlib.sha256(canonical(bindings)).hexdigest(),
''',
)
replace_once(
    "scripts/lane_a_foundation_lib.py",
    '''            "capabilityCoverage": capabilities["entryCount"],
''',
    '''            "capabilityCoverage": capabilities["entryCount"]
            + operations_capabilities["entryCount"],
''',
)

# 4. Bring platform.types current implementation prose into the Lane-A standard
# section contract and include already-exported Prompt Delivery / Runtime Topology.
write(
    "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
    '''# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust foundational contract library.
It owns bounded values, profiled identifiers, monotonic identities, SHA-256
content digests, frozen HPTC V1 canonical bytes, checked fixed-point values,
immutable schema/normalization and numeric-profile registries, registered
numeric conversion, Prompt Delivery observations, Runtime Topology candidates,
and deterministic Python/JavaScript/TypeScript foundational bindings.

The crate forbids unsafe code and owns no clock, network, filesystem,
credential, durable writer, ambient registry, selection or effect authority.

## Public symbols and source bindings

- bounded values: `src/bounded.rs`;
- identities, generations and sealed non-authorizing posture: `src/identity.rs`;
- `Digest32` and bounded streaming digest: `src/digest.rs`;
- HPTC V1 encode, digest and raw validation: `src/canonical_digest.rs`;
- Q32 arithmetic: `src/fixed.rs`;
- immutable registry and numeric profiles: `src/registry.rs`,
  `src/numeric_profile.rs`;
- pure and registry-admitted numeric conversion: `src/numeric_conversion.rs`;
- `PromptDeliveryObservationV1` and rejection reason: `src/prompt_delivery.rs`;
- `RuntimeTopologyCandidateV1`, deltas and operations: `src/topology.rs`;
- generated language surfaces: `bindings/**` and `generated/**`.

Prompt Delivery is consumed by runtime/learning callers. Runtime Topology is
consumed by the Supervisor only after independent selection and exact baseline
checks. Neither contract grants execution or selection authority.

## Durability and activation

The module is stateless. Callers own immutable registry generations and any
persistence, authentication, revocation or lifecycle around them. Existing
source consumers do not make the complete module a production implementation.
`productCallerState` remains `not_composed` until a capability-specific named
product admission path and its executable evidence are recorded.

## Target-only design

The canonical registries assign `RandomStreamManifestV1`,
`ExternalSystemManifestV1` and `SensorCalibrationManifestV1` to this module,
but native Rust contracts for those three protocols remain source-pending in
this candidate. Authenticated registry provisioning, the full consumer compile
matrix, target-host measurements and independent semantic acceptance are also
separate gates.

## Known limits and non-claims

HPTC V1 is bounded to 256 KiB, 4096 container items and depth 16. Stable IDs are
bounded to 128 encoded bytes; numeric signals are bounded to 4096 elements and
registered definitions to 256 entries. Invalid input, overflow, unknown
profiles and nonzero raw authority bits fail closed.

Generated bindings cover only the frozen foundational binding specification;
they do not automatically expose arbitrary Rust structs as external schemas.
Documentation, source tests and generated bindings do not imply activation,
operator acceptance, promotion or release.

## Verification

Native tests cover bounds, ID grammar, authority rejection, digest parsing,
canonical encoding/validation, Q32 arithmetic, registry invariants, numeric
conversion, Prompt Delivery and Runtime Topology substitution rejection.
Python and Node execute five accepted and seven rejected HPTC vectors. Binding
checks regenerate all outputs and compare Python/JavaScript behavior, including
unknown numeric-profile names and JavaScript inherited-property names.

Lane A runs truth checks, native tests and strict lint for exact HEAD and the
deterministic synthetic merge. Executed workflow artifacts, not this prose, are
the qualification receipts.

## Integration prerequisites

A product owner must authenticate the immutable registry generation it supplies,
bind that generation at the physical admission boundary and retain any required
receipt. Consumers of Prompt Delivery and Runtime Topology must preserve their
producer/selector boundaries. The three owned manifest protocols require native
types, rejection tests and mapping before full owned-protocol source completion
can be claimed.
''',
)

# 5. Preserve independent truth/native feedback in Lane A while keeping a final
# all-required gate. Apply the transformation to both source and merge jobs.
workflow_path = ".github/workflows/lane-a-foundation.yml"
workflow = read(workflow_path)
workflow = workflow.replace(
    '''      - name: Verify current implementation, traceability and nonclaims
        env:
''',
    '''      - name: Verify current implementation, traceability and nonclaims
        id: source_truth
        continue-on-error: true
        env:
''',
    1,
)
workflow = workflow.replace(
    '''      - name: Run Lane A native tests and strict lint
        shell: bash
        run: scripts/run_lane_a_native_qualification.sh

      - name: Write exact-source and native receipts
''',
    '''      - name: Run Lane A native tests and strict lint
        id: source_native
        if: ${{ !cancelled() }}
        continue-on-error: true
        shell: bash
        run: scripts/run_lane_a_native_qualification.sh

      - name: Write exact-source and native receipts
        id: source_receipts
        if: ${{ steps.source_truth.outcome == 'success' && steps.source_native.outcome == 'success' }}
''',
    1,
)
workflow = workflow.replace(
    '''      - name: Retain exact source receipts
        uses: actions/upload-artifact@''',
    '''      - name: Retain exact source receipts
        id: source_artifacts
        if: ${{ steps.source_receipts.outcome == 'success' }}
        uses: actions/upload-artifact@''',
    1,
)
workflow = workflow.replace(
    '''          if-no-files-found: error
          retention-days: 90

  merge-candidate:
''',
    '''          if-no-files-found: error
          retention-days: 90

      - name: Require complete source-head qualification
        if: ${{ always() }}
        env:
          TRUTH_OUTCOME: ${{ steps.source_truth.outcome }}
          NATIVE_OUTCOME: ${{ steps.source_native.outcome }}
          RECEIPT_OUTCOME: ${{ steps.source_receipts.outcome }}
          ARTIFACT_OUTCOME: ${{ steps.source_artifacts.outcome }}
        shell: bash
        run: |
          set -euo pipefail
          test "$TRUTH_OUTCOME" = success
          test "$NATIVE_OUTCOME" = success
          test "$RECEIPT_OUTCOME" = success
          test "$ARTIFACT_OUTCOME" = success

  merge-candidate:
''',
    1,
)
workflow = workflow.replace(
    '''      - name: Verify synthetic merge truth
        env:
''',
    '''      - name: Verify synthetic merge truth
        id: merge_truth
        continue-on-error: true
        env:
''',
    1,
)
workflow = workflow.replace(
    '''      - name: Run Lane A native tests and strict lint on merge candidate
        shell: bash
        run: scripts/run_lane_a_native_qualification.sh

      - name: Write synthetic-merge receipts
''',
    '''      - name: Run Lane A native tests and strict lint on merge candidate
        id: merge_native
        if: ${{ !cancelled() }}
        continue-on-error: true
        shell: bash
        run: scripts/run_lane_a_native_qualification.sh

      - name: Write synthetic-merge receipts
        id: merge_receipts
        if: ${{ steps.merge_truth.outcome == 'success' && steps.merge_native.outcome == 'success' }}
''',
    1,
)
workflow = workflow.replace(
    '''      - name: Retain synthetic merge receipts
        uses: actions/upload-artifact@''',
    '''      - name: Retain synthetic merge receipts
        id: merge_artifacts
        if: ${{ steps.merge_receipts.outcome == 'success' }}
        uses: actions/upload-artifact@''',
    1,
)
if "Require complete synthetic-merge qualification" not in workflow:
    workflow = workflow.rstrip() + '''

      - name: Require complete synthetic-merge qualification
        if: ${{ always() }}
        env:
          TRUTH_OUTCOME: ${{ steps.merge_truth.outcome }}
          NATIVE_OUTCOME: ${{ steps.merge_native.outcome }}
          RECEIPT_OUTCOME: ${{ steps.merge_receipts.outcome }}
          ARTIFACT_OUTCOME: ${{ steps.merge_artifacts.outcome }}
        shell: bash
        run: |
          set -euo pipefail
          test "$TRUTH_OUTCOME" = success
          test "$NATIVE_OUTCOME" = success
          test "$RECEIPT_OUTCOME" = success
          test "$ARTIFACT_OUTCOME" = success
'''
write(workflow_path, workflow)

print("platform.types phase A applied")
