# ACT-2 real App observation faults

This extension depends on evidence source `db3324c75cd4ef1e46ee4603a5fd8df240fe8722`.
It extends the existing explicitly selected real Session/App test. It does not
change the writer, observer implementation, effect authority or skill library.

## Frozen assertions

1. Observe the first original operation while revision 1 still satisfies its
   goal; retain the actual owner receipt and positive current-goal observation.
2. After the existing second and third real edits, freshly read revision 3.
   The first operation must retain historical `applied`, but report current
   goal `unsatisfied` and runtime `unknown`.
3. Read the third original operation and its receipt three more times, querying
   the App independently each time. Each complete status assembly must equal the
   preceding successful observation. Effect attempts and grant requests must stay
   at 3 and 4 respectively, including the existing deliberately denied grant.
4. Close and reap this test's Notes App, then actually attempt a new document
   read. The read must fail. Read the original operation and receipt again:
   historical `applied` and committed owner state remain, current readback is
   absent and current goal/runtime become `unknown`. Effect/grant counts remain
   unchanged.

The test uses the existing production nonce-correlated document observer and
product status assembly. It does not invoke the complete model-facing tool
handler. All these assertions belong to one test and one App lifecycle; they
are not independent trials or a success-rate estimate.

## Execution and records

Push the dedicated `test/act2-real-observer-faults-20261109-r1` branch to run the
existing ACT-2 qualification workflow. Its checkout uses the triggering SHA;
the companion remains pinned to `fd8d56c52b971c2d5d0e6430f296803b43ef60a3`.
The workflow runs the automation package, selected Notes tests, locked companion
build, real App test, scoped fix and official formatter. Native command records,
full logs, original readback JSON and source/lock/binary identities are retained
in the workflow artifacts.

The pre-extension run `42613527940` is historical evidence only. New assertions
have no passing result until this extension's exact-source run completes.
Formatting output, if any, is recorded separately from the tested source.

## Remaining holds

App closure here is a readback-loss fault. It is not a Notes durable tombstone,
a cancel/commit race qualification, or proof excluding a late commit. Overdue
checkpoint recovery, general cross-observation ordering, real long-running and
network-wait adapters, production authority, pixels and learned hierarchy
benefit remain unqualified. Full ACT-2 promotion stays HOLD.
