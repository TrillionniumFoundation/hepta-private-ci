#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        if text.count(new) != 1:
            raise SystemExit(f"{label}: replacement is duplicated")
        return text
    if text.count(old) != 1:
        raise SystemExit(f"{label}: anchor missing or ambiguous")
    return text.replace(old, new, 1)


def patch_authority_trust() -> None:
    path = Path("codex-rs/hepta-contracts/src/authority_trust.rs")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use crate::final_use::FinalUseRevocations;\nuse ed25519_dalek::VerifyingKey;\n",
        "use crate::final_use::FinalUseRevocations;\n"
        "use crate::final_use_control::FinalUseControlError;\n"
        "use crate::final_use_control::FinalUseRevocationFeedVerifier;\n"
        "use crate::final_use_control::SignedFinalUseRevocationUpdate;\n"
        "use ed25519_dalek::VerifyingKey;\n",
        "authority trust imports",
    )

    verified_type = r'''
/// Opaque proof that one exact revocation head was authenticated by a
/// pinned distributor key while the signed feed was fresh.
///
/// Fields are private so a caller cannot turn an arbitrary
/// `FinalUseRevocations` value into production recovery authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFinalUseRevocationHead {
    distributor_id: String,
    trust_key_id: String,
    head: FinalUseRevocations,
    update_sha256: [u8; 32],
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
}

impl VerifiedFinalUseRevocationHead {
    pub fn verify(
        verifier: &FinalUseRevocationFeedVerifier,
        signed: &SignedFinalUseRevocationUpdate,
        now_unix_ms: u64,
    ) -> Result<Self, FinalUseControlError> {
        let trust_key_id = verifier.verify(signed, now_unix_ms)?.to_owned();
        let signing_bytes = signed.update.signing_bytes()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.kernel.authority.revocation-update-digest.v1\0");
        digest.update(signing_bytes);
        Ok(Self {
            distributor_id: signed.update.distributor_id.clone(),
            trust_key_id,
            head: signed.update.head.clone(),
            update_sha256: digest.finalize().into(),
            issued_at_unix_ms: signed.update.issued_at_unix_ms,
            expires_at_unix_ms: signed.update.expires_at_unix_ms,
        })
    }

    pub fn distributor_id(&self) -> &str {
        &self.distributor_id
    }

    pub fn trust_key_id(&self) -> &str {
        &self.trust_key_id
    }

    pub fn head(&self) -> &FinalUseRevocations {
        &self.head
    }

    pub fn update_sha256(&self) -> [u8; 32] {
        self.update_sha256
    }

    pub fn issued_at_unix_ms(&self) -> u64 {
        self.issued_at_unix_ms
    }

    pub fn expires_at_unix_ms(&self) -> u64 {
        self.expires_at_unix_ms
    }

    fn head_at(&self, now_unix_ms: u64) -> Result<FinalUseRevocations, FinalUseError> {
        if now_unix_ms < self.issued_at_unix_ms || now_unix_ms >= self.expires_at_unix_ms {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(self.head.clone())
    }
}

'''
    marker = "pub struct VerifiedFinalUseRevocationHead {"
    if marker not in text:
        anchor = "/// Complete production trust bundle. Construction and every privileged open\n"
        if text.count(anchor) != 1:
            raise SystemExit("verified revocation head insertion anchor drifted")
        text = text.replace(anchor, verified_type + anchor, 1)
    elif text.count(marker) != 1:
        raise SystemExit("verified revocation head type is duplicated")

    text = replace_once(
        text,
        '''pub fn open_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    head: FinalUseRevocations,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>''',
        '''pub fn open_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    verified_head: &VerifiedFinalUseRevocationHead,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>''',
        "production FinalUse open signature",
    )
    text = replace_once(
        text,
        '''pub fn recover_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    head: FinalUseRevocations,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>''',
        '''pub fn recover_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    verified_head: &VerifiedFinalUseRevocationHead,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>''',
        "production FinalUse recovery signature",
    )

    old = '''    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let clock: Arc<dyn AuthorityClock> = bundle.clock.clone();'''
    new = '''    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let now_unix_ms = bundle
        .clock
        .now_unix_ms()
        .map_err(|_| FinalUseError::InvalidTrust)?;
    let head = verified_head.head_at(now_unix_ms)?;
    let clock: Arc<dyn AuthorityClock> = bundle.clock.clone();'''
    if old in text:
        if text.count(old) != 2:
            raise SystemExit("production FinalUse validation anchors drifted")
        text = text.replace(old, new)
    elif text.count(new) != 2:
        raise SystemExit("production FinalUse verified-head validation is incomplete")

    path.write_text(text, encoding="utf-8")


