#!/usr/bin/env python3
"""Write the human review and exact raw/source references; no product execution."""
import collections
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent

def pin(path):
    data=path.read_bytes()
    return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),git_blob=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest())

def read(name):
    return json.loads((ROOT/name).read_text())

def write(name,value):
    path=ROOT/name
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return pin(path)

SPECS = [
 ('injection_after_completed_turn','positive_and_absence_control','First turn completes before injection. The injected developer item is durably present with metadata=None. Exactly two physical provider requests: absent from request 1 and present in request 2.', ['requests.len(), 2','!requests[0]','requests[1]','persisted_developer_item.metadata, None']),
 ('recovery_cwd_drift','negative_rejection','After a real child kill and cold resume with an explicit different cwd, the returned cwd is the override; recover must return INVALID_REQUEST and no-longer-valid, and provider request count stays 1.', ['resumed.cwd, override_cwd','INVALID_REQUEST_ERROR_CODE','no longer valid','model_requests(&server).await?.len(),']),
 ('recovery_paginated_tail','positive','After a real child kill, the paginated canonical context tail is Interrupted; recovery preserves the original turn id through completion, paginated history contains one such turn, and provider requests are exactly 2.', ['ThreadHistoryMode::Paginated','TurnStatus::Interrupted','ClientRequest::TurnRecover','completed','model_requests(&server).await?.len(), 2']),
 ('recovery_workspace_root_drift','negative_rejection','After a real child kill, explicit resumed roots override persisted roots; recover is INVALID_REQUEST and physical provider requests remain 1.', ['vec![override_root]','INVALID_REQUEST_ERROR_CODE','workspace-root drift must fail closed before another physical provider send']),
 ('recovery_after_provider_output','negative_rejection','The test first receives a real command-execution approval request from provider output, kills the child, and cold resumes. Recovery is rejected as not interrupted; no second physical provider send.', ['ServerRequest::CommandExecutionRequestApproval','kill_ungracefully','not interrupted','model_requests(&server).await?.len(), 1']),
 ('recovery_busy_complete_wrong_thread','negative_rejections','The same original test rejects busy, already completed, and cross-thread/wrong-tail identities plus a pending interruption/approval boundary. Exactly two provider requests ensure rejects do not sample.', ['not interrupted','not the interrupted tail','model_requests.len(), 2']),
 ('recovery_ephemeral_listener','positive','The ephemeral thread has no persisted rollout. After a real request and interrupt it recovers from listener state, preserves the turn id, completes, and the restored input occurs once across exactly two requests.', ['ephemeral: Some(true)','TurnStatus::Interrupted','TurnStatus::InProgress','model_requests(&server).await?']),
 ('recovery_feature_disabled','negative_rejection','HeptaTurnRecovery is not enabled; actual turn/recover returns -32600 with the exact feature-required message and the model server receives zero requests.', ['INVALID_REQUEST_ERROR_CODE','turn/recover requires features.hepta_turn_recovery=true','model_requests(&server).await?.is_empty()']),
 ('recovery_stable_queue_and_hook','positive_and_deduplication_controls','A real child is killed after the first physical provider send. Cold recovery hydrates roots, preserves the interrupted id, consumes the same stable queued user input once, does not consume SessionStart on recovery, and the next new turn runs that hook once. History/physical input occurrence counts are asserted.', ['kill_ungracefully','client_user_message_id','SessionStart','model_requests(&server).await?']),
 ('suspension_unfinished_history','positive_and_descendant_rejection','A delayed local provider response keeps the root active. A currently loaded descendant blocks handoff; after it shuts down/removal, suspension succeeds. Durable history has no TurnAborted/TurnComplete and retains Ready. A replacement runtime preserves config and environment, recovers the same id, and both original and recovered provider requests are single requests.', ['SuspendTurnOutcome::HasLiveDescendants','RolloutItem::EventMsg(EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_))','TurnRecoveryCandidateState::Ready','Some(original_environments.clone())','recovered_request.single_request()']),
 ('task_panic_terminal_error','fault_injection','An intentional SessionTask panic is converted to a TurnComplete terminal lifecycle event and the active slot becomes None, within the original two-second waits.', ['PanickingTask','StdDuration::from_secs(2)','EventMsg::TurnComplete(_)','active_turn.lock().await.is_none()']),
 ('finish_owner_cancel','fault_injection','A real spawned finish owner is cancelled while the idle contributor is blocked. Releasing the contributor lets the detached terminalizer complete its exact witness, clear the pending/active fences, and publish idle exactly once.', ['finish_owner.abort()','completion.as_mut().now_or_never().is_none()','assert_eq!(1, idle_calls','detached finish terminalizer should clear its exact fence']),
 ('finish_terminalizer_panic','fault_injection','The turn-stop contributor intentionally panics after the non-idempotent transition. Pending/exact active terminalization fences remain, no TurnComplete is emitted, and the original 100 ms shutdown-drain observation remains unresolved.', ['intentional finish terminalizer panic','panic must not publish TurnComplete','StdDuration::from_millis(100)','an advanced finish panic must leave shutdown fail-closed']),
 ('finish_watchdog','fault_injection','A contributor signals entry then remains pending. The original watchdog returns, elapsed time is at least the actual cfg(test) watchdog; the completion observation resolves but pending/active fences stay, with no terminal event.', ['std::future::pending::<()>()','StdDuration::from_secs(1)','StdDuration::from_secs(4)','started.elapsed() >= crate::tasks::TERMINALIZER_WATCHDOG_TIMEOUT','a hung terminalizer must not publish a terminal event']),
 ('abort_owner_cancel','fault_injection','The actual public abort owner is cancelled after entering a blocking abort hook. Releasing that hook allows its detached owner to clear the exact active and registry fences within the original two-second wait.', ['abort_owner.abort()','release_abort.notify_one()','detached abort terminalizer should clear its exact fence']),
 ('abort_terminalizer_panic','fault_injection','An actual PanickingAbortTask executes its panic path; pending and active terminalization witnesses remain instead of admitting a replacement writer.', ['PanickingAbortTask','session.has_pending_task_terminalization()','active_turn.task_terminalization.is_some()']),
 ('suspend_caller_cancel','fault_injection','The real suspend caller is cancelled while thread-stop lifecycle blocks. Active/pending fences remain across cancellation; after release, shutdown completes once and the exact turn id stays the same. This original unit fixture bypasses only descendant inventory; the separate root integration test exercises the live descendant check.', ['suspend_turn_and_shutdown_for_test','caller.abort()','store.calls().await.shutdown_thread, 1','assert_eq!(turn_id, tc.sub_id)']),
 ('idle_steer_rejection','negative_rejection','Steer-only with no active turn returns NotSubmitted::NoActiveTurn; it cannot create a new turn.', ['NotSubmittedReason::NoActiveTurn','submit_steer_only']),
 ('wrong_turn_steer_rejection','negative_rejection','With a live never-ending regular task, steering the wrong id returns ExpectedTurnMismatch carrying both exact expected and actual ids.', ['NeverEndingTask','NotSubmittedReason::ExpectedTurnMismatch','actual: turn_context.sub_id.clone()']),
]

