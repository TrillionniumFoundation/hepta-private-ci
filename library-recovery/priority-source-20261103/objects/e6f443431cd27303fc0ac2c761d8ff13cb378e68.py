from pathlib import Path
import difflib,re,shutil
R=Path(__file__).parent
C=R/'current'
B=R/'base'
def patch(name, before):
 text=''
 for path,old in before.items():
  new=(C/path).read_text()
  if old==new:continue
  text+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path if old else '/dev/null',tofile='b/'+path))
 (R/'patches'/name).write_text(text)
p='codex-rs/hepta-memory/src/production_cognitive_source_target.rs'
t='codex-rs/hepta-memory/src/production_cognitive_source_target_tests.rs'
s=(C/p).read_text();before={p:s,t:(C/t).read_text()}
a=s.index('    async fn terminal_proof(\n');b=s.index('    async fn terminal_proof_tx(',a);s=s[:a]+s[b:]
s=s.replace('        draft: &SourceDraft,\n        source_id: &SourceEventId,\n    ) -> Result<i64, sqlx::Error>', '        transaction: &mut sqlx::Transaction<\'_, sqlx::Sqlite>,\n        draft: &SourceDraft,\n        source_id: &SourceEventId,\n    ) -> Result<i64, sqlx::Error>')
s=s.replace('.fetch_one(&self.store.pool)\n        .await\n    }\n\n    pub async fn observe_terminal', '.fetch_one(&mut **transaction)\n        .await\n    }\n\n    pub async fn observe_terminal')
s=s.replace('        match self.terminal_proof(request).await {', '''        // An exact commit between separate exact-row and identity probes
        // must not turn an applied operation into a false semantic conflict.
        let mut transaction = match self.store.pool.begin().await {
            Ok(transaction) => transaction,
            Err(error) => {
                return CognitiveSourceTerminalObservation::Unavailable {
                    reason: error.to_string(),
                };
            }
        };
        let observation = self
            .observe_terminal_snapshot(&mut transaction, request, &draft)
            .await;
        if let Err(error) = transaction.commit().await {
            return CognitiveSourceTerminalObservation::Unavailable {
                reason: error.to_string(),
            };
        }
        observation
    }

    async fn observe_terminal_snapshot(
        &self,
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        request: &ProductionDispatchRequest,
        draft: &SourceDraft,
    ) -> CognitiveSourceTerminalObservation {
        match Self::terminal_proof_tx(transaction, request).await {''')
s=s.replace('self.exact_count(&draft, &source_id).await','self.exact_count(transaction, draft, &source_id).await')
s=s.replace('.fetch_one(&self.store.pool)\n        .await;', '.fetch_one(&mut **transaction)\n        .await;')
(C/p).write_text(s)
(C/t).write_text(before[t]+'''
#[tokio::test]
async fn destination_observation_keeps_one_snapshot_across_late_exact_commit() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let target = CognitiveSourceOutboxTarget::new(
        store, CognitiveAccess::agent_private(owner.clone()),
    ).expect("target");
    let operation_id = "operation:late-exact-commit";
    let (draft, payload) = source_payload(operation_id, b"late exact source");
    let intent = operation(&owner, operation_id, &payload, &draft, None);
    let request = direct_request(&intent, payload);
    let source_id = SourceEventId::for_event(&owner, &draft.scope, draft.kind, operation_id);
    let mut snapshot = target.store.pool.begin().await.expect("read snapshot");
    assert_eq!(
        target.exact_count(&mut snapshot, &draft, &source_id).await.expect("initial exact probe"),
        0
    );
    let receipt = match tokio::time::timeout(
        std::time::Duration::from_secs(5), target.dispatch(request.clone()),
    ).await.expect("WAL writer must not wait for reader") {
        ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("unexpected outcome: {other:?}"),
    };
    assert_eq!(
        target.observe_terminal_snapshot(&mut snapshot, &request, &draft).await,
        CognitiveSourceTerminalObservation::Indeterminate {
            reason: "destination has no terminal proof for this operation".to_string(),
        }
    );
    snapshot.commit().await.expect("release snapshot");
    assert_eq!(target.observe_terminal(&request).await,
        CognitiveSourceTerminalObservation::Applied { receipt });
}
''')
patch('01-snapshot.patch',before)
p='codex-rs/hepta-memory/src/production_writer.rs'
n='codex-rs/hepta-memory/src/production_operation_reconciliation.rs'
s=(C/p).read_text();before={p:s,t:(C/t).read_text(),n:''}
s=s.replace('    live_verifier: Option<Arc<dyn ProductionAuthorityVerifier>>,','''    live_verifier: Option<Arc<dyn ProductionAuthorityVerifier>>,
    reconciliation_cursors:
        Arc<tokio::sync::Mutex<std::collections::BTreeMap<String, String>>>,''')
