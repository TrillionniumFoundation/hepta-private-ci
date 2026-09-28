#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
BOOTSTRAP = ROOT / ".github/workflows/control-engineering-bootstrap.yml"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    text = read(rel)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: expected one marker, found {count}: {old[:100]!r}"
        )
    write(rel, text.replace(old, new, 1))


def replace_function(rel: str, name: str, next_name: str, body: str) -> None:
    text = read(rel)
    start = text.index(f"def {name}(")
    end = text.index(f"\ndef {next_name}(", start)
    write(
        rel,
        text[:start]
        + textwrap.dedent(body).strip()
        + "\n\n"
        + text[end + 1 :],
    )


def append_once(rel: str, marker: str, body: str) -> None:
    text = read(rel)
    if marker not in text:
        write(rel, text.rstrip() + "\n\n" + textwrap.dedent(body).strip() + "\n")


replace_function(
    "scripts/hepta-implementation-maps.py",
    "checked_identity",
    "evidence_paths",
    r'''
    def checked_identity(
        value, candidate: dict[str, str], *, require_ancestor: bool = True
    ) -> dict[str, str]:
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str)
            or not re.fullmatch(r"[0-9a-f]{40}", value[key])
            for key in ("commit", "tree")
        ):
            raise ValueError("source identity requires literal commit/tree SHA-1 values")
        commit, tree = value["commit"], value["tree"]
        if git("cat-file", "-t", commit) != "commit":
            raise ValueError("source identity does not identify a commit")
        if git("rev-parse", f"{commit}^{{tree}}") != tree:
            raise ValueError("source tree mismatch")
        if require_ancestor:
            git("merge-base", "--is-ancestor", commit, candidate["commit"])
        return {"commit": commit, "tree": tree}


    def checked_observation_identity(value) -> dict[str, str]:
        """Validate audit metadata without making it a currentness authority."""
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str)
            or not re.fullmatch(r"[0-9a-f]{40}", value[key])
            for key in ("commit", "tree")
        ):
            raise ValueError("source observation requires literal commit/tree SHA-1 values")
        commit, tree = value["commit"], value["tree"]
        try:
            kind = git("cat-file", "-t", commit)
        except subprocess.CalledProcessError:
            return {"commit": commit, "tree": tree}
        if kind != "commit" or git("rev-parse", f"{commit}^{{tree}}") != tree:
            raise ValueError("source observation tree mismatch")
        return {"commit": commit, "tree": tree}
    ''',
)

