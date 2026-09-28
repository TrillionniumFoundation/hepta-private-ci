# kernel.authority two-process product recovery

Status: **normal product-process regression and candidate-bound qualification; not production trust, target-host acceptance, activation, or release**.

This qualification closes the repository-controlled gap between a same-process
`drop/reopen` fixture and two fresh normal Agentd processes using the ordinary
Fleet lifecycle, Agentd binary, public control socket, TaskFlow owner, FinalUse
owner, provider adapter, and reconciliation entrypoint.

## Preserved ownership and retry semantics

The regression does not expose or clone the crate-private effect host. Test setup
creates the same durable TaskFlow facts that a normal product call consumes;
physical dispatch and recovery are driven only through:

```text
codex-hepta-agentd
AgentdClient::automation_execute_effect
AgentdClient::automation_reconcile_effect
```

TaskFlow remains the attempt/observation owner. FinalUse remains the nonce,
revocation, pending-head, and frontier owner. Agentd remains the selected
provider-contract and effect-task owner. A timed-out control waiter is not
provider absence and does not cancel admitted owner work.

## Exact crash and recovery scenario

The test `two_agentd_processes_preserve_pending_nonce_attempt_witness_and_terminal_receipt` performs this sequence:

1. initialize a real Fleet record, Agent layout, AutomationStore, TaskFlow run,
   and claimed effect step;
2. start a first normal Agentd process, observe promotion readiness, and move its
   Fleet lifecycle from `Starting` to `Running`;
3. submit the effect through the public control socket to a provider endpoint
   whose response is deliberately delayed beyond the control-client timeout;
4. prove provider contact occurred while the Agentd-owned task continued after
   the waiter disappeared;
5. publish a newer signed revocation head that revokes the same grant and drive
   a second ordinary execute request so the active dispatch forces an exact
   durable pending head;
6. inspect the owner snapshot and fixed-width claim journal, then terminate the
   first process without graceful effect completion;
7. reopen the public AutomationStore and prove the exact attempt and
   non-authorizing authority witness were durably retained;
8. advance the Fleet lifecycle through `Failed` to a new `Starting` generation,
   launch a second fresh normal Agentd process, and promote it to `Running`;
9. recover the pending revocation from the same external frontier and signed
   feed, then reconcile the original provider occurrence through the normal
   status lookup entrypoint;
10. prove terminal replay returns the retained receipt without consuming a new
    grant or dispatching the provider again;
11. close the second process and verify the committed revocation head, cleared
    pending field, unchanged one-frame nonce history, identical witness, exact
    attempt identity, and terminal provider receipt.

The provider mock requires exactly one physical `POST` and one recovery `GET`.
A second `POST`, missing lookup, reset nonce file, changed witness, lost pending
head, or substituted receipt fails the test.

## Candidate-bound execution

`qualification/kernel-authority/product_process_recovery.py` runs one exact
integration-test identity with captured deterministic libtest output. A zero-test
exit, renamed or ignored test, duplicate execution, unexpected test, failed
summary, or contradictory count cannot produce a passing receipt.

The dedicated workflow executes both:

```text
exact-head
synthetic-merge
```

Every artifact binds source commit/tree, base commit, prepared candidate
commit/tree, exact command, exit code, duration, log bytes, and log SHA-256.
Successful execution may set only the repository-process facts covered by the
single test. It always keeps these false:

```text
productionTrustProved
targetHostQualified
independentAcceptance
activationGranted
releaseGranted
```

A queued, pending, cancelled, skipped, missing, stale, historical, or
different-SHA run is not success.

## Remaining external qualification

This regression uses normal product processes but still runs on a CI host with
fixture trust and provider services. Production completion separately requires
selected attested/protected time, rollback-independent frontier, KMS/HSM custody,
real revocation fanout, selected target-host filesystem and restart evidence,
independently accepted SLOs, operator acceptance, canary, promotion, and release.
