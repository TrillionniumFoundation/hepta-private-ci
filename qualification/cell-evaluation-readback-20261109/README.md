# Cell evaluation caller: authenticated execution readback

## Result

**10 selected Cell tests passed; real private-head learning and production remain HOLD.**
Code: [#5539](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5539), commit `bc6b9ff0a6436c5aacc3a3f0fb1edca7b5dd115b`,
tree `29b59b85b406cca78e7c76b9fb9c0f112c08ca66`. The cut changes 471 lines across three files.
It follows the Product execution recovery stack and its [retained evidence](../product-evaluation-execution-recovery-20261109/README.md).

The Cell wrapper privately owned ProductEvaluationRunnerV1 and previously exposed
only execution. The new `evaluate_or_readback` reuses its authenticated durable
readback. It re-reads both drained journals, complete cost/continuity cuts and the
full frozen Product plan before any execution claim, provider call or holdout
mutation. The old evaluate path shares the same original journal check.
Qualification retains the original Product evaluator and signing domain.

## Native checks

```text
just test --locked --offline -p codex-hepta-agentd --lib neuron_cell_evaluation --test-threads 2
```

| Attempt | Actual result |
| --- | --- |
| 1 | Compile exit 101, zero tests; isolated snapshot lacked the original module catalog input. |
| 2 | Compile exit 101, zero tests; agentd test compilation exposed the original proposal-worker fixture input. |
| 3 | **10 passed, 817 skipped**; seven existing Cell cases and three added parent cases. |

Both missing inputs were restored from exact baseline Git blobs, without fixture
changes. The external include scan and validation recipes are retained. This is
a scoped Cell run, not all agentd tests. Its three new cases are included in ten;
they are not added on top. The preceding 141 evaluation tests were not rerun.

The added cases cover complete receipt equality after actual file close/reopen,
original evaluator/validity checks, current fence takeover, and rejection of
journal/cost/foreign-plan drift before claim. Cell reopening occurs within one
process; the separate Product tests cover actual writer/reader OS subprocesses.
All cohorts and role keys remain explicit fixtures.

Scoped `just fix` and `just fmt` exited zero. Only two candidate Rust files changed
in maintenance. Per AGENTS.md, behavior tests were not rerun afterward.
`cargo check --locked --offline -p codex-hepta-agentd --lib --bins` then exited zero
without changing source. Existing warnings are retained; warning-free validation
is not claimed. Rust 1.96.0, just 1.51.0 and nextest 0.9.137 were used with four
build jobs and a 16 GiB memory limit in an isolated offline target directory.

## Source and evidence binding

Test inventory: `92dc7b736c831fbc7f1e7525239201aa768f54aa82824aafd6ef6b0494ef5ef4`.
Maintained inventory: `843b0e6e5ed93671dcfcdc8230930d88f2379b30a0d4c2dff7ce6ea6183c4e97`.
The 10,618 objects comprise 10,616 codex-rs objects and two exact external
compile inputs. Test sources stayed unchanged during execution. Every maintained
object was compared to the local publishing candidate. Projection trees exclude
later qualification documents; complete identities are in `validation.json`.
The source archive retains the reversible tested-to-maintained patch.

`native-evidence-v1.tar.xz` contains all three attempts, raw logs, inventories,
resource usage and maintenance/compiler records. `source-and-review-evidence-v1.tar.xz`
contains source binding, validation recipes and separate code-review scope.
Both have internal manifests and external hashes in `SHA256SUMS`.

The prior full caller proof covers evaluation code head `715dfcecd10afcdaf9db4d2559c306c11282ba7b`.
It is not relabeled as a full caller proof for this later Cell change. This cut
has the scoped native checks and code review above; GitHub CI remains separately
observable and no required-CI success is inferred from native results.

## Remaining real experiment gates

[OWNER_ASSEMBLY_NEXT_GATES.md](OWNER_ASSEMBLY_NEXT_GATES.md) records the exact
profile/scoped-transport integration dependencies and missing original owner
inputs. It is a bounded audit and an unexecuted integration plan, not a claim
about every other branch or deployed host.

Actual Experience, Dataset, single private-head Training, independent Evaluation,
Selection and NextUse still need the original admitted capabilities and real
ordinary-task records. Missing authority is an error, not a completed NoUpdate.
Full Root-session learning recovery, published-generation next-task consumption,
new-task gain, old-ability retention and complete training economics remain HOLD.
No real model training, production Adopt/NoUpdate, merge or deployment occurred
in this scope. This mechanism evidence establishes no descendant-improver or RSI
advantage.
