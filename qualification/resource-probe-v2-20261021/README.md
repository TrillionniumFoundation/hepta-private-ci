# Resource probe V2: exact owner child, no model execution

This package repairs the resource collector proposed in V1 and attaches it to
the two existing read-only CPU scout workflows. It does not close the larger
runner requirement, qualify a model, or schedule a new 112-call attempt.
SHADOW_ONLY / DENY_ALL / NO_GO remain in force.

## Exact source

- Owner PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452
- Owner branch: `codex/memory-cell-evidence-20261008`.
- Exact parent: `81d9fcb36bddfcc6dc914f87697c642824273cc1`.
- Local child: `b01d33144b4f153adc46649bba6ac9683aa3b94d`.
- Child tree: `e965df0dd997492da34f294bfcb9174643502545`.
- Proposed child branch: `agents/memory-resource-probe-v2-20261021`.

The five changed files are the two existing scout workflows, the existing CPU
scout and its tests, and one new standard-library-only resource helper. The
incremental Git bundle requires the exact parent. No remote ref was written by
this work. The original generation runner, original workflow budgets, trigger
branches, path filters, permissions, concurrency, action pins and matrices are
unchanged. Workflow changes retain the collector source alongside its results.

## What V2 corrects

A cgroup namespace can report `0::/` while its visible root is an ordinary
non-root cgroup with hidden ancestors. A missing `memory.max` alone also cannot
identify the global hierarchy root. V2 uses the kernel's non-root-only
`cgroup.type` interface together with the root-only absence of `memory.max`,
readable controller interfaces, a single unambiguous mount, visible ancestry,
and stable process membership and mount observations.

It records every visible finite ancestor limit, including zero, and takes the
minimum with physical MemTotal. Missing non-root controller files require proof
that the visible parent did not enable memory for its children. Permission
errors, invalid values, legacy/hybrid hierarchies, an overmounted view or hidden
ancestors cannot become a complete-hierarchy capacity result. All raw bytes and
read failures are retained. The collector does not reserve RAM, measure a
NUMA/rlimit envelope, or certify inference latency.

Primary kernel reference:
https://docs.kernel.org/admin-guide/cgroup-v2.html
(`cgroup.type`, `memory.max`, controller enablement and cgroup namespaces).

## Actual validation and its limits

The existing two-module suite passed all 28 tests. Eleven new resource tests
cover actual-root semantics, the smaller-ancestor case, namespace and bind-mount
roots, zero/missing limits, disabled controllers, permission failures, malformed
or symlinked interfaces, membership drift and overmounts. The positive 16 GiB
fixtures are simulated logic tests, not hosted-runner measurements.

The separate real-container negative control came from hostname
`00f65abd2fab`. It observed `0::/`, `cgroup.type=domain` and a visible limit of
8,589,934,592 bytes. The complete-hierarchy capacity correctly remained null
and hidden ancestors remained unattested. This is a temporary shared container,
not a dedicated runner. The snapshot is bound to the committed collector hash.

Ruff 0.15.13 E/F/I and formatting checks passed. `just fmt` completed using the
already-installed identical Ruff environment with dependency synchronization
disabled and no network; all three changed Python files were byte-identical
before and after. No model was imported or run by this validation.

## Legal execution route

1. Publish the child branch and source package for review. A child-branch push
   does not match any push workflow in this exact snapshot. Do not describe
   opening a child PR as a read-only probe: the existing MemoryCell continuation
   PR workflow matches `scripts/memory_cell/**`, stages models and invokes the
   locomo/longmemeval native pilots, actual pretrained training/serving owner
   tests and actual Laya tensor training. Its relevant job conditions and commands are included separately.
   Opening the PR therefore requires the owner to account for that existing
   model CI and its resources; this work has not executed it.
2. Re-read the owner head before any merge or normal ref update. If it has
   moved from the exact parent, reconcile and review the actual new diff. Do not
   force-update the owner or alter its branch restriction.