def main():
    evidence=read('original-19-case-evidence-v1.json')
    bridge=read('source-leaf-bridge-v1.json')
    assert len(bridge['complete_source_files'])==22
    rows=[]
    for case,spec in zip(evidence['cases'],SPECS,strict=True):
        tag,kind,contract,needles=spec
        block=pathlib.Path(case['raw_block']['path']).read_bytes()
        body=pathlib.Path(case['source_excerpt']['path']).read_text()
        # Deliberately broader than the frozen v1 skip_re. No v1 output is overwritten.
        assert b'Skipping test' not in block and b'skipping capability test' not in block
        for needle in needles:
            assert needle in body,(tag,needle)
        text=block.decode()
        if 'suite::v2::turn_recover::' in case['name']:
            assert 'writing message to stdin: Request(JSONRPCRequest' in text and 'method: "turn/recover"' in text
            assert 'read message from stdout:' in text
        if tag=='injection_after_completed_turn':
            assert 'Injected after first turn' in text and 'method: "thread/inject_items"' in text
        lines=[]
        for number,line in enumerate(text.splitlines(),case['raw_block']['first_line']):
            if ('Error(JSONRPCError' in line or 'intentional ' in line and 'panic' in line or
                'writing message to stdin:' in line and ('method: "turn/recover"' in line or 'method: "thread/inject_items"' in line)):
                lines.append(dict(original_full_raw_line=number,text=line))
        rows.append(dict(position=case['position'],classname=case['classname'],name=case['name'],result=case['result'],seconds=case['seconds'],
            contract_kind=kind,original_assertions_reviewed=contract,source_body_identity=case['source_excerpt']['identity'],
            source_original_lines=[case['source_excerpt']['start_line'],case['source_excerpt']['end_line']],
            complete_original_raw=case['raw_block'],direct_raw_observations=lines,
            broad_no_skip_notice_checked=True,
            inference_limit='Assertions not printed by libtest are supported by the exact unchanged test body and its successful complete execution; no claim is made that every assertion text appears in stdout.'))
    sources={x['logical_path']:x['identity'] for x in bridge['complete_source_files']}
    production=[
        ('codex-rs/app-server/src/request_processors/turn_processor.rs',[907,937],'Raw injection validates and deserializes the requested ResponseItems, routes to the actual thread, and propagates errors.'),
        ('codex-rs/app-server/src/request_processors/turn_processor.rs',[1592,1790],'Recovery checks feature, exact thread/tail/id/status and captured Core epoch, calls recover_turn_if_idle, and rejects invalid/busy/stale states; ephemeral listener history and paginated bounded history stay distinct.'),
        ('codex-rs/core/src/codex_thread.rs',[674,807],'Public recovery does not add new user input and preserves the turn id. Suspension is root-only, accepted work belongs to the session after caller disconnect, and waits for actual loop termination. Steer-only cannot become Started.'),
        ('codex-rs/core/src/codex_thread.rs',[939,983],'Injection routes into real session history and flushes persisted rollout; this is not a recorder-only fixture.'),
        ('codex-rs/core/src/session/mod.rs',[1213,1240],'Recovery epoch is returned only for the exact idle candidate and matching turn epoch/persistence generation, with no shutdown or terminalization fence.'),
        ('codex-rs/core/src/session/turn_input.rs',[396,773],'Recovery under active-turn ownership validates exact candidate generation, persisted context/environment and history boundary; settings drift rejects before a new provider send. Consumption and reservation remain explicit.'),
        ('codex-rs/core/src/session/turn_input.rs',[911,1035],'Steer-only retains active-turn/task/terminalization and expected-turn-id checks before queue admission.'),
        ('codex-rs/core/src/session/turn_suspension.rs',[20,131],'Public handoff is bounded at 30s independently of the detached owner. Live descendant inventory, durable preflush, exact task claim, and first-poll witness are preserved. Unit-only helper omits only inventory.'),
        ('codex-rs/core/src/session/turn_suspension.rs',[274,493],'Owned suspension retains the exact witness on panic/cancellation; task quiescing, input clearing, runtime stop, writer flush/close, lifecycle/event publication and final exact marker release remain ordered.'),
        ('codex-rs/core/src/tasks/mod.rs',[90,97],'Existing production terminalizer watchdog is 30s; existing cfg(test) constant is 2s. This review changes neither.'),
        ('codex-rs/core/src/tasks/mod.rs',[2505,2578],'SessionTask panic is caught and converted into the ordinary fatal terminalization path; attached task epoch and recovery identity remain actual.'),
        ('codex-rs/core/src/tasks/mod.rs',[2734,2789],'Abort owns a detached scheduled job after claiming the complete task witness, so cancelling the public await does not discard cleanup.'),
        ('codex-rs/core/src/tasks/mod.rs',[3149,3186],'Finish likewise claims a witness then runs the owned terminalizer detached from the public caller.'),
        ('codex-rs/core/src/tasks/mod.rs',[3507,3629],'Finish/abort handoff drivers catch panic and use the watchdog while retaining exact failed-closed witnesses; successful release requires completed side effects.'),
        ('codex-rs/core/tests/common/lib.rs',[583,616],'The original skip_if_remote macro prints Skipping test in a remote test environment before returning. All original19 raw blocks were separately checked against the broad Skipping test prefix.'),
    ]
    production=[dict(path=path,identity=sources[path],lines=lines,review=description) for path,lines,description in production]
    review=dict(schema='b09-original-contract-independent-review/v1',conclusion='CLOSED_SCOPED_CANDIDATE_FOR_ROOT_DECISION',
        root_has_not_yet_closed_b09_in_this_record=True,
        literal_original_exit=evidence['original_exit'],
        counts=dict(original_names=19,actual_unique_executions=19,passed=19,failed=0,skipped=0,observed_early_return=0,
            composition=dict(injection=1,turn_recover=8,suspension_integration=1,panic_cancel_watchdog=7,idle_steer=2),
            turn_recover_composition=dict(successful_recovery=3,rejection_scenarios=4,feature_disabled_rejection=1)),
        tested_source=evidence['source_tree'],native_job=evidence['native_job'],platform='Linux x86_64 GNU / original host rog',
        evidence=pin(ROOT/'original-19-case-evidence-v1.json'),source_bridge=pin(ROOT/'source-leaf-bridge-v1.json'),
        complete_original_verification=pin(ROOT/'complete-original-verification-v1.json'),verifier=pin(ROOT/'verify_b09_originals.py'),
        complete_source_file_count=22,case_contracts=rows,production_review=production,
        interpretation=[
            'The literal B09 exit names these existing controls. It does not state a new five-platform matrix or whole-candidate success prerequisite. Q01 and historical broad evidence-gathering plans are not added as new exit requirements.',
            'All nineteen original names now have complete original fb9 GNU/Linux execution evidence, including their existing functional rejection/fault controls. No substitute new recovery case or newly written mirror test is used.',
            'The full reviewed test files and direct production/test-support files are unchanged across four independently reconstructed trees: fb9, 5b, e78, eed. All existing Cargo manifests and the two lock leaves also match. This supports scoped source continuity only.',
            'The seven enabled-feature turn_recover cases are not all positive recoveries: three succeed, four exercise rejection scenarios. The eighth is the explicit disabled-feature rejection.',
            'Panic/cancel/watchdog negative controls are existing fault-injection tests whose expected outcome is a PASS with the original fail-closed assertions. They are not separately counted as failed product tests or invented mutation runs.',
            'The old complete fb9 run remains 19490 PASS / 16 FAIL / 25 observed early-return cases, command exit100/controller nonpass. The nineteen cases are outside those25. B15 and other whole-tree/platform obligations remain separate.',
            'No new GNU execution of the entire eed tree, Wine, macOS, musl, or Windows run is claimed by this receipt. Existing platform evidence remains separately labelled by its actual source/job.'
        ],
        reviewer_corrections=[
            {'issue':'Frozen verifier v1 skip_re covers because and in the Wine but not the remote-test-environment spelling.',
             'resolution':'v1 source and its outputs stay unchanged. This independent semantic review checks every full original19 block for any Skipping test prefix and skipping capability test, then verifies real request/response activity for all nine App cases. Root independently performs the same broader check.',
             'outcome':'No such skip/early-return prefix appears in the nineteen blocks.'},
            {'issue':'The initial local verifier draft counted all 19522 header-shaped lines, including the final16 failure-summary repetitions.',
             'resolution':'Before freezing v1, the parser was bounded by the exact original full Summary line and requires the16 summary rows separately equal the original failure Counter; no deduplication disguises repeated executions.',
             'outcome':'19506 original execution records, 19 unique B09 records; source/raw/XML remain unchanged.'},
            {'issue':'The earlier remaining-five-exit assessment used the limited e78 project selection and therefore did not notice that full fb9 already contained the eight original recovery cases.',
             'resolution':'Keep that historical assessment. This review supplies the full older archive and explicit source bridge rather than changing its coverage or relabelling fb9 as e78/eed.',
             'outcome':'The original19-execution gap is now covered by complete originals; whole-candidate failures remain open elsewhere.'}
        ],no_native_or_tests_executed_by_review=True)
    print(json.dumps(write('semantic-review-v1.json',review),ensure_ascii=False))

if __name__=='__main__':
    main()
