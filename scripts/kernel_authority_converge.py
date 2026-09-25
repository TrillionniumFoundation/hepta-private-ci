#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}")
    write(path, text.replace(old, new, 1))


def patch_authority_lease() -> None:
    path = "codex-rs/hepta-contracts/src/authority_lease.rs"
    replace_once(
        path,
        '''            Some(current) => {
                if current == &lease {
                    return Ok(AuthorityLeaseReadV1 {
                        lease,
                        store_revision: state.store_revision,
                    });
                }
                if current.revision != expected_revision
                    || lease.revision != expected_revision.saturating_add(1)
                {
                    return Err(AuthorityLeaseError::RevisionMismatch);
                }
            }
''',
        '''            Some(current) => {
                let next_expected_revision = next_revision(expected_revision)?;
                if current == &lease {
                    if lease.revision != next_expected_revision {
                        return Err(AuthorityLeaseError::RevisionMismatch);
                    }
                    return Ok(AuthorityLeaseReadV1 {
                        lease,
                        store_revision: state.store_revision,
                    });
                }
                if current.revision != expected_revision
                    || lease.revision != next_expected_revision
                {
                    return Err(AuthorityLeaseError::RevisionMismatch);
                }
            }
''',
    )
    replace_once(
        path,
        '''        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let state = self.lock_state()?;
        let lease = state
''',
        '''        let state = self.lock_state()?;
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let lease = state
''',
    )
    text = read(path)
    old = '''        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let state = self.lock_state()?;
        validate_live(
'''
    new = '''        let state = self.lock_state()?;
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        validate_live(
'''
    if old in text:
        if text.count(old) != 2:
            raise RuntimeError(f"{path}: expected two final-use clock-order replacements")
        text = text.replace(old, new, 2)
        write(path, text)
    replace_once(
        path,
        '''    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::mpsc;
''',
        '''    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::sync::mpsc;
''',
    )
    replace_once(
        path,
        '''    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0)
        }
    }
''',
        '''    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0)
        }
    }

    #[derive(Debug)]
    struct ObservableClock {
        now_unix_ms: AtomicU64,
        observer: Mutex<Option<mpsc::Sender<u64>>>,
    }

    impl ObservableClock {
        fn new(now_unix_ms: u64) -> Self {
            Self {
                now_unix_ms: AtomicU64::new(now_unix_ms),
                observer: Mutex::new(None),
            }
        }

        fn set(&self, now_unix_ms: u64) {
            self.now_unix_ms.store(now_unix_ms, Ordering::SeqCst);
        }

        fn observe_with(&self, observer: mpsc::Sender<u64>) {
            *self.observer.lock().unwrap() = Some(observer);
        }
    }

    impl AuthorityClock for ObservableClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            let now_unix_ms = self.now_unix_ms.load(Ordering::SeqCst);
            if let Some(observer) = self.observer.lock().unwrap().as_ref() {
                let _ = observer.send(now_unix_ms);
            }
            Ok(now_unix_ms)
        }
    }
''',
    )
    marker = '''    #[test]
    fn stale_cas_and_binding_drift_fail_closed() {
'''
    tests = '''    fn lease_expiring_while_waiting_for_owner_lock(
        dispatch_boundary: bool,
    ) -> Result<(), AuthorityLeaseError> {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let clock = Arc::new(ObservableClock::new(2_000));
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            directory.path(),
            "security-authority".into(),
            AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
            clock.clone(),
        )
        .unwrap();
        let mut expiring = lease();
        expiring.expires_at_unix_ms = 3_000;
        registry.put_lease(expiring, 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier.verify_use("lease-one", 1, &binding()).unwrap();

        let owner = Arc::clone(&verifier.0);
        let owner_lock = owner.state.lock().unwrap();
        let (clock_tx, clock_rx) = mpsc::channel();
        clock.observe_with(clock_tx);
        let (started_tx, started_rx) = mpsc::channel();
        let expected = binding();
        let worker = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            if dispatch_boundary {
                verifier.with_dispatch_boundary(token, &expected, || ())
            } else {
                verifier.with_verified_use(token, &expected, || ())
            }
        });
        started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let sampled_before_lock = clock_rx.recv_timeout(Duration::from_millis(500)).ok();
        clock.set(4_000);
        drop(owner_lock);
        if sampled_before_lock.is_none() {
            assert_eq!(clock_rx.recv_timeout(Duration::from_secs(2)).unwrap(), 4_000);
        }
        worker.join().unwrap()
    }

    #[test]
    fn identical_lease_retry_requires_the_original_predecessor_revision() {
        let (registry, _directory) = fixture();
        let original = lease();
        registry.put_lease(original.clone(), 0).unwrap();
        assert_eq!(
            registry.put_lease(original.clone(), 1).unwrap_err(),
            AuthorityLeaseError::RevisionMismatch
        );
        registry.put_lease(original, 0).unwrap();

        let mut replacement = lease();
        replacement.revision = 2;
        replacement.expires_at_unix_ms = 40_000;
        registry.put_lease(replacement.clone(), 1).unwrap();
        assert_eq!(
            registry.put_lease(replacement.clone(), 2).unwrap_err(),
            AuthorityLeaseError::RevisionMismatch
        );
        registry.put_lease(replacement, 1).unwrap();
    }

    #[test]
    fn verified_use_rechecks_expiry_after_waiting_for_owner_lock() {
        assert_eq!(
            lease_expiring_while_waiting_for_owner_lock(false),
            Err(AuthorityLeaseError::Expired)
        );
    }

    #[test]
    fn dispatch_boundary_rechecks_expiry_after_waiting_for_owner_lock() {
        assert_eq!(
            lease_expiring_while_waiting_for_owner_lock(true),
            Err(AuthorityLeaseError::Expired)
        );
    }

'''
    text = read(path)
    if "identical_lease_retry_requires_the_original_predecessor_revision" not in text:
        if text.count(marker) != 1:
            raise RuntimeError(f"{path}: missing test insertion marker")
        write(path, text.replace(marker, tests + marker, 1))


