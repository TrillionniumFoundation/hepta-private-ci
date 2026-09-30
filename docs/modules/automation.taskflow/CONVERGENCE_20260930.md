# automation.taskflow Schema 22 convergence record

This record supplements [TECHNICAL.md](TECHNICAL.md) and is bounded by the generated
[CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md). It records repository source
composition only; it is not a deployment, selected-host, independent-acceptance,
activation, promotion or release receipt.

## Immutable qualification topology

The sole focused workflow is `.github/workflows/automation-taskflow-focused.yml`.
It resolves an immutable candidate and base before any checkout. Linux exact-head,
macOS exact-head and deterministic local-merge lanes use read-only credentials,
check-only formatting, locked compilation, strict Clippy, native tests, Agentd
product tests and Bazel qualification. No TaskFlow workflow may commit, push,
format source in place or synthesize a future tree. A queued, skipped, interrupted,
`not_run`, missing or failed record cannot satisfy a success gate.

The Lane B canonical-path guard now resolves every explicitly named delegated owner
through that module's canonical implementation map. It does not widen the closed
Lane B operation inventory and does not treat a legitimate cross-lane owner such as
`learning.ledger` as an unowned path.

## Durable Circuit product composition

`codex-rs/hepta-agentd/src/automation_circuit_host.rs` is the named product host for
the existing durable owner. It binds one Agent, owner identity and spawn generation
to registered DecisionCell, organ, Wait and recovery ports. The AutomationStore
commits the activation intent and conserved cost reservation before owner contact.
Wait and Effect boundaries persist resumable checkpoints. Committed outcomes and
recorded choices replay without asking a newer policy to reinterpret history.

The product regression includes the decisive ambiguous cut: an owner port records
that contact occurred and then returns an error before the durable receipt exists.
The run remains executing/recovery-required and an identity-bound recovery observer
settles the exact activation. The owner call count remains one; the host never turns
a lost receipt into permission to call the owner again.

## Cross-host writer handoff

`cross_host_controller.rs` composes the existing signed host-fence contract with an
exact checkpoint digest and the timer lifecycle. Source sealing requires current
independent fence claims, drains unresolved work, creates the recovery manifest and
retires the source writer. Target admission requires a copied store still draining
at the source epoch, exact owner/schema/checkpoint/fence identity, and exactly the
next writer epoch. Post-handoff validation runs before the target becomes active.
A wrong target, expired/partitioned controller or digest mismatch leaves the copy
draining. A stale source or predecessor target handle cannot resume writing.

Repository tests exercise two distinct store roots, copied SQLite bytes, source
retirement, next-epoch target activation, stale-handle rejection and wrong-target
partition behavior. Physical host isolation, checkpoint transport and real network
partition remain selected-runtime evidence rather than source declarations.

## Bounded startup and retained history

TaskFlow definition, run and event verification uses fixed-size pages from one
read snapshot. It validates every digest, revision and fence transition without
materializing an unbounded retained collection. Recovery frontiers use permanent
keyset sweeps rather than business timestamps. Selected-runtime growth, restore,
compaction and saturation measurements remain required before deployment claims.

## Runtime metrics

The owner exports the following exact metric names:

- `automation_unknown_effect_age_seconds`
- `automation_recovery_sweep_lag`
- `automation_recovery_budget_saturation_total`
- `automation_timer_writer_epoch`
- `automation_timer_drain_blocked_total`
- `automation_circuit_recovery_required_total`
- `automation_circuit_reserved_cost_units`
- `automation_circuit_resume_latency_seconds`
- `automation_occurrence_parked_seconds`
- `automation_destination_dedupe_conflict_total`

Store-derived gauges are read-only and bounded. Process counters are monotone within
one Agentd process epoch and must be exported with host and generation labels.

## Remaining evidence boundary

Source composition does not prove that a selected host consumed the declared tzdb
profile, native SQLite implementation, provider contract, final-use trust root,
revocation frontier or terminal observer. The final candidate must have terminal
green Linux exact-head, macOS exact-head and deterministic-merge receipts on the
same source candidate. Independent acceptance and all release states remain false.
