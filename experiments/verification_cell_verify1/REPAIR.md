# Predeclared repair evidence

`RepairLineage` records one original repair opportunity per frozen task, across
distinct parent and child `ShadowJournal` subjects and continuation targets.
Both rosters must be frozen before child execution. The goal domain/event and
source group match; an external evaluator still has to establish the semantic
task relation. The parent forecast and label are never rewritten as child success.

Create it with the original owner's identity/version and a frozen `CostItem`
roster. Keep its manifest and ledger hashes externally. `prepare` returns an
intent claim; authenticate and `record` it before the original owner dispatches.
This module executes nothing. `completion` forms an original-operation claim
for an authenticated destination readback; record either completed or failed.
An absent/unknown reply remains pending. Recovery never returns permission to
reissue an operation. Record explicit no_repair/abstained decisions with reasons;
unrecorded opportunities remain in the denominator.

Freeze and intent writes acquire parent then child SQLite writer locks and commit
the parent while the child remains locked. Hardlinked parent/child files refuse.
This establishes journal order; actual physical effect order remains an obligation
of the original owner protocol, which dispatches only after the intent is durable.

Owner verification receives `(manifest, claim, attestation)` and must check the
original authorized owner, source/subject/target/root bindings, current trust,
and actual destination evidence. `report` reauthenticates every retained owner
claim and both original label journals before counting observed corrections or
induced errors, including terminal failed repairs with known labels. These paired
observations do not prove causal repair benefit.

Cost reports reuse `summarize_costs`. Only a separate authenticated complete
physical/history-coverage claim plus complete measurements can mark full cost
complete. Missing operations or measurements stay explicit. No default verifier,
new trust key, acceptance authority or automatic adoption is provided.
Included tests use synthetic custody fixtures and establish no independent tasks.
Scientific admission remains HOLD; production authority remains NONE.