def patch_final_use_revocation_progress() -> None:
    path = "codex-rs/hepta-contracts/src/final_use.rs"
    replace_once(path, "use std::sync::atomic::AtomicUsize;\n", "use std::sync::atomic::AtomicBool;\nuse std::sync::atomic::AtomicUsize;\n")
    replace_once(
        path,
        '''    active_dispatches: AtomicUsize,
    store: store::Store,
''',
        '''    active_dispatches: AtomicUsize,
    revocation_pending: AtomicBool,
    store: store::Store,
''',
    )
    text = read(path)
    old = '''            active_dispatches: AtomicUsize::new(0),
            store,
'''
    new = '''            active_dispatches: AtomicUsize::new(0),
            revocation_pending: AtomicBool::new(false),
            store,
'''
    if old in text:
        if text.count(old) != 3:
            raise RuntimeError(f"{path}: expected three constructors")
        write(path, text.replace(old, new, 3))
    replace_once(
        path,
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.owner.clock.now_unix_ms().map_err(map_trust_error)?;
''',
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if self.owner.revocation_pending.load(Ordering::Acquire) {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = self.owner.clock.now_unix_ms().map_err(map_trust_error)?;
''',
    )
    replace_once(
        path,
        '''        if self.0.active_dispatches.load(Ordering::Acquire) != 0 {
            return Err(FinalUseError::DispatchInProgress);
        }
        let mut next = state.clone();
        if head.authority_epoch > next.head.authority_epoch {
            next.used_nonces.clear();
        }
        next.head = head;
        self.persist_or_fence(&mut state, next)
''',
        '''        if self.0.active_dispatches.load(Ordering::Acquire) != 0 {
            self.0.revocation_pending.store(true, Ordering::Release);
            return Err(FinalUseError::DispatchInProgress);
        }
        let mut next = state.clone();
        if head.authority_epoch > next.head.authority_epoch {
            next.used_nonces.clear();
        }
        next.head = head;
        self.persist_or_fence(&mut state, next)?;
        self.0.revocation_pending.store(false, Ordering::Release);
        Ok(())
''',
    )
    replace_once(
        path,
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&signed.grant, &state.head, now_unix_ms)?;
''',
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if self.0.revocation_pending.load(Ordering::Acquire) {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&signed.grant, &state.head, now_unix_ms)?;
''',
    )
    replace_once(
        path,
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        validate_live(&token.grant, &state.head, self.now_unix_ms()?)?;
        self.0.active_dispatches.fetch_add(1, Ordering::AcqRel);
''',
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if self.0.revocation_pending.load(Ordering::Acquire) {
            return Err(FinalUseError::RevocationPending);
        }
        validate_live(&token.grant, &state.head, self.now_unix_ms()?)?;
        self.0.active_dispatches.fetch_add(1, Ordering::AcqRel);
''',
    )
    replace_once(
        path,
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&token.grant, &state.head, now_unix_ms)?;
        Ok(VerifiedUseTokenWitnessV1::final_use(
''',
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if self.0.revocation_pending.load(Ordering::Acquire) {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&token.grant, &state.head, now_unix_ms)?;
        Ok(VerifiedUseTokenWitnessV1::final_use(
''',
    )
    replace_once(
        path,
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&token.grant, &state.head, now_unix_ms)?;
        let witness = VerifiedUseTokenWitnessV1::final_use(
''',
        '''        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if self.0.revocation_pending.load(Ordering::Acquire) {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&token.grant, &state.head, now_unix_ms)?;
        let witness = VerifiedUseTokenWitnessV1::final_use(
''',
    )
    replace_once(path, "    DispatchInProgress,\n    Unavailable,\n", "    DispatchInProgress,\n    RevocationPending,\n    Unavailable,\n")

    tests_path = "codex-rs/hepta-contracts/src/final_use_tests.rs"
    replace_once(
        tests_path,
        '''fn async_final_use_fence_survives_pending_and_releases_on_cancellation() {
    let (authority, signed, _directory) = fixture().unwrap();
    let binding = signed.grant.binding.clone();
    let token = authority.claim(&signed, &binding).unwrap();
    let mut future = Box::pin(
''',
        '''fn async_final_use_fence_survives_pending_and_releases_on_cancellation() {
    let (authority, signed, _directory) = fixture().unwrap();
    let binding = signed.grant.binding.clone();
    let token = authority.claim(&signed, &binding).unwrap();
    let mut later = signed.clone();
    later.grant.grant_id = "read-after-pending-revocation".into();
    later.grant.nonce = [91; 32];
    later.signature = SigningKey::from_bytes(&[47; 32])
        .sign(&later.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let mut future = Box::pin(
''',
    )
    replace_once(
        tests_path,
        '''        Err(FinalUseError::DispatchInProgress)
    );

    drop(future);
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id]),
        })
        .unwrap();
}
''',
        '''        Err(FinalUseError::DispatchInProgress)
    );
    assert_eq!(
        authority.claim(&later, &binding).unwrap_err(),
        FinalUseError::RevocationPending,
        "a pending newer head must stop new admission rather than permit starvation"
    );

    drop(future);
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id]),
        })
        .unwrap();
    authority
        .claim(&later, &binding)
        .expect("successful revocation retry clears the admission fence");
}
''',
    )


def set_toml_boundary(text: str, boundary_id: str, callers: list[str], markers: list[str], *, call_pattern: str | None = None) -> str:
    match = re.search(rf'(?ms)^\[\[boundary\]\]\nid = "{re.escape(boundary_id)}"\n.*?(?=^\[\[boundary\]\]|\Z)', text)
    if match is None:
        raise RuntimeError(f"CALLERS.toml: missing {boundary_id}")
    block = match.group(0).rstrip()
    block = re.sub(r'^product_callers = \[[^\n]*\]$', "product_callers = [" + ", ".join(json.dumps(value) for value in callers) + "]", block, flags=re.M)
    block = re.sub(r'^caller_markers = \[[^\n]*\]$', "caller_markers = [" + ", ".join(json.dumps(value) for value in markers) + "]", block, flags=re.M)
    if call_pattern is not None:
        if re.search(r'^call_pattern = ', block, flags=re.M):
            block = re.sub(r'^call_pattern = .*$', f"call_pattern = {json.dumps(call_pattern)}", block, flags=re.M)
        else:
            block = block.replace(f'id = "{boundary_id}"\n', f'id = "{boundary_id}"\ncall_pattern = {json.dumps(call_pattern)}\n', 1)
    return text[: match.start()] + block + "\n\n" + text[match.end() :].lstrip("\n")


def append_toml_boundary(text: str, boundary_id: str, block: str) -> str:
    if f'id = "{boundary_id}"' in text:
        return text
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def patch_callers_and_b4() -> None:
    callers_path = "CALLERS.toml"
    text = read(callers_path)
    required = [
        "final_use_guarded_effect",
        "final_use_async_dispatch_fence",
        "final_use_async_entry",
        "bao_authbus_final_use_consumer",
    ]
    for boundary_id in required:
        if f'  "{boundary_id}",\n' not in text:
            text = text.replace('  "automation_taskflow_provider_effect_bridge",\n', f'  "{boundary_id}",\n  "automation_taskflow_provider_effect_bridge",\n', 1)
    text = set_toml_boundary(
        text,
        "final_use_open_state",
        [
            "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
        ],
        ["FinalUseAuthority::open_state_dir", "FinalUseAuthority", "authority"],
    )
    text = set_toml_boundary(
        text,
        "final_use_claim_raw",
        [
            "codex-rs/hepta-automation/src/authorized_effect.rs",
            "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
            "codex-rs/hepta-memory/src/production_writer.rs",
            "codex-rs/hepta-ndu/src/owner.rs",
            "codex-rs/hepta-operations/src/durable_store.rs",
            "codex-rs/hepta-prompt-registry/src/admission.rs",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "codex-rs/hepta-runtime/src/organs.rs",
        ],
        ["FinalUseAuthority", ".claim(", "FinalUseBinding"],
    )
    text = set_toml_boundary(
        text,
        "final_use_delivery_raw",
        [
            "codex-rs/hepta-memory/src/production_writer.rs",
            "codex-rs/hepta-ndu/src/owner.rs",
            "codex-rs/hepta-operations/src/durable_store.rs",
            "codex-rs/hepta-prompt-registry/src/admission.rs",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "codex-rs/hepta-runtime/src/organs.rs",
        ],
        ["FinalUseAuthority", "with_verified_use", "FinalUseBinding"],
    )
    text = set_toml_boundary(
        text,
        "final_use_revocation_update",
        [
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "codex-rs/hepta-contracts/src/final_use_control.rs",
            "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
        ],
        ["FinalUseAuthority", "update_revocations", "FinalUseRevocations"],
    )
    text = set_toml_boundary(
        text,
        "final_use_async_dispatch_fence",
        ["codex-rs/hepta-automation/src/authorized_effect.rs"],
        ["with_verified_use_async", "driver.dispatch(request)", "expected_binding"],
        call_pattern=r"authority\s*\.\s*with_verified_use_async\s*\(",
    )
    text = append_toml_boundary(
        text,
        "final_use_async_entry",
        '''[[boundary]]