replace_function(
    "scripts/hepta-implementation-maps.py",
    "verify_source_identity",
    "tracked_source_paths",
    r'''
    def _validate_exact_source_objects(row: dict, paths: list[str]) -> None:
        entries = row.get("sourceObjects")
        if not isinstance(entries, list) or not entries:
            raise ValueError("exact manifest policy requires sourceObjects")
        by_path: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid exact source object")
            path, object_id = entry.get("path"), entry.get("object")
            if not (
                isinstance(path, str)
                and path
                and isinstance(object_id, str)
                and re.fullmatch(r"[0-9a-f]{40}", object_id)
            ):
                raise ValueError("invalid exact source object")
            if path in by_path:
                raise ValueError("duplicate exact source object: " + path)
            checked_source_path(ROOT, path)
            actual = git("rev-parse", f"HEAD:{path}")
            if actual != object_id:
                raise SourceDrift("exact source object drift: " + path)
            by_path[path] = object_id
        missing = sorted(set(paths) - set(by_path))
        if missing:
            raise ValueError("exact source objects omit evidence: " + ", ".join(missing))
        for operation in row.get("operations", []):
            if not isinstance(operation, dict) or not operation.get("sourcePath"):
                continue
            path = operation["sourcePath"]
            expected = operation.get("sourceBlob")
            actual = git("rev-parse", f"HEAD:{path}")
            if expected != actual:
                raise SourceDrift("mapped operation blob drift: " + path)


    def verify_source_identity(
        row: dict, roots: list[str], candidate: dict[str, str], *, check_checkout=True
    ) -> list[str]:
        policy = row.get("sourceIdentityPolicy", "legacy_shared_batch")
        policies = {
            "legacy_shared_batch",
            "candidate_or_exact_observation_v1",
            "candidate_or_exact_manifest_v2",
        }
        if policy not in policies:
            raise ValueError(f"unknown source identity policy: {policy}")
        source = checked_identity(row.get("sourceBase"), candidate)
        mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
        if mapping_mode not in {"path_only", "exact_blob"}:
            raise ValueError(f"unknown mapping source identity mode: {mapping_mode}")
        if policy == "candidate_or_exact_manifest_v2" and mapping_mode != "exact_blob":
            raise ValueError("exact manifest policy requires exact_blob mode")
        paths = evidence_paths(row, roots)
        observations = [] if mapping_mode == "exact_blob" else [(source, paths)]
        observed_paths = row.get("observedSourcePaths", roots)
        observed = None
        if "observedAtHead" in row:
            if (
                not isinstance(observed_paths, list)
                or not observed_paths
                or any(not isinstance(path, str) for path in observed_paths)
            ):
                raise ValueError("invalid observed source paths")
            if not set(roots).issubset(observed_paths):
                raise ValueError("observed source paths omit resolved roots")
            if policy in {
                "candidate_or_exact_observation_v1",
                "candidate_or_exact_manifest_v2",
            } and any(
                source_root == "codex-rs" or source_root.startswith("codex-rs/")
                for source_root in roots
            ):
                required = {"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"}
                missing = sorted(required.difference(observed_paths))
                if missing:
                    raise ValueError(
                        "observed source paths omit Rust workspace build inputs "
                        + ", ".join(missing)
                    )
            if policy == "candidate_or_exact_manifest_v2":
                checked_observation_identity(row["observedAtHead"])
            else:
                observed = checked_identity(row["observedAtHead"], candidate)
                observations.append((observed, sorted(set(paths + observed_paths))))
        elif mapping_mode == "exact_blob":
            raise ValueError(
                "exact blob provenance requires an explicit current source observation"
            )
        if (
            policy == "candidate_or_exact_observation_v1"
            and mapping_mode != "exact_blob"
            and source not in (candidate, observed)
        ):
            raise ValueError("source base is neither candidate nor exact observed source")
        checked_paths = (
            sorted(set(paths + observed_paths))
            if policy == "candidate_or_exact_manifest_v2"
            else sorted({path for _, items in observations for path in items})
        )
        for path in checked_paths:
            if not checked_source_path(ROOT, path).exists():
                raise ValueError(f"missing observed source/evidence: {path}")
        if check_checkout:
            require_clean_candidate(candidate, checked_paths)
        require_tracked_paths(candidate["commit"], checked_paths)
        if policy == "candidate_or_exact_manifest_v2":
            _validate_exact_source_objects(row, checked_paths)
        else:
            for identity, identity_paths in observations:
                if identity == candidate:
                    continue
                require_tracked_paths(
                    identity["commit"], identity_paths, historical=True
                )
                changed = git(
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--name-only",
                    identity["commit"],
                    candidate["commit"],
                    "--",
                    *identity_paths,
                )
                if changed:
                    raise SourceDrift(
                        "mapped source/evidence changed after source observation: "
                        + changed
                    )
        if check_checkout:
            require_clean_candidate(candidate, checked_paths)
        return checked_paths
    ''',
)

maps_path = ROOT / "scripts/hepta-implementation-maps.py"
maps_text = maps_path.read_text(encoding="utf-8")
maps_text = maps_text.replace(
    '== "candidate_or_exact_observation_v1"',
    'in {"candidate_or_exact_observation_v1", "candidate_or_exact_manifest_v2"}',
)
maps_path.write_text(maps_text, encoding="utf-8")

