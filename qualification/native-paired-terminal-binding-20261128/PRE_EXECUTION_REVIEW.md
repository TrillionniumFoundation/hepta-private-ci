# Review amendment before the first native gate

The initial protocol remains unchanged. Review identified two concrete gaps:
Prepared originally compared only Ledger and Replay owner Arcs, and its outer
timeout did not reach the existing spawn_blocking worker's work budget.

The candidate now also retains and compares the original jobs and compute Arcs.
The existing custody control adds a second Owner built on the same Ledger/Replay,
which must refuse Prepared because it has different job and compute state.

A stricter end flows through an internal train_until into the existing executor,
authorization wait and blocking fit checks. Signed request/job bytes do not change.
The original end is checked before a new native fit invocation and after work.
An already invoked synchronous atomic fit cannot be preempted; actual work may
finish after end. Timeout or a post-fit change cannot be reported as no execution.
The deadline control also calls the actual native owner with an already expired end.

Because this changes the shared terminal executor, the first gate includes its
four existing terminal_learning_tests as necessary regression: real supervised
fit/readback/idempotency, exact owner evidence/budget, queue/lost acknowledgement,
and recovered-Ledger missing-job behavior. Together with nine new paired controls,
select `test(terminal_learning_tests)` and require exactly 13, no skip/count drift.
This does not repeat the previous Root/Agentd 61/26 or identity-only eight gates.
The cap remains 600 seconds and the original shared 3600-second cumulative budget.
The four existing regressions also execute their original synthetic native fits;
the claim of one positive fit in the original protocol describes the new paired
controls only. All such execution is engineering, with no scientific-budget reset.

The original native job cache can return an existing exact result. A new signed
pair association is not proof that this delivery executed a fresh fit; the receipt
does not add an executed-this-delivery flag or permission to award work again.
