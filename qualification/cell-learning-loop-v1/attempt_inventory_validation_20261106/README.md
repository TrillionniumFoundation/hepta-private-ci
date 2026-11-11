# Missing attempt accounting regression

This change extends the Memory recovery code based on PR #5089 at
`9bbf4bb4d1b5466f62d75d6b70dad4d26ec75d55`.

The original driver rejected retry of a known attempt with a missing phase result,
but it summarized only `phase_results/*.json`. If no result survived, the empty
sum reported worker CPU and wall time as zero. An unsettled attempt for a phase
past `--stop-after`, an unregistered attempt, or a linked attempt directory could
also be omitted from the aggregate and did not stop later dispatch.

The driver now inventories attempts before dispatch and again during final
accounting. Missing receipts, unknown phase names, linked paths and an unresolved
training marker prevent further dispatch and remain in the failure summary.
When any attempt lacks settled measurements, total worker CPU, wall time and
RSS remain unknown. Existing failed receipts still retain their measured costs.
No attempt is replayed, deleted or relabeled as successful.

The five new behavior regressions all failed against the original driver. The
fixed driver passed those five together with the existing 13 recovery tests:
**18 passed, 0 skipped**. Tests launch real fresh subprocesses producing synthetic
worker receipts; there are zero model loads and zero optimizer updates.
`RESULTS.json` binds the final command, source byte hashes and raw logs. The
initial diagnostic invocations are also retained and labeled separately.

This closes an evidence-accounting defect. The original real Memory experiment
still improved authored corrections from 0/2 to 2/2 while historical correctness
fell from 59/72 to 55/72. Its candidate remains unadopted under the original gate.
No nine-arm future round, complete cost superiority, adoption after cold startup,
or next real-task qualification is claimed.