id = "final_use_async_entry"
symbol = "VerifiedUseToken::enter / FinalUseAuthority::enter_verified_use"
definition_path = "codex-rs/hepta-contracts/src/final_use.rs"
definition_markers = ["pub fn enter(self", "pub fn enter_verified_use(", "StaleRevocationHead"]
product_callers = ["codex-rs/hepta-infer-worker-host/src/native_app_server.rs"]
caller_markers = ["VerifiedUseToken", "verified_use.enter", "EnteredUseToken"]''',
    )
    text = append_toml_boundary(
        text,
        "bao_authbus_final_use_consumer",
        '''[[boundary]]
id = "bao_authbus_final_use_consumer"
symbol = "BaoClient::consume_kv_v2_with_authbus"
call_pattern = '\\.\\s*consume_kv_v2_with_authbus\\s*\\('
definition_path = "codex-rs/hepta-bao-adapter/src/https_consumer.rs"
definition_markers = ["pub async fn consume_kv_v2_with_authbus", "mark_dispatch_attempted", "consume_kv_v2(authority"]
product_callers = []
caller_markers = []''',
    )
    write(callers_path, text)

    b4_path = "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
    data = json.loads(read(b4_path))
    types = {row["typeName"]: row for row in data["types"]}
    final_use = types["FinalUseAuthority"]
    final_use["privilegedMethods"]["enter_verified_use"] = "final_use_async_entry"
    if "revocation_head" not in final_use["nonPrivilegedMethods"]:
        final_use["nonPrivilegedMethods"].append("revocation_head")
    if "VerifiedUseToken" not in types:
        insert_at = next(i for i, row in enumerate(data["types"]) if row["typeName"] == "AuthorityLeaseRegistry")
        data["types"][insert_at:insert_at] = [
            {
                "typeName": "VerifiedUseToken",
                "sourcePath": "codex-rs/hepta-contracts/src/final_use.rs",
                "privilegedMethods": {"enter": "final_use_async_entry"},
                "nonPrivilegedMethods": ["witness_sha256", "claimed_authority_epoch", "claimed_revocation_revision", "claimed_revocation_head_sha256"],
            },
            {
                "typeName": "EnteredUseToken",
                "sourcePath": "codex-rs/hepta-contracts/src/final_use.rs",
                "privilegedMethods": {},
                "nonPrivilegedMethods": ["matches", "witness_sha256"],
            },
        ]
    bao = types["BaoClient"]
    bao["privilegedMethods"]["consume_kv_v2_with_authbus"] = "bao_authbus_final_use_consumer"
    if "authbus_effect_digest" not in bao["nonPrivilegedMethods"]:
        bao["nonPrivilegedMethods"].append("authbus_effect_digest")

    boundaries = {row["id"]: row for row in data["boundaries"]}
    boundaries["final_use_open_state"]["callPatterns"] = [
        r"FinalUseAuthority\s*::\s*open_state_dir\s*\(",
        r"FinalUseAuthority\s*::\s*open_state_dir_with_clock\s*\(",
        r"FinalUseAuthority\s*::\s*open_state_dir_with_trust\s*\(",
        r"FinalUseAuthority\s*::\s*open_state_dir_with_issuer_keys\s*\(",
    ]
    boundaries["final_use_open_state"]["allowedCallers"] = [
        "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
        "codex-rs/hepta-agentd/src/automation_effect_host.rs",
        "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    ]
    boundaries["final_use_claim_raw"]["allowedCallers"] = [
        "codex-rs/hepta-automation/src/authorized_effect.rs",
        "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
        "codex-rs/hepta-memory/src/production_writer.rs",
        "codex-rs/hepta-ndu/src/owner.rs",
        "codex-rs/hepta-operations/src/durable_store.rs",
        "codex-rs/hepta-prompt-registry/src/admission.rs",
        "codex-rs/hepta-prompt-registry/src/durable.rs",
        "codex-rs/hepta-runtime/src/organs.rs",
    ]
    boundaries["final_use_delivery_raw"]["allowedCallers"] = [
        "codex-rs/hepta-memory/src/production_writer.rs",
        "codex-rs/hepta-ndu/src/owner.rs",
        "codex-rs/hepta-operations/src/durable_store.rs",
        "codex-rs/hepta-prompt-registry/src/admission.rs",
        "codex-rs/hepta-prompt-registry/src/durable.rs",
        "codex-rs/hepta-runtime/src/organs.rs",
    ]
    boundaries["final_use_revocation_update"]["allowedCallers"] = [
        "codex-rs/hepta-agentd/src/automation_effect_host.rs",
        "codex-rs/hepta-contracts/src/final_use_control.rs",
        "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    ]
    boundaries["authority_lease_delivery"]["allowedCallers"] = []
    for boundary_id, patterns in {
        "final_use_revocation_convergence_trust": [r"FinalUseRevocationConvergenceVerifier\s*::\s*new\s*\("],
        "final_use_revocation_convergence_verify": [r"convergence_verifier\s*\.\s*verify\s*\(", r"FinalUseRevocationConvergenceVerifier\s*::\s*verify\s*\("],
    }.items():
        boundaries[boundary_id]["callPatterns"] = patterns

    additions = [
        {
            "id": "final_use_guarded_effect",
            "typeMarker": "FinalUseAuthority",
            "definitionPath": "codex-rs/hepta-contracts/src/final_use.rs",
            "callPatterns": [r"\.\s*with_verified_effect\s*\(", r"FinalUseAuthority\s*::\s*with_verified_effect\s*\("],
            "allowedCallers": ["codex-rs/hepta-automation/src/authorized_effect.rs"],
        },
        {
            "id": "final_use_async_dispatch_fence",
            "typeMarker": "FinalUseAuthority",
            "definitionPath": "codex-rs/hepta-contracts/src/final_use.rs",
            "callPatterns": [r"\.\s*with_verified_use_async\s*\(", r"FinalUseAuthority\s*::\s*with_verified_use_async\s*\("],
            "allowedCallers": ["codex-rs/hepta-automation/src/authorized_effect.rs"],
        },
        {
            "id": "final_use_async_entry",
            "typeMarker": "VerifiedUseToken",
            "definitionPath": "codex-rs/hepta-contracts/src/final_use.rs",
            "callPatterns": [r"\bverified_use\s*\.\s*enter\s*\(", r"\btoken\s*\.\s*enter\s*\(", r"\.\s*enter_verified_use\s*\(", r"VerifiedUseToken\s*::\s*enter\s*\(", r"FinalUseAuthority\s*::\s*enter_verified_use\s*\("],
            "allowedCallers": ["codex-rs/hepta-infer-worker-host/src/native_app_server.rs"],
        },
        {
            "id": "bao_authbus_final_use_consumer",
            "typeMarker": "BaoClient",
            "definitionPath": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
            "callPatterns": [r"\.\s*consume_kv_v2_with_authbus\s*\(", r"BaoClient\s*::\s*consume_kv_v2_with_authbus\s*\("],
            "allowedCallers": [],
        },
    ]
    known = {row["id"] for row in data["boundaries"]}
    for row in additions:
        if row["id"] not in known:
            data["boundaries"].append(row)
    write(b4_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    scanner = "qa/b4-no-bypass/test_kernel_authority_closed_world.py"
    text = read(scanner)
    text = text.replace(r'\bpub\s+(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)', r'\bpub\s+(?:(?:async|const)\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)')
    write(scanner, text)


def main() -> int:
    patch_authority_lease()
    patch_final_use_revocation_progress()
    patch_callers_and_b4()
    print("kernel.authority source/caller convergence patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