s=s.replace('            live_verifier: None,','            live_verifier: None,\n            reconciliation_cursors: Arc::default(),')
a=s.index('    /// Discover and reconcile a bounded batch');b=s.index('    async fn reconciliation_request(',a);method=s[s.index('    pub async fn reconcile_target_batch<T>(',a):b];s=s[:a]+s[b:]
s+='\n#[path = "production_operation_reconciliation.rs"]\nmod operation_reconciliation;\n';(C/p).write_text(s)
method=method.replace('        let operation_ids =','''        // Scheduling only: shared across clones, reset on reopen. Retain at
        // most 256 lifetime nonempty destination cursors; never silently evict.
        let destination = target.destination_id();
        let mut cursors = self.reconciliation_cursors.lock().await;
        let cursor = cursors.get(destination).cloned();
        if cursor.is_none() && cursors.len() >= 256 {
            return Err(ProductionWriterError::Invalid(
                "reconciliation destination cursor capacity exceeded".to_string(),
            ));
        }
        let operation_ids =''')
method=method.replace('             ORDER BY o.prepared_at_unix_seconds, o.operation_id','''             ORDER BY CASE WHEN ? IS NULL OR o.operation_id > ? THEN 0 ELSE 1 END,
                      o.operation_id''')
method=method.replace('        .bind(target.destination_id())','        .bind(destination)\n        .bind(cursor.as_deref())\n        .bind(cursor.as_deref())')
method=method.replace('        let mut reconciled = 0_usize;','''        if !operation_ids.is_empty() {
            cursors.entry(destination.to_string()).or_default();
        }
        drop(cursors);
        let mut reconciled = 0_usize;''')
method=method.replace('''        for operation_id in operation_ids {
            let request''','''        for operation_id in operation_ids {
            // Advance only attempted rows, including errors/unavailable. A
            // poisoned first row must not skip the unattempted batch tail.
            self.reconciliation_cursors.lock().await
                .insert(destination.to_string(), operation_id.clone());
            let request''')
(C/n).write_text('//! Bounded observer-only circular reconciliation.\n\nuse super::*;\n\nimpl ProductionDurableWriter {\n'+method+'}\n')
(C/t).write_text((C/t).read_text()+ (R/'fair_tests.txt').read_text())
patch('02-fair-reconcile.patch',before)
p='codex-rs/hepta-operations/src/durable_store.rs';t='codex-rs/hepta-operations/src/durable_store_tests.rs';n='codex-rs/hepta-operations/src/durable_lock_clock_tests.rs'
s=(C/p).read_text();before={p:s,t:(C/t).read_text(),n:''}
pattern=r'(        let (?:now|entry_now) = now_millis\(\)\?;\n)(        let mut tx = self\n            \.pool\n            \.begin_with\("BEGIN IMMEDIATE"\)\n            \.await\n            \.map_err\(sqlx_error\)\?;\n)'
s,count=re.subn(pattern,lambda m:m[2]+m[1],s);assert count==12,count
a=s.index('        let now = now_millis()?;',s.index('    pub async fn release_not_dispatched'));b=s.index('        let mut tx = self',a);c=s.index('        require_current_lease',b);s=s[:a]+s[b:c]+s[a:b]+s[c:]
s=s.replace('        require_current_lease(&mut tx, &claim, entry_now).await?;','''        let status = require_current_lease(&mut tx, &claim, entry_now).await?;
        let lease_until = status.lease_until_unix_ms.ok_or(DurableOperationError::StaleLease)?;''')
s=s.replace('''        let observation = match authorized.enter(effect) {
            Ok(observation) => observation,
            Err(error) => {''','''        let observation = match authorized.enter(entry_now, lease_until, effect) {
            Ok(observation) => observation,
            Err(error @ DurableOperationError::Authority(_)) => {''')
a=s.index('        let observation = match authorized.enter(');b=s.index('        let settled_at = now_millis()?;',s.index('                return Err(error);',a));sub=s[a:b].replace('''            }
        };''','''            }
            Err(error) => return Err(error),
        };''');s=s[:a]+sub+s[b:]
s=s.replace('''    fn enter<T>(
        mut self,
        effect:''','''    fn enter<T>(
        mut self,
        transaction_time: i64,
        lease_until_unix_ms: u64,
        effect:''')
s=s.replace('''            .with_verified_effect(token, &self.binding, || effect(&self.claim.intent))
            .map_err(DurableOperationError::Authority)
''','''            .with_verified_effect(token, &self.binding, || {
                // Sample after SQL awaits and synchronous authority-lock wait,
                // inside both fences immediately before actual effect entry.
                let now = now_millis()?;
                if now < transaction_time {
                    return Err(DurableOperationError::ClockRollback);
                }
                if to_u64(now)? >= lease_until_unix_ms {
                    return Err(DurableOperationError::StaleLease);
                }
                Ok(effect(&self.claim.intent))
            })
            .map_err(DurableOperationError::Authority)?
''')
(C/p).write_text(s);(C/t).write_text(before[t]+'\n#[cfg(unix)]\n#[path = "durable_lock_clock_tests.rs"]\nmod lock_clock_tests;\n');(C/n).write_text((R/'clock_tests.txt').read_text());patch('03-lock-clock.patch',before)
print('Regenerated3runtime patches;13 clock samples plus final-use callback deadline check')