def patch_authority_trust_tests() -> None:
    path = Path("codex-rs/hepta-contracts/src/authority_trust_tests.rs")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use ed25519_dalek::SigningKey;\n",
        "use ed25519_dalek::Signer;\nuse ed25519_dalek::SigningKey;\n",
        "authority trust test signer import",
    )
    text = replace_once(
        text,
        '''fn clock() -> Arc<QualifiedClock> {
    Arc::new(QualifiedClock {
        now_unix_ms: 2_000,
        trust_domain: "authority-root".into(),
        uncertainty_ms: 10,
    })
}''',
        '''fn clock_at(now_unix_ms: u64) -> Arc<QualifiedClock> {
    Arc::new(QualifiedClock {
        now_unix_ms,
        trust_domain: "authority-root".into(),
        uncertainty_ms: 10,
    })
}

fn clock() -> Arc<QualifiedClock> {
    clock_at(2_000)
}''',
        "qualified clock fixture",
    )

    marker = (
        "#[cfg(unix)]\n"
        "#[test]\n"
        "fn final_use_production_open_binds_exact_custodied_key_ring() {"
    )
    replacement = r'''#[cfg(unix)]
fn verified_revocation_head(
    head: &FinalUseRevocations,
    verified_at_unix_ms: u64,
    expires_at_unix_ms: u64,
) -> VerifiedFinalUseRevocationHead {
    let distributor = SigningKey::from_bytes(&[43; 32]);
    let update = FinalUseRevocationUpdate::new(
        "revocation-distributor".into(),
        head.clone(),
        1_000,
        expires_at_unix_ms,
    );
    let signed = SignedFinalUseRevocationUpdate {
        signature: distributor
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        update,
    };
    let verifier = FinalUseRevocationFeedVerifier::new(
        "revocation-distributor".into(),
        distributor.verifying_key().to_bytes(),
    )
    .unwrap();
    VerifiedFinalUseRevocationHead::verify(&verifier, &signed, verified_at_unix_ms).unwrap()
}

#[cfg(unix)]
#[test]
fn final_use_production_open_binds_exact_custodied_key_ring_and_verified_head() {
    let signer = SigningKey::from_bytes(&[41; 32]);
    let issuer_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-a".into(),
        verifying_key: signer.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    let key_set_sha256 = final_use_issuer_trust_sha256(&issuer_keys).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 2_000, 3_000);
    assert_eq!(verified_head.distributor_id(), "revocation-distributor");
    assert_eq!(verified_head.trust_key_id(), "single-key");
    assert_eq!(verified_head.head(), &head);
    assert_ne!(verified_head.update_sha256(), [0; 32]);
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let authority = open_production_final_use_authority(
        directory.path(),
        "security-owner".into(),
        issuer_keys.clone(),
        &verified_head,
        &bundle,
    )
    .unwrap();
    assert_eq!(authority.issuer_key_ids(), vec!["issuer-a"]);
    drop(authority);

    let wrong_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-b".into(),
        verifying_key: SigningKey::from_bytes(&[42; 32])
            .verifying_key()
            .to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    assert_eq!(
        recover_production_final_use_authority(
            directory.path(),
            "security-owner".into(),
            wrong_keys,
            &verified_head,
            &bundle,
        )
        .unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[cfg(unix)]
#[test]
fn production_open_rechecks_verified_head_freshness_on_the_protected_clock() {
    let signer = SigningKey::from_bytes(&[41; 32]);
    let issuer_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-a".into(),
        verifying_key: signer.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    let key_set_sha256 = final_use_issuer_trust_sha256(&issuer_keys).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 2_000, 3_000);
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock_at(4_000),
        frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    assert_eq!(
        open_production_final_use_authority(
            directory.path(),
            "security-owner".into(),
            issuer_keys,
            &verified_head,
            &bundle,
        )
        .unwrap_err(),
        FinalUseError::InvalidTrust
    );
}
'''
    if marker in text:
        text = text[: text.index(marker)] + replacement
    elif "final_use_production_open_binds_exact_custodied_key_ring_and_verified_head" not in text:
        raise SystemExit("production FinalUse trust test anchor drifted")
    path.write_text(text, encoding="utf-8")


