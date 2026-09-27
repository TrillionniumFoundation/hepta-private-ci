from pathlib import Path
r=Path(__file__).resolve().parents[1]
import hashlib
import subprocess
EXPECTED = {'apps/hepta-native/tests/runtime.rs': '9021766ef7018a270582b59d7521ef54e7f6220d74189f8e0c1f64c3c1a6e977', 'apps/hepta-native/tests/retirement_recovery.rs': '48e64291e060588a8fbda6ba3b7a11940785dd9d8097f936f4755a07b06d9c12', 'apps/hepta-native/src/ui.rs': '37ba37277d61ec8e080c960ea403feb8000adf7f6f4429f5c2b3688026efecae', 'apps/hepta-native/tools/prepare_current_source.py': '4bbfc3319b8f59a56cfebef382ea50aeaf22bed78350b1b2b33c3ba4beb44238', 'scripts/test_hepta_ui_native_source.py': '8dea43919eeb48bfc799ab2cbbd7f28fb2ee78a96c6f24950207e679443a503d', '.github/workflows/hepta-ui-native-remediation.yml': '37846ff759e84a34fbf8b032cf7f0b636d25be41d0748d9d1f25ac97876b31ce', '.github/workflows/hepta-ui-native-remediation-format.yml': '7a76e2a7c858364a64f7f2564d3019484fbd719e6e20c946e64879cab928cae4', 'docs/modules/ui.native/TECHNICAL.md': 'cda7a6e970bcf10aec4f7a8aacf6e7167ff8665a0c55a72b1862a93244188cf1', 'apps/hepta-native/DEVELOPMENT.md': 'e8123428a944ddafbb5abd8a5e5eb46d61524049a255c6f0955f089c0409d9fc', 'docs/modules/ui.native/REMEDIATION-20260927.md': 'bf3f396e5f2635fcd7df81a054e4e906ed954f20e5bb190f7a9679cbeaeaeefd'}
# This is a one-time materializer, not a product launch hook. Refuse semantic
# drift before writing anything; the workflow verifies the exact input commit.
for name, digest in EXPECTED.items():
    if hashlib.sha256((r/name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f"input differs from audited acceptance-repair baseline: {name}")
if (r/'docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md').exists():
    raise SystemExit("acceptance repair is already materialized")
p=r/'apps/hepta-native/tests/runtime.rs';s=p.read_text()
s=s.replace('fn retired_operation_identity_is_rejected_before_permission_or_dispatch()', 'fn retired_receipt_is_returned_without_permission_or_dispatch()')
s=s.replace('''    assert!(
        runtime
            .request_platform_capability(request.clone())
            .unwrap()
            .terminal_observed
    );
    runtime.compact_terminal_history(0).unwrap();
    let error = runtime.request_platform_capability(request).unwrap_err();
    assert!(error.to_string().contains("retirement frontier"));''','''    let original = runtime.request_platform_capability(request.clone()).unwrap();
    assert!(original.terminal_observed);
    runtime.compact_terminal_history(0).unwrap();
    render(&mut runtime, 2);
    assert_eq!(runtime.request_platform_capability(request.clone()).unwrap(), original);
    let mut drifted = request;
    drifted.payload = PlatformPayload::CopyText { text: "changed after retirement".to_owned() };
    assert!(runtime.request_platform_capability(drifted).is_err());''')
s=s.replace('''    runtime.compact_closed_history(0).unwrap();
    assert!(runtime.request_platform_capability(request).is_err());''','''    runtime.compact_closed_history(0).unwrap();
    assert_eq!(runtime.request_platform_capability(request).unwrap(), closed);''')
p.write_text(s)
p=r/'apps/hepta-native/tests/retirement_recovery.rs'
p.write_text(p.read_text()+'''
#[test]
fn archive_retains_unknown_receipt_across_restart_without_replay() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.archived");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    let closed = journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    let mut journal = OperationJournal::open(&path).unwrap();
    let archived = journal.archived_record(&record.endpoint_id, &record.key).unwrap().unwrap();
    assert_eq!(archived.receipt(), closed);
    assert_eq!(archived.phase, OperationPhase::ObservationClosed);
    assert!(archived.terminal_status.is_none());
    assert!(archived.outcome_digest.is_none());
    assert_eq!(journal.capacity().active_records, 0);
    assert!(journal.ensure_not_retired(&record.endpoint_id, &record.key).is_err());
    assert!(journal.upsert(record.clone()).is_err());
    assert!(journal.archived_record("other.endpoint", &record.key).unwrap().is_none());
}

#[test]
fn missing_or_modified_archive_never_becomes_a_new_operation() {
    for corrupt in [false, true] {
        let temp = private_tempdir();
        let path = temp.path().join("operations.json");
        let record = unknown("operation.archive-integrity");
        let mut journal = OperationJournal::open(&path).unwrap();
        journal.upsert(record.clone()).unwrap();
        journal.close_observation(&record.key).unwrap();
        journal.compact_closed_history(0).unwrap();
        drop(journal);
        let archived = std::fs::read_dir(temp.path().join("operations.json.retirement"))
            .unwrap().map(|entry| entry.unwrap().path())
            .find(|path| path.file_name().unwrap().to_string_lossy().starts_with("record-"))
            .unwrap();
        if corrupt { std::fs::write(archived, b"{}").unwrap(); }
        else { std::fs::remove_file(archived).unwrap(); }
        let mut journal = OperationJournal::open(&path).unwrap();
        assert!(journal.archived_record(&record.endpoint_id, &record.key).is_err());
        assert!(journal.ensure_not_retired(&record.endpoint_id, &record.key).is_err());
        assert!(journal.upsert(record).is_err());
    }
}

#[test]
fn retirement_failure_keeps_active_evidence_and_fences_the_owner() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.archive-fault");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    let closed = journal.find(&record.key).unwrap().clone();
    let directory = temp.path().join("operations.json.retirement");
    hepta_native::private_state::PrivateStateRoot::open(directory.clone()).unwrap();
    // A complete empty head is followed by a conflicting immutable record path.
    let head = serde_json::json!({"schema":"hepta.native-retirement.v1", "checkpoint":{"head":null,"count":0}});
    std::fs::write(directory.join("head.json"), serde_json::to_vec(&head).unwrap()).unwrap();
    let digest = sha256_hex(serde_json::to_vec(&closed).unwrap());
    std::fs::create_dir(directory.join(format!("record-{digest}.json"))).unwrap();
    assert!(journal.compact_closed_history(0).is_err());
    assert!(journal.ensure_healthy().is_err());
    assert_eq!(journal.find(&record.key), Some(&closed));
    drop(journal);
    let journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.find(&record.key), Some(&closed));
    assert_eq!(journal.retired_count(), 0);
}

#[test]
fn repeated_restart_compaction_keeps_old_receipts_and_reclaims_capacity() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    for cycle in 0..3 {
        let mut journal = OperationJournal::open(&path).unwrap();
        for index in 0..24 {
            let record = unknown(&format!("operation.{cycle}.{index}"));
            journal.upsert(record.clone()).unwrap();
            journal.close_observation(&record.key).unwrap();
        }
        journal.compact_closed_history(0).unwrap();
        assert_eq!(journal.capacity().active_records, 0);
        assert_eq!(journal.retired_count(), (cycle + 1) * 24);
    }
    let journal = OperationJournal::open(&path).unwrap();
    for cycle in 0..3 {
        for index in 0..24 {
            let record = unknown(&format!("operation.{cycle}.{index}"));
            let archived = journal.archived_record(&record.endpoint_id, &record.key).unwrap().unwrap();
            assert!(archived.receipt().observation_closed);
            assert!(!archived.receipt().terminal_observed);
        }
    }
}
''')
# A direct, user-triggered history action also works for terminal-only workloads.
p=r/'apps/hepta-native/src/ui.rs';s=p.read_text()
s=s.replace('''        if self.operations.is_empty() {
            ui.label(self.locale.text("No operation receipts.", "暂无操作回执。"));''','''        if ui.add_enabled(!busy, egui::Button::new(self.locale.text(
            "Archive closed history (retain last 256)", "归档已结案历史（保留最近 256 条）",
        ))).clicked() {
            let runtime = Arc::clone(&self.runtime);
            self.start_task(UiTaskKind::Reconcile, move || {
                let mut runtime = lock_runtime(&runtime)?;
                runtime.compact_closed_history(256)?;
                Ok(UiTaskOutput::Reconcile { operations: runtime.operation_history() })
            });
        }
        if self.operations.is_empty() {
            ui.label(self.locale.text("No operation receipts.", "暂无操作回执。"));''')
s=s.replace('// Retirement preserves the identity, not a fabricated outcome.', '// Retirement preserves the full closed record, not a fabricated outcome.')
s=s.replace('''            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                ui.label(self.locale.text("Absolute path", "绝对路径"));''','''            PlatformAction::OpenPath | PlatformAction::RevealPath => {
                ui.label(self.locale.text(
                    "Unavailable: verified OS resource handoff is not implemented. No path operation will be dispatched.",
                    "当前不可用：尚未实现已验证资源的 OS 句柄交付；不会派发路径操作。",
                ));
                ui.label(self.locale.text("Absolute path", "绝对路径"));''')
p.write_text(s)
branch='work/ui-native-acceptance-repair-20260927'
p=r/'apps/hepta-native/tools/prepare_current_source.py';s=p.read_text()
s=s.replace('BRANCH = "work/ui-native-verified-closure-20260927"', f'BRANCH = "{branch}"')
s=s.replace('WRITE_BRANCHES = {', 'WRITE_BRANCHES = {"work/ui-native-verified-closure-20260927", ')
s=s.replace('    ROOT / "CALLERS.toml",','''    ROOT / "CALLERS.toml",
    ROOT / "docs/modules/ui.native/TECHNICAL.md",
    ROOT / "docs/modules/ui.native/REMEDIATION-20260927.md",
    ROOT / "docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md",
    ROOT / "docs/modules/ui.native/CURRENT_SOURCE.json",''')
s=s.replace('''                or manifest.get("productionQualified") is not False''', '''                or manifest.get("canonicalBranch") != BRANCH
                or manifest.get("productionQualified") is not False''')
p.write_text(s)
p=r/'scripts/test_hepta_ui_native_source.py'
s=p.read_text().replace('    def test_unregistered_write_branch_refused(self):','''    def test_stale_candidate_branch_is_rejected(self):
        path = self.app / 'CURRENT_SOURCE.json'
        data = json.loads(path.read_text())
        data['canonicalBranch'] = 'work/stale-candidate'
        path.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError): self.check()

    def test_unregistered_write_branch_refused(self):''')
p.write_text(s)
for filename in ['.github/workflows/hepta-ui-native-remediation.yml','.github/workflows/hepta-ui-native-remediation-format.yml']:
    p=r/filename;s=p.read_text().replace('branches: [', f'branches: [{branch}, ')
    p.write_text(s)
for rel in ['docs/modules/ui.native/TECHNICAL.md','apps/hepta-native/DEVELOPMENT.md','docs/modules/ui.native/REMEDIATION-20260927.md']:
    p=r/rel;s=p.read_text();a=s.index('\n')
    pointer = '../../docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md' if rel.startswith('apps/') else 'ACCEPTANCE-REPAIR-20260927.md'
    s=s[:a+1]+f'''\nCurrent candidate: `{branch}`, continuing #1107 at
`43da94c5fa48675a3e0956a80fac201fa3ce8b34`. See [current acceptance ledger]({pointer}).
The authoritative source inventory is `apps/hepta-native/CURRENT_SOURCE.json`;
CI receipts bind the actual tested HEAD and pinned-main merge separately.
No queued, skipped, source-only, or historical result is a qualification pass.\n'''+s[a+1:]
    p.write_text(s)
p=r/'docs/modules/ui.native/CURRENT_SOURCE.json'
p.write_text('''{
  "schema": "hepta.ui.native.source-navigation.v1",
  "authoritativeInventory": "apps/hepta-native/CURRENT_SOURCE.json",
  "currentLedger": "docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md",
  "validationAuthority": "same-run same-attempt exact-head and pinned-main merge qualification receipts",
  "qualificationClaim": false,
  "releaseAuthorized": false
}
''')
p=r/'docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md'
p.write_text(f'''# ui.native acceptance repair — 2026-09-27

## Current candidate and provenance

The single candidate advanced here is `{branch}`. It directly continues
`work/ui-native-full-closure-20260927` (#1107), source HEAD
`43da94c5fa48675a3e0956a80fac201fa3ce8b34`, tree
`fc16515c91608c37bd6e85af8aaa1e7eadc7eecd`. No unrelated module branch is updated.
The pinned integration main is `a126987b84737dbc2ee2592442a314117bddb4a2`.
`apps/hepta-native/CURRENT_SOURCE.json` is the one generated source inventory.
`docs/modules/ui.native/CURRENT_SOURCE.json` is navigation, not a competing status database.
Implementation-map anchors name an already committed source tree, not the future
metadata commit. Qualification receipts always name the actual tested SHA/tree.

## Implemented changes

Full closed operation records now survive compaction. A record is serialized and
written to a content-addressed immutable file before its hash and operation identity
are published in a v2 retirement segment, before the chain head, before active journal
replacement. The head hash transitively binds each archived record. Ordinary checksums
are corruption detection, not a signature, a trusted anti-rollback frontier, or protection
against an attacker able to replace all private state.

A repeated identical request returns its original archived terminal/unknown-closed
receipt without authority claim, permission interaction, or platform dispatch. The
subject, endpoint/session, action, payload, view revision and exact signed-grant digest
must still match. A different payload or grant conflicts. Reading a historical receipt
is not permission for a new effect and does not require a fresh displayed view.

Legacy v1 retirement segments and v2–v6 journals remain readable. Previously retired
identity-only entries cannot be reconstructed: they remain replay-fenced and do not
produce invented receipts. New v2 segments can reference old segments without rewriting
history. Missing/corrupt referenced records make historical lookup fail, never create a
fresh operation. An ahead retirement head reconciles only identical closed records;
active-record/archive disagreement fails closed. Orphan record files have no authority.

The UI offers explicit closed-history compaction for terminal-only workloads as well
as unknown-observation closure. Unknown means unknown after archiving. There is no
ordinary replay/retry action. A journal-clear operation is not recovery. OpenPath and
RevealPath remain explicitly unavailable in the system adapter until an OS API consumes
the verified resource capability; tests now match this inherited security restriction.
The unused path snapshot research module is test-only, not claimed as production handoff.

## Durability order and failure handling

1. Write and sync each immutable record; validate existing bytes on an idempotent write.
2. Write bounded content-addressed segment(s) including identity-to-record-digest links.
3. Atomically publish and sync the retirement head.
4. Atomically replace the active journal using the new checkpoint.

Any write error fences the current journal owner. A restart may recover the old or new
complete head. Published retirements forbid dispatch even when the active journal has
not yet been replaced. Orphan files never authorize replay or manufacture evidence.
The live journal remains bounded; retired index memory and restart scan still grow with
history. A disk index and measured compaction policy remain performance work, not an
unbounded-memory production claim.

## Regression scope

Tests cover preserved unknown receipts across restart; semantic drift after terminal
retirement; no dispatch or reconciliation when returning an archived receipt; missing
and modified archive records; failed record publication and owner fencing; repeated
restart/compaction; old identity-only migration; source candidate mismatch; and path
operations remaining unavailable before/after replacement. Existing view, revocation,
receipt-write-failure and ahead-head tests are retained.

## Validation ledger

Local Python test results are reported in the execution handoff, with retained raw logs.
No local Rust compiler is available in the editing environment. Rust test declarations,
manual static review, and Python validation do not count as native test passes.
The formatter workflow produces an immutable proposal; it must not push to a moving
candidate. The previous live-branch rebind workflow is removed from this continuation.
The six existing qualification subjects remain mandatory: Linux/macOS/Windows, each
at exact head and the fixed main merge. The workflow still fails on missing, skipped,
cancelled, or unsuccessful subjects; formatting, lint and native tests are not relaxed.

Phase A remains pending until those actual candidate receipts pass. Phase B has concrete
implementation and regression additions, but path capability handoff is not implemented
and native execution has not been claimed. Phase C remains unqualified: real installed
macOS/Windows/Linux behavior, signed packages, notarization, update/rollback/key rotation,
IME/DPI/screen-reader acceptance, long-run installed performance, and independent release
approval require real external observations. No signing keys or production policies are
changed. The existing performance plan must be run on identified installed artifacts;
no measurements, signatures, or physical-host results are synthesized by this change.
''')

# Do not retain a workflow that rewrites the shared predecessor branch.
(r/'.github/workflows/ui-native-candidate-rebind.yml').unlink()
