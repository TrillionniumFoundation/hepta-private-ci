# Execution06 supervisor and measured launcher

This is the explicitly registered continuation of the execution04 operating protocol. It admits one verified historical A17, executes thirteen new jobs, and retains fourteen logical jobs and seventeen fresh durable barriers. It does not execute a scientific job itself or contact Library. Root still services every actual archive request with the real external service.

The implementation and validation follow a workspace interruption. Owned/controller dependencies are marked CONTEXT_RECONSTRUCTION and have new tests. The new supervisor is a narrow adaptation of the exact restored public execution04 source; the old source remains unchanged.

## Entry and configuration

The sole production entry is `daemon_bootstrap.py --config PATH --expected-config-sha256 SHA --execute`. Without `--execute`, the bootstrap, supervisor and measured launcher validate or prepare metadata only. Direct `wait4_launcher.py --execute` is rejected. The detached bootstrap alone owns the measured production launch. Fixed roots are fullstudy_recovery06_git, fullstudy_execution06_ops, fullstudy_execution06_durable_raw and its `_cas` sibling under the registered base. The pipeline config schema is `hepta.fullstudy.execution06.configuration.1`, episode `execution06_detached_20261030`.

In addition to the original input descriptors, config requires daemon_bootstrap, wait4_launcher, producer_config, import_receipt and producer_map. Producer config uses schema `hepta.execution06.producer-config.1` and the same episode, with exact producer_map/import_receipt descriptors and the full fresh_registration object. The latter binds the current source root/commit, raw root, profile, primary source freeze, protocol and runtime. Supervisor verifies current paths/profile/commit and the import; producer adapters independently verify their full seed map before use. Current operational source helpers must match the registered Git commit. The frozen execution04 durable_archive and external engineering wrapper retain their original bytes.

## Fresh input and A17 barrier

Before creating supervisor_run, ControllerCore revalidates the actual imported bytes and origin. RAW may contain only the exact materialization list plus IMPORT_STARTED and IMPORT_RECEIPT. Extra files, extra directories, links and a nonempty CAS are refused. New wrapper/resource/cwd/archive work directories must be empty. A prior supervisor run cannot resume or be overwritten.

Only A17 initially activates. When its controller IMPORT and RESULT appear, supervisor compares both entire objects and the queued job with the verified ControllerCore properties. Its original completed profile/freeze remain authoritative. New A17 START, operation START or log files are forbidden. Closed archive input includes its stage, original operation COMPLETE, complete import provenance subtree and new explicit IMPORT/RESULT; no fabricated worker receipt is created.

This imported job is the first of the seventeen durable barriers. The new episode actually archives it and waits for a new verified ACK. An execution04 ACK cannot admit A29: the next activation requires the current episode, sequence and completed prefix. Every subsequent job retains the original completion/profile checks and required START/log artifacts.

## Shared resource policy

Before any wrapper starts, supervisor exclusively writes `OPS/supervisor_run/START_POLICY.json` with schema `hepta.execution06.supervisor-start-policy.1`, episode, source/raw/ops paths, exact cwd_policy descriptor, original started_monotonic, deadline_monotonic=started+43200, original OOM baseline and actual supervisor identity.

That policy identity is the integer-field `{pid,parent_pid,pgid,sid,start_ticks}` contract consumed by the new wrappers. The legacy STATUS and outer OwnedChild process identity shape remains `{pid,start_ticks,process_group,session,state}` so the archive liveness verifier retains its original interface. These are explicit separate schemas, not interchangeable aliases.

All original resource gates and loop semantics remain: 1,879,048,192 B admission RAM, 2,415,919,104 B admission disk, three consecutive samples, original sampling periods, archive RAM/disk/inode guards, OOM baseline, absolute 12-hour window, ordered fourteen-job loop, registrations after A43 and R43, 26 analysis seals and 30 finalizer seals. The controller independently retains its 300-second admission rule and original scientific decisions.

## Finalization and operational evidence

Finalization goes through the registered cwd wrapper with kind=finalizer and evidence_id=verification06. Literal restore and manifest verification remain original. The final archive adds closed wrapper_runs and resource_backpressure trees. Their fixed seventeen tokens are controller, thirteen actually executed jobs, analysis parent/report, and finalizer. Each must have exactly one actual process directory with START and COMPLETE, no FAILED. Controller and analysis-parent ownership must prove respectively thirteen and one returned direct children, all real wait4 exit zero and complete accounting. There is no A17 wrapper.

Pipeline completion retains schema `hepta.fullstudy.pipeline-completion.4`, explicitly declares one imported and thirteen newly executed jobs, and assigns historical A17 science cost once to execution04. It requires all seventeen fresh durable stages. Root still closes primary COMPLETE, outer wait4 and terminal metadata after supervisor exits.

## Measured launcher

The new launcher uses the owner adapter around the same actual supervisor argv/cwd/environment and new-session setting. It preserves full-entry-to-exit wait4 even when outer START publication fails. Failure closes the real child with the original fifteen-second TERM/five-second KILL allowance and retains the original exception plus the owned closure. A zero exit with a missing/invalid primary seal retains its actual measured usage in WAIT4_PRIMARY_INVALID and fails verification.

Normal outer receipts use `hepta.fullstudy.execution06-outer-wait4.1`. They include the supervisor and descendants it waited for, while launcher own CPU remains a separate scope. Historical A17 science and external root upload/readback are not added to that measurement. Inner scientific/driver/archive/owner usage is attribution within the outer observation, never an additional total.

## Current verification

The actual execution06 root behavior run passed 51 tests covering ancestry, controller import, producer, supervisor and archive metadata. Its measured receipt is `/workspace/scratch/178ced6a501f/execution06_recovery_20261030/measurements/root_behavior_checks01/WAIT4.json`. The separate current detached-launch suite passed 79 tests, including real tiny processes, and a separate two-host-exec experiment verified the same measuring parent survived its originating exec before later writing the real supervisor wait4. Exact descriptors and scope are in `DETACHED_LAUNCH_VALIDATION.json` in that recovery directory.

These tests do not establish scientific outcomes, production remote transfers or full completion. Older execution05 verification records stay in their original namespace and are not relabeled as current receipts.
