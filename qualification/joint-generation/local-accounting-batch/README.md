# Snapshot-batched complete-budget accounting

This research patch removes repeated validation of the same immutable cost graph
at one all-cell boundary. It does **not** change training, data, models, thresholds,
800 CPU-second per-method ceilings, or P/T/O/S/M attribution.

## Reproduce the portable tests

Python 3.12+, standard library only:

```sh
python3 -I -B -W error qualification/joint-generation/local-accounting-batch/test_batch_accounting.py
```

The 38 literal checks compare the entire old/new account maps, exact Decimal
formula AST, all category/total boundaries, invalid receipts/DAGs/allocations,
detached snapshots, fresh-call validation and end-of-batch M overshoot rejection.
They use an explicitly fake evidence adapter and never read a dataset, model or
private experiment receipt. This is not a scientific campaign runner.

## Implementation and integration

- `accounting.py` is the exact reviewed new accounting implementation.
- `support.py` supplies its original portable standard-library helpers.
- `reference/` retains the exact original two source preimages.
- `eval_controller.py` retains the exact reviewed two-call-site integration.
- `integration.patch` applies to those original files, with hashes in
  `PROVENANCE.json`. No existing repository accounting module is overwritten.

`standalone_all` executes the original full `inventory` once per call, then uses
that call's detached snapshot for all 12 cell reductions. Original `standalone`
behavior, evidence checks, Decimal formulas, DAG rules, carry requirements and
ceilings remain. There is no cross-stage or persistent metadata cache and no
unverified public batch entry point.

Production integration must supply the original fail-closed `evidence` adapter
and the other original controller modules. They are not replaced with the test
stub. The controller source here is an integration reference, **not a stand-alone
launcher**. Private historical receipt graphs and scientific execution authority
are intentionally not published; absence of those dependencies must fail closed.

The live-clock path samples M after validation, per cell, then again for a final
all-cell gate. The small tail after the final sample still requires the original
provisional and complete-wait settlement. Snapshot verification does not repeatedly
re-read mutable files within one call; each new boundary validates afresh.

## Observed qualification and limits

A separate local real-metadata check used a frozen 245-event receipt graph. Old
and new implementations produced the same full 12-cell account map and matched
its saved values. Private inputs are not included here. In two fresh Python
processes, method CPU was 1.980629658 seconds for the old 12-call path and
0.171437934 seconds for the batch. This single old-then-new observation is not a
replicated timing guarantee; filesystem-cache/order effects remain possible.
The three original qualification children cost 2.457115 CPU seconds in total;
supervisor lower bound was 0.010592874 seconds, with final tail unknown, not zero.
Portable-publication validation is separately recorded in `QUALIFICATION.json`.

The originating experiment stopped when shared M exceeded 120 CPU seconds. Its
budget failure remains a failure, and its predeclared quality claims were also
negative. This patch neither retrospectively accepts it nor establishes content
or NDU generation improvement. No identical-hypothesis retraining was performed.
A future full run needs independent source-bound admission and complete costs;
this local speed observation does not prove that its total M will satisfy 120.

No datasets, model weights, per-request DEV rows, receipt graphs, credentials,
unknown files or broad experiment outputs are included. No merge or deployment
is authorized by this package.