wl = "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py"
replace_once(
    wl,
    "from .orchestration import CompletionReceipt, _verify_completion\n",
    "from .orchestration import CompletionReceipt, _verify_completion\n"
    "from .time_policy import (\n"
    "    ClockSkewPolicy,\n"
    "    STRICT_CLOCK_SKEW_POLICY,\n"
    "    validate_signed_window,\n"
    ")\n",
)
replace_once(
    wl,
    "@dataclass(frozen=True)\nclass WorkerHeartbeatReceipt:",
    "@dataclass(frozen=True)\n"
    "class WorkerRegistrationRenewalReceipt:\n"
    "    worker_id: str\n"
    "    expected_revision: int\n"
    "    predecessor_profile_digest: str\n"
    "    worker_signing_identity: str\n"
    "    skills: tuple[str, ...]\n"
    "    capacity_units: int\n"
    "    allowed_paths: tuple[str, ...]\n"
    "    issuer: str\n"
    "    signing_identity: str\n"
    "    observed_unix_ns: int\n"
    "    expires_unix_ns: int\n"
    "    signature: str = \"\"\n\n\n"
    "@dataclass(frozen=True)\n"
    "class WorkerHeartbeatReceipt:",
)
replace_once(
    wl,
    "    now_ns: int | None = None,\n) -> str:\n"
    "    now = _now(now_ns)\n"
    "    if not isinstance(receipt, WorkerRegistrationReceipt):",
    "    now_ns: int | None = None,\n"
    "    clock_policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,\n"
    ") -> str:\n"
    "    now = _now(now_ns)\n"
    "    if not isinstance(receipt, WorkerRegistrationReceipt):",
)
replace_once(
    wl,
    "    if not (\n"
    "        type(receipt.observed_unix_ns) is int\n"
    "        and type(receipt.expires_unix_ns) is int\n"
    "        and receipt.observed_unix_ns <= now < receipt.expires_unix_ns\n"
    "    ):\n"
    "        raise EngineeringError(\"worker_registration_stale\")\n",
    "    try:\n"
    "        validate_signed_window(\n"
    "            receipt.observed_unix_ns,\n"
    "            receipt.expires_unix_ns,\n"
    "            now,\n"
    "            policy=clock_policy,\n"
    "        )\n"
    "    except EngineeringError as error:\n"
    "        raise EngineeringError(\n"
    "            \"worker_registration_\" + error.code\n"
    "        ) from error\n",
)
renewal = r'''
def renew_worker_registration(
    store: EngineeringStore,
    receipt: WorkerRegistrationRenewalReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,
) -> str:
    """Renew or rotate one worker under exact revision/capacity fencing."""
    now = _now(now_ns)
    if not isinstance(receipt, WorkerRegistrationRenewalReceipt):
        raise EngineeringError("worker_registration_renewal_required")
    checked_id(receipt.worker_id, "worker_id")
    checked_id(receipt.worker_signing_identity, "worker_signing_identity")
    checked_sha256(receipt.predecessor_profile_digest, "predecessor_profile_digest")
    if receipt.issuer != WORKER_IDENTITY_ISSUER:
        raise EngineeringError("worker_registration_renewal_issuer_role")
    if type(receipt.expected_revision) is not int or receipt.expected_revision < 1:
        raise EngineeringError("invalid_worker_registration_revision")
    if (
        type(receipt.capacity_units) is not int
        or not 1 <= receipt.capacity_units <= 1_000_000
        or not isinstance(receipt.skills, tuple)
        or len(receipt.skills) > 64
        or len(set(receipt.skills)) != len(receipt.skills)
    ):
        raise EngineeringError("invalid_worker_profile")
    for skill in receipt.skills:
        checked_id(skill, "worker_skill")
    paths = canonical_paths(receipt.allowed_paths)
    try:
        validate_signed_window(
            receipt.observed_unix_ns,
            receipt.expires_unix_ns,
            now,
            policy=clock_policy,
        )
    except EngineeringError as error:
        raise EngineeringError(
            "worker_registration_renewal_" + error.code
        ) from error
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("worker_registration_renewal_signature")
    profile = {
        "workerId": receipt.worker_id,
        "workerSigningIdentity": receipt.worker_signing_identity,
        "skills": tuple(sorted(receipt.skills)),
        "capacityUnits": receipt.capacity_units,
        "allowedPaths": paths,
    }
    digest = semantic_digest(profile)
    receipt_digest = semantic_digest(asdict(receipt))
    with store._transaction():
        current = store.connection.execute(
            "SELECT * FROM worker_registrations WHERE worker_id=?",
            (receipt.worker_id,),
        ).fetchone()
        if current is None:
            raise EngineeringError("unknown_worker")
        current_revision = int(current["revision"])
        exact_result = (
            str(current["profile_digest"]) == digest
            and str(current["worker_signing_identity"])
            == receipt.worker_signing_identity
            and int(current["expires_unix_ns"]) == receipt.expires_unix_ns
            and str(current["state"]) == "active"
        )
        if receipt.expected_revision != current_revision:
            if receipt.expected_revision + 1 == current_revision and exact_result:
                return digest
            raise EngineeringError("stale_worker_revision")
        if str(current["state"]) != "active":
            raise EngineeringError("worker_not_active")
        if str(current["profile_digest"]) != receipt.predecessor_profile_digest:
            raise EngineeringError("worker_registration_predecessor_mismatch")
        if receipt.observed_unix_ns < int(current["observed_unix_ns"]):
            raise EngineeringError("worker_registration_renewal_order")
        if receipt.expires_unix_ns < int(current["expires_unix_ns"]):
            raise EngineeringError("worker_registration_expiry_regression")
        active = store.connection.execute(
            "SELECT COALESCE(SUM(capacity_units),0) AS units,"
            "COUNT(*) AS claims FROM worker_capacity_reservations "
            "WHERE worker_id=? AND state='active'",
            (receipt.worker_id,),
        ).fetchone()
        reserved_units = int(active["units"])
        active_claims = int(active["claims"])
        if receipt.capacity_units < reserved_units:
            raise EngineeringError(
                "worker_registration_capacity_below_reservation"
            )
        profile_changed = str(current["profile_digest"]) != digest
        signing_changed = (
            str(current["worker_signing_identity"])
            != receipt.worker_signing_identity
        )
        if active_claims and (profile_changed or signing_changed):
            raise EngineeringError(
                "worker_registration_rotation_active_claims"
            )
        if not profile_changed and not signing_changed and (
            receipt.expires_unix_ns == int(current["expires_unix_ns"])
        ):
            raise EngineeringError("worker_registration_not_advanced")
        revision = current_revision + 1
        updated = store.connection.execute(
            "UPDATE worker_registrations SET profile_digest=?,"
            "worker_signing_identity=?,skills_json=?,allowed_paths_json=?,"
            "capacity_units=?,issuer=?,authority_signing_identity=?,"
            "observed_unix_ns=?,expires_unix_ns=?,revision=?,"
            "recorded_unix_ns=? WHERE worker_id=? AND revision=? "
            "AND state='active'",
            (
                digest,
                receipt.worker_signing_identity,
                canonical_json(tuple(sorted(receipt.skills))),
                canonical_json(paths),
                receipt.capacity_units,
                receipt.issuer,
                receipt.signing_identity,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                revision,
                now,
                receipt.worker_id,
                receipt.expected_revision,
            ),
        )
        if updated.rowcount != 1:
            raise EngineeringError("worker_registration_renewal_race")
        store._append_audit(
            "worker_registration_renewed",
            {
                "workerId": receipt.worker_id,
                "priorProfileDigest": receipt.predecessor_profile_digest,
                "profileDigest": digest,
                "receiptDigest": receipt_digest,
                "revision": revision,
                "signingIdentityRotated": signing_changed,
            },
            now,
        )
    return digest
'''
text = read(wl)
marker = "\ndef revoke_worker(\n"
if marker not in text:
    raise RuntimeError("worker revoke marker missing")