def patch_agentd() -> None:
    path = Path("codex-rs/hepta-agentd/src/automation_effect_host.rs")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        revocation_feed_verifier
            .verify(&signed_update, now_unix_ms)
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "initial signed final-use revocation feed rejected: {error}"
                ))
            })?;
        let initial_revocations = signed_update.update.head.clone();''',
        '''        let verified_initial_head =
            codex_hepta_contracts::authority_trust::VerifiedFinalUseRevocationHead::verify(
                &revocation_feed_verifier,
                &signed_update,
                now_unix_ms,
            )
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "initial signed final-use revocation feed rejected: {error}"
                ))
            })?;
        let initial_revocations = verified_initial_head.head().clone();''',
        "Agentd verified initial revocation head",
    )
    path.write_text(text, encoding="utf-8")


def patch_extension_inventory() -> None:
    path = Path("qa/b4-no-bypass/KERNEL_AUTHORITY_EXTENSION_API.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value["types"]
    if not any(row["typeName"] == "VerifiedFinalUseRevocationHead" for row in rows):
        insert_at = next(
            index
            for index, row in enumerate(rows)
            if row["typeName"] == "ProductionAuthorityTrustBundle"
        )
        rows.insert(
            insert_at,
            {
                "typeName": "VerifiedFinalUseRevocationHead",
                "privilegedMethods": {},
                "nonPrivilegedMethods": [
                    "verify",
                    "distributor_id",
                    "trust_key_id",
                    "head",
                    "update_sha256",
                    "issued_at_unix_ms",
                    "expires_at_unix_ms",
                ],
            },
        )
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def patch_runtime_qualification() -> None:
    path = Path("qualification/kernel-authority/runtime_qualification.py")
    text = path.read_text(encoding="utf-8")
    load_start = text.index("def load_identity(path: Path) -> dict[str, Any]:")
    load_end = text.index("\n\ndef environment()", load_start)
    identity_functions = r'''def validate_candidate_structure(
    identity: dict[str, Any], git_reader=git
) -> None:
    mode = identity["mode"]
    source = identity["sourceCommit"]
    base = identity["baseCommit"]
    candidate = identity["candidateCommit"]
    candidate_tree = identity["candidateTree"]

    if mode == "exact-head" and candidate != source:
        raise QualificationError(
            "exact-head candidate commit does not equal the source commit"
        )
    try:
        resolved_source = git_reader("rev-parse", "--verify", f"{source}^{{commit}}")
        resolved_base = git_reader("rev-parse", "--verify", f"{base}^{{commit}}")
        resolved_candidate = git_reader(
            "rev-parse", "--verify", f"{candidate}^{{commit}}"
        )
        resolved_tree = git_reader(
            "rev-parse", "--verify", f"{candidate_tree}^{{tree}}"
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise QualificationError(
            f"candidate identity names a missing git object: {error}"
        ) from error
    if (
        resolved_source != source
        or resolved_base != base
        or resolved_candidate != candidate
        or resolved_tree != candidate_tree
    ):
        raise QualificationError("candidate identity is not exact")

    if mode == "exact-head":
        expected_tree = git_reader("rev-parse", f"{source}^{{tree}}")
        if candidate_tree != expected_tree:
            raise QualificationError(
                "exact-head candidate tree differs from the source tree"
            )
        return

    parent_line = git_reader("rev-list", "--parents", "-n", "1", candidate).split()
    if parent_line != [candidate, base, source]:
        raise QualificationError(
            "synthetic-merge candidate parents are not exact base/source"
        )
    merge_tree = git_reader("merge-tree", "--write-tree", base, source).splitlines()
    if not merge_tree or candidate_tree != merge_tree[0]:
        raise QualificationError(
            "synthetic-merge candidate tree is not the deterministic merge tree"
        )


def load_identity(path: Path) -> dict[str, Any]:
    identity = load_json_object(path, "candidate identity")
    if set(identity) != IDENTITY_FIELDS:
        raise QualificationError("candidate identity fields are not exact")
    if identity["schema"] != "hepta.kernel-authority-candidate.v1":
        raise QualificationError("unsupported candidate identity schema")
    if identity["mode"] not in {"exact-head", "synthetic-merge"}:
        raise QualificationError("unsupported candidate mode")
    for field in ("sourceCommit", "baseCommit", "candidateCommit", "candidateTree"):
        value = identity[field]
        if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
            raise QualificationError(
                f"{field} is not an exact lowercase commit/tree id"
            )
    if (
        identity["activationGranted"] is not False
        or identity["releaseGranted"] is not False
    ):
        raise QualificationError(
            "candidate identity must not grant activation or release"
        )
    validate_candidate_structure(identity)
    if git("rev-parse", "HEAD") != identity["candidateCommit"]:
        raise QualificationError("candidate identity does not match checkout HEAD")
    if git("rev-parse", "HEAD^{tree}") != identity["candidateTree"]:
        raise QualificationError("candidate identity does not match checkout tree")
    return identity'''
    text = text[:load_start] + identity_functions + text[load_end:]

    pilot_start = text.index(
        "def pilot(identity: dict[str, Any], output_dir: Path) -> int:"
    )
    pilot_end = text.index("\n\ndef validate_distribution", pilot_start)
    pilot_functions = r'''PILOT_COVERAGE_REQUIREMENTS = {
    "fleetPathExecuted": {"fleet-create-restart-revoke"},
    "browserAgentdPathExecuted": {
        "browser-agentd-final-use-boundary",
        "agentd-effect-owner-restart-and-receipt",
    },
    "restartRecoveryExercised": {
        "fleet-create-restart-revoke",
        "agentd-effect-owner-restart-and-receipt",
        "external-frontier-snapshot-rollback",
        "pending-revocation-crash-recovery-matrix",
    },
    "revocationExercised": {
        "fleet-create-restart-revoke",
        "pending-revocation-admission-fence",
        "pending-revocation-crash-recovery-matrix",
    },
    "snapshotRollbackExercised": {
        "external-frontier-snapshot-rollback",
        "frontier-ahead-local-commit-failure",
    },
    "keyRotationExercised": {"issuer-key-overlap-and-retirement"},
    "durableReceiptExercised": {
        "agentd-effect-owner-restart-and-receipt",
        "pending-revocation-crash-recovery-matrix",
    },
}


def pilot_coverage(results: list[dict[str, Any]]) -> dict[str, bool]:
    by_name = {result["name"]: result for result in results}
    expected = {case.name for case in PILOT_CASES}
    if set(by_name) != expected or len(by_name) != len(results):
        raise QualificationError(
            "product pilot result set does not exactly match the declared cases"
        )
    missing = sorted(
        name
        for names in PILOT_COVERAGE_REQUIREMENTS.values()
        for name in names
        if name not in expected
    )
    if missing:
        raise QualificationError(
            f"product pilot coverage references unknown cases: {missing}"
        )
    return {
        claim: all(by_name[name]["passed"] for name in names)
        for claim, names in PILOT_COVERAGE_REQUIREMENTS.items()
    }


def pilot(identity: dict[str, Any], output_dir: Path) -> int:
    results = [run_case(case, output_dir) for case in PILOT_CASES]
    coverage = pilot_coverage(results)
    passed = all(result["passed"] for result in results)
    receipt = {
        "schema": "hepta.kernel-authority-product-pilot.v1",
        "schemaVersion": 1,
        "candidate": identity,
        "scope": "repository-process-pilot",
        "fleetPathExecuted": coverage["fleetPathExecuted"],
        "browserAgentdPathExecuted": coverage["browserAgentdPathExecuted"],
        "restartRecoveryExercised": coverage["restartRecoveryExercised"],
        "revocationExercised": coverage["revocationExercised"],
        "snapshotRollbackExercised": coverage["snapshotRollbackExercised"],
        "keyRotationExercised": coverage["keyRotationExercised"],
        "durableReceiptExercised": coverage["durableReceiptExercised"],
        "passed": passed,
        "deploymentActivationProved": False,
        "productionTrustProved": False,
        "activationGranted": False,
        "releaseGranted": False,
        "cases": results,
    }
    write_json(output_dir / "product-pilot-receipt.json", receipt)
    return 0 if passed else 1'''
    text = text[:pilot_start] + pilot_functions + text[pilot_end:]
    path.write_text(text, encoding="utf-8")


def patch_runtime_tests() -> None:
    path = Path("qualification/kernel-authority/test_runtime_qualification.py")
    text = path.read_text(encoding="utf-8")
    class_anchor = "\n\nclass RuntimeQualificationReceiptTests(unittest.TestCase):\n"
    helper = r'''


def candidate_identity(mode: str = "exact-head") -> dict[str, object]:
    source = "a" * 40
    return {
        "schema": "hepta.kernel-authority-candidate.v1",
        "mode": mode,
        "sourceCommit": source,
        "baseCommit": "b" * 40,
        "candidateCommit": source if mode == "exact-head" else "c" * 40,
        "candidateTree": "d" * 40,
        "activationGranted": False,
        "releaseGranted": False,
    }
'''
    if "def candidate_identity(" not in text:
        if text.count(class_anchor) != 1:
            raise SystemExit("runtime qualification test helper anchor drifted")
        text = text.replace(class_anchor, helper + class_anchor, 1)

    method_anchor = (
        "    def test_benchmark_receipt_is_strict_and_rejects_slo_overclaim(self) -> None:\n"
    )
    methods = r'''    def test_exact_head_identity_cannot_rebind_a_different_commit(self) -> None:
        identity = candidate_identity()
        identity["candidateCommit"] = "c" * 40
        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.validate_candidate_structure(
                identity, lambda *_args: self.fail("git must not be consulted")
            )

    def test_synthetic_merge_identity_requires_exact_parent_order(self) -> None:
        identity = candidate_identity("synthetic-merge")
        source = str(identity["sourceCommit"])
        base = str(identity["baseCommit"])
        candidate = str(identity["candidateCommit"])
        tree = str(identity["candidateTree"])
        answers = {
            ("rev-parse", "--verify", f"{source}^{{commit}}"): source,
            ("rev-parse", "--verify", f"{base}^{{commit}}"): base,
            ("rev-parse", "--verify", f"{candidate}^{{commit}}"): candidate,
            ("rev-parse", "--verify", f"{tree}^{{tree}}"): tree,
            ("rev-list", "--parents", "-n", "1", candidate):
                f"{candidate} {source} {base}",
        }

        def fake_git(*args: str) -> str:
            return answers[args]

        with self.assertRaises(RUNTIME.QualificationError):
            RUNTIME.validate_candidate_structure(identity, fake_git)

    def test_pilot_claims_are_derived_from_named_passed_cases(self) -> None:
        results = [
            {"name": case.name, "passed": True}
            for case in RUNTIME.PILOT_CASES
        ]
        for result in results:
            if result["name"] == "issuer-key-overlap-and-retirement":
                result["passed"] = False
        coverage = RUNTIME.pilot_coverage(results)
        self.assertFalse(coverage["keyRotationExercised"])
        self.assertTrue(coverage["fleetPathExecuted"])

'''
    if "test_exact_head_identity_cannot_rebind_a_different_commit" not in text:
        if text.count(method_anchor) != 1:
            raise SystemExit("runtime qualification test method anchor drifted")
        text = text.replace(method_anchor, methods + method_anchor, 1)
    path.write_text(text, encoding="utf-8")


def add_main_and_schedule(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    branch = "      - work/kernel-authority-convergence-20260925\n"
    broad = "      - main\n" + branch
    if broad not in text:
        if text.count(branch) != 1:
            raise SystemExit(f"{path.name}: push branch anchor drifted")
        text = text.replace(branch, broad, 1)
    schedule = "  schedule:\n    - cron: '17 3 * * *'\n"
    if schedule not in text:
        dispatch = "  workflow_dispatch:\n"
        if text.count(dispatch) != 1:
            raise SystemExit(f"{path.name}: dispatch anchor drifted")
        text = text.replace(dispatch, schedule + dispatch, 1)
    path.write_text(text, encoding="utf-8")


def patch_workflows() -> None:
    workflow_root = Path(".github/workflows")
    for name in (
        "kernel-authority-convergence.yml",
        "kernel-authority-production-closure.yml",
        "kernel-authority-status.yml",
    ):
        add_main_and_schedule(workflow_root / name)

    convergence_path = workflow_root / "kernel-authority-convergence.yml"
    convergence = convergence_path.read_text(encoding="utf-8")
    single = "      - '.github/workflows/kernel-authority-convergence.yml'\n"
    all_paths = (
        single
        + "      - '.github/workflows/kernel-authority-production-closure.yml'\n"
        + "      - '.github/workflows/kernel-authority-status.yml'\n"
    )
    if all_paths not in convergence:
        if convergence.count(single) != 2:
            raise SystemExit("convergence workflow path anchors drifted")
        convergence = convergence.replace(single, all_paths)
    elif convergence.count(all_paths) != 2:
        raise SystemExit("convergence workflow coverage is incomplete")
    convergence_path.write_text(convergence, encoding="utf-8")

    production_path = workflow_root / "kernel-authority-production-closure.yml"
    production = production_path.read_text(encoding="utf-8")
    narrow = (
        "      - 'codex-rs/hepta-contracts/src/authority_trust.rs'\n"
        "      - 'codex-rs/hepta-contracts/src/authority_trust_tests.rs'\n"
        "      - 'codex-rs/hepta-contracts/tests/kernel_authority_benchmark.rs'\n"
    )
    broad = (
        "      - 'codex-rs/hepta-contracts/**'\n"
        "      - 'codex-rs/hepta-automation/**'\n"
        "      - 'codex-rs/hepta-prompt-registry/**'\n"
    )
    if broad not in production:
        if production.count(narrow) != 2:
            raise SystemExit("production closure source path anchors drifted")
        production = production.replace(narrow, broad)
    elif production.count(broad) != 2:
        raise SystemExit("production closure source coverage is incomplete")
    anchor = "      - 'docs/modules/kernel.authority/**'\n"
    extras = (
        anchor
        + "      - 'qa/b4-no-bypass/**'\n"
        + "      - 'CALLERS.toml'\n"
        + "      - 'scripts/kernel_authority_status.py'\n"
        + "      - 'scripts/hepta-implementation-maps.py'\n"
        + "      - 'scripts/verify_hepta_callers.py'\n"
    )
    if extras not in production:
        if production.count(anchor) != 2:
            raise SystemExit("production closure governance path anchors drifted")
        production = production.replace(anchor, extras)
    elif production.count(extras) != 2:
        raise SystemExit("production closure governance coverage is incomplete")
    production_path.write_text(production, encoding="utf-8")

    status_path = workflow_root / "kernel-authority-status.yml"
    status = status_path.read_text(encoding="utf-8")
    narrow = (
        "      - 'codex-rs/hepta-contracts/src/authority_trust.rs'\n"
        "      - 'codex-rs/hepta-contracts/src/authority_trust_tests.rs'\n"
        "      - 'codex-rs/hepta-contracts/tests/kernel_authority_benchmark.rs'\n"
        "      - 'codex-rs/hepta-fleet/src/authority_port.rs'\n"
        "      - 'codex-rs/hepta-agentd/src/authority_trust_host.rs'\n"
        "      - 'codex-rs/hepta-agentd/src/automation_effect_host.rs'\n"
        "      - 'codex-rs/hepta-agentd/src/browser_servo.rs'\n"
    )
    broad = (
        "      - 'codex-rs/hepta-contracts/**'\n"
        "      - 'codex-rs/hepta-fleet/**'\n"
        "      - 'codex-rs/hepta-agentd/**'\n"
        "      - 'codex-rs/hepta-automation/**'\n"
        "      - 'codex-rs/hepta-prompt-registry/**'\n"
    )
    if broad not in status:
        if status.count(narrow) != 2:
            raise SystemExit("status workflow source path anchors drifted")
        status = status.replace(narrow, broad)
    elif status.count(broad) != 2:
        raise SystemExit("status workflow source coverage is incomplete")
    status_path.write_text(status, encoding="utf-8")


def main() -> None:
    patch_authority_trust()
    patch_authority_trust_tests()
    patch_agentd()
    patch_extension_inventory()
    patch_runtime_qualification()
    patch_runtime_tests()
    patch_workflows()


if __name__ == "__main__":
    main()