3. Only an authorized update of the existing owner branch activates these
   scout workflows. One such push starts two existing workflow runs: three
   image jobs in `hepta-memory-bf16-host-scout.yml`, plus three images times two
   repeats in `hepta-memory-bf16-hosted-scout.yml`, nine declared scout jobs.
   Those two workflows have no model calls and no `workflow_dispatch` route.
   The same owner update can also synchronize the existing PR and activate its
   original model CI. Nine scouts is not a count of all resulting CI jobs.
   No branch filter, PR condition or other gate is disabled to avoid this.
4. Record every run ID, run attempt, job ID, runner metadata, source SHA, status
   and artifact digest. Retain failed and ineligible samples. Do not rerun jobs
   selectively to hide an unsuitable machine or call nine samples one host.

For each image (`ubuntu-22.04`, `ubuntu-24.04`, `ubuntu-26.04`), expected artifacts
are `memorycell-bf16-cpu-<image>` and
`memory-native-bf16-host-<image>-<repeat>` for repeats 0 and 1. The first contains
`<image>-resources.json`; the second contains `host-resources.json`. Both retain
the corresponding original CPU gate result and the new collector source.

The exact five-file owner-push filter analysis matches only these two scout
workflows. The unchanged strong-RAG model workflow does not match this delta.
The audit parses all 224 workflows and includes their exact source in two small
archives. Child PR checks additionally include blocking CI, architecture,
MemoryCell continuation, ingress review, V8 and CLA workflows. Job-level
conditions and repository policy still control actual execution.

The existing owner PR has 972 changed files. Its PR-to-main checks are based on
the cumulative PR diff and GitHub's actual merge/base tree, not merely these
five new paths. The reference PR scenarios in the audit are explicitly limited
to this source snapshot and delta; they are not a prediction of all checks on
that large existing PR. Recheck those current merge/base sources before updating
the owner. All snapshot workflow bytes are available for review here.

## Admission of a later complete attempt remains separate

The historical hosted sample (run 38224160872, job 114727445770) records a
four-logical-CPU Xeon 8573C with BF16 acceleration, but no RAM or cgroup capacity
measurement. It does not prove a current machine above 8 GiB. Existing OS
records reviewed by the OS owner likewise did not establish that capacity; the
dedicated queued job has not yet produced a runner observation.

After new scouts finish, require exact source/artifact joins and the original
BF16 gate. A MemTotal value or a visible limit above 8 GiB is insufficient when
hidden ancestors remain unattested. Even a complete hierarchy ceiling is only
an observation at that time: available headroom, competing work and the model
job's own actual machine must be checked. A later hosted allocation is not
guaranteed to be the sampled scout machine.

`full112-retry-capsule-v1` remains a blocked draft. A fresh attempt must restore
the same original source, eleven publisher files, input identities, runtime,
40 calibration plus 72 evaluation calls, CPU BF16, two intra-op threads, greedy
decoding, token limits and 180-second bound. It must seal new actual staging,
cost, host and source receipts before generation. This child does not make the
draft dispatchable and does not change those pins. The prior 88-of-112 bounded
failure remains immutable; its 24 unexecuted calls cannot be appended or its
old calibration policy spliced into a new attempt. Such a retry remains exposed
development replication and cannot substitute for independent held-out quality.

The prospective independent-cohort code and admission packets, Reader raw
64-call report, Reader producer fix and all prior evidence packets are unchanged.


## Accompanying job inventory

The original continuation workflow declares seven job instances. Five can execute
models or trained parameters: native-models has two benchmark instances;
native-owner, training-owner and laya-pretrained have one each. Source-inputs
and source-format are the remaining two. Their full unmodified steps, runners,
conditions, resource environment and timeouts are in
`PR_NATIVE_MODEL_SIDE_EFFECTS_V2.json`. The wider job resource catalogue also
follows local reusable workflow references; it does not evaluate dynamic guards
or claim any measured memory capacity.

The current handoff is **child branch and source only**. No PR creation or owner
ref update is requested for execution within this packet. The owner must first
resolve the accompanying original model CI scheduling. No new dispatch trigger
or gate bypass is proposed.

## Replay the scoped logic tests

From this package directory, run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=source/scripts/memory_cell python3 -m unittest -v test_strong_rag_cpu_scout test_strong_rag_host_gate
```

This command uses the included exact source and only the Python standard
library. It does not run a model. Replaying tests creates a new local validation
event and does not turn the historical real-container negative control into a
measurement of the replay host.