write(wl, text.replace(marker, renewal + marker, 1))

pr = "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py"
replace_once(
    pr,
    "    WorkerRegistrationReceipt,\n    WorkerResultReceipt,\n",
    "    WorkerRegistrationReceipt,\n"
    "    WorkerRegistrationRenewalReceipt,\n"
    "    WorkerResultReceipt,\n",
)
replace_once(
    pr,
    "    recover_worker_lifecycle,\n    register_worker,\n",
    "    recover_worker_lifecycle,\n"
    "    register_worker,\n"
    "    renew_worker_registration,\n",
)
method = (
    "    def renew_worker(\n"
    "        self,\n"
    "        receipt: WorkerRegistrationRenewalReceipt,\n"
    "        *,\n"
    "        now_ns: int | None = None,\n"
    "    ) -> str:\n"
    "        return renew_worker_registration(\n"
    "            self.store, receipt, self.trust_store, now_ns=now_ns\n"
    "        )\n\n"
)
replace_once(pr, "    def claim(\n", method + "    def claim(\n")

init = "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
replace_once(
    init,
    "    WorkerRegistrationReceipt,\n    WorkerResultReceipt,\n",
    "    WorkerRegistrationReceipt,\n"
    "    WorkerRegistrationRenewalReceipt,\n"
    "    WorkerResultReceipt,\n",
)
replace_once(
    init,
    "    recover_worker_lifecycle,\n    register_worker,\n",
    "    recover_worker_lifecycle,\n"
    "    register_worker,\n"
    "    renew_worker_registration,\n",
)
replace_once(
    init,
    '    "WorkerRegistrationReceipt",\n    "WorkerResultReceipt",\n',
    '    "WorkerRegistrationReceipt",\n'
    '    "WorkerRegistrationRenewalReceipt",\n'
    '    "WorkerResultReceipt",\n',
)
replace_once(
    init,
    '    "recover_worker_lifecycle",\n    "register_worker",\n',
    '    "recover_worker_lifecycle",\n'
    '    "register_worker",\n'
    '    "renew_worker_registration",\n',
)
replace_once(
    init,
    "from .external_controls import (\n",
    "from .audit_checkpoint import (\n"
    "    AuditCheckpoint,\n"
    "    create_audit_checkpoint,\n"
    "    verify_audit_suffix,\n"
    ")\n"
    "from .capacity_policy import (\n"
    "    StoreCapacityPolicy,\n"
    "    evaluate_store_capacity,\n"
    ")\n"
    "from .time_policy import (\n"
    "    ClockSkewPolicy,\n"
    "    FixedClock,\n"
    "    SystemClock,\n"
    "    validate_signed_window,\n"
    ")\n"
    "from .production_adapters import (\n"
    "    ProductionProviderSet,\n"
    "    validate_live_provider_set,\n"
    ")\n"
    "from .external_controls import (\n",
)
replace_once(
    init,
    '    "AssimilationProposal",\n',
    '    "AssimilationProposal",\n'
    '    "AuditCheckpoint",\n'
    '    "ClockSkewPolicy",\n'
    '    "FixedClock",\n'
    '    "SystemClock",\n'
    '    "StoreCapacityPolicy",\n'
    '    "ProductionProviderSet",\n',
)
replace_once(
    init,
    '    "admit_distributed_fence",\n',
    '    "admit_distributed_fence",\n'
    '    "create_audit_checkpoint",\n'
    '    "evaluate_store_capacity",\n',
)
replace_once(
    init,
    '    "validate_consent",\n',
    '    "validate_consent",\n'
    '    "validate_live_provider_set",\n'
    '    "validate_signed_window",\n',
)
replace_once(
    init,
    '    "verify_distributed_fence",\n',
    '    "verify_audit_suffix",\n'
    '    "verify_distributed_fence",\n',
)

map_path = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
row = json.loads(map_path.read_text(encoding="utf-8"))
row["sourceIdentityPolicy"] = "candidate_or_exact_manifest_v2"
row["productCallerState"] = (
    "repository_product_caller_dual_lane_and_post_merge_defined_execution_pending"
)
row["productionWriterState"] = "named_product_owner_composed_execution_pending"
existing = {item.get("operation") for item in row.get("operations", [])}
operations = [
    (
        "renew_worker_registration",
        "worker_registration_renewal_and_key_rotation",
        "worker_lifecycle.py",
    ),
    ("validate_signed_window", "clock_skew_policy", "time_policy.py"),
    ("create_audit_checkpoint", "audit_checkpoint", "audit_checkpoint.py"),
    (
        "evaluate_store_capacity",
        "sqlite_capacity_and_migration_threshold",
        "capacity_policy.py",
    ),
    (
        "validate_live_provider_set",
        "production_external_provider_ports",
        "production_adapters.py",
    ),
]
for operation, design, leaf in operations:
    if operation in existing:
        continue
    row.setdefault("operations", []).append(
        {
            "operation": operation,
            "designOperation": design,
            "nativeSymbol": operation,
            "sourcePath": (
                "tools/hepta-engineering-control/"
                "control_engineering_v2/"
                + leaf
            ),
            "state": "source_implemented",
            "authority": "none",
            "tests": [
                {
                    "path": (
                        "tools/hepta-engineering-control/"
                        "test_control_engineering_extensions.py"
                    )
                }
            ],
            "sourcePathExists": True,
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        }
    )
row["repositoryControlledGaps"] = [
    "Retain exact-source, deterministic synthetic-merge and post-merge main "
    "product receipts before changing the product-execution claim boundary.",
    "Retain strong Linux/Bubblewrap, mutation-testing and target-host receipts "
    "for the exact candidate.",
    "Product execution uses CI reference identities; independent acceptance "
    "and live external observations remain separate evidence.",
]
map_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")

append_once(
    "docs/modules/control.engineering/IMPLEMENTATION.md",
    "## Post-merge identity, renewal and scale closure",
    '''
    ## Post-merge identity, renewal and scale closure

    `candidate_or_exact_manifest_v2` separates ancestral `sourceBase` provenance,
    non-authoritative `observedAtHead` audit metadata, and the complete current
    `sourceObjects`/operation `sourceBlob` manifest. Pull requests retain source-head
    and base-merge receipts; pushes to `main` additionally emit an exact-main product
    and runtime-status artifact. Historical PR success cannot substitute for this gate.

    Worker registration supports authority-signed, revision-bound renewal and key
    rotation. Profile/key rotation fails while capacity is reserved; capacity cannot
    shrink below durable reservations. Signed windows use explicit `ClockSkewPolicy`.
    Externally retained `AuditCheckpoint` values enable bounded suffix verification,
    while `StoreCapacityPolicy` makes SQLite/WAL/audit/claim thresholds executable.
    ''',
)
append_once(
    "docs/modules/control.engineering/OPERATIONS.md",
    "## Post-merge gate and capacity thresholds",
    '''
    ## Post-merge gate and capacity thresholds

    Treat `control.engineering release blocker (exact main)` as required for release.
    It binds the actual post-merge SHA, runs gap closure, strong-sandbox owner tests and
    the named product caller, then retains product and status artifacts.

    Default planning starts at 2 GiB database size or five million audit events and
    hard-fails the target profile at 4 GiB database size, 1 GiB WAL, ten million audit
    events or 100,000 active claims. Replace these defaults with measured host policy.
    Retain audit checkpoints outside SQLite; suffix verification does not replace
    periodic full owner-state anchoring, backup restore or rollback rehearsal.
    ''',
)
append_once(
    "docs/modules/control.engineering/TECHNICAL.md",
    "## 16. Current canonical status and external dependency ports",
    '''
    ## 16. Current canonical status and external dependency ports

    `STATUS.json` is the committed source-status projection; exact SHA/run/artifact
    facts remain external receipts. `ProductionProviderSet` separates distributed
    fencing, immutable audit, hardware custody, completion and terminal observation.
    Fixture/mock/local-HMAC providers and role collisions fail closed. These ports do
    not claim a live provider, deployment, rollback rehearsal or operator acceptance.
    ''',
)

if BOOTSTRAP.exists():
    BOOTSTRAP.unlink()
if SELF.exists():
    SELF.unlink()
