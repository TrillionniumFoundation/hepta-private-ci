# PFT continuation: diagnostic and process-bound repairs

This continuation starts from `25c2cb2b60446a5f7692945bd154b0d8deb485f3` (#7075).
It preserves the completed PFT studies, frozen protocols, candidate seals, evidence
bytes and original E1–E6 budget ledger. It runs diagnostic and process-transport
regressions, plus retained-evidence verification; it does not restart training.

## Changes

1. A zero effective design has rank zero and no nonzero singular spectrum.
   PFT1 now records `nonzero_condition_number: null` rather than computing 0/0
   and failing strict JSON serialization. Positive-rank calculations are unchanged.
2. The statement-only native adapter collects stdout and stderr in separate
   bounded pipes, each limited to 32768 bytes. It creates its own process group,
   observes the leader with `WNOWAIT`, signals the original group before
   reaping the direct child, and bounds the final wait. The ELF pin, fixed
   commands and unconditional owner-authorization refusal remain.
3. Codespell skips only the two exact immutable `pft2_multihost_*.json.zlib`
   evidence paths named in `.codespellrc`. Their bytes are unchanged. Codespell
   2.4.3 examined only their first 1024 bytes for NUL, then treated the compressed
   streams as Latin-1 text and reported 21 false positives.

The native wrapper controls the process group it creates. It does not claim to
adopt grandchildren, reap them through an external reaper, or contain descendants
that deliberately establish another session. The tests use clearly identified
C ELF fixtures; they do not qualify an actual Hepta model or a real participant.

## Verification

[VALIDATION.json](VALIDATION.json) records exact source hashes, commands, results
and scope. Root executed the new tests; source-review agents did not run these
candidate tests. The rank regression rejects the old implementation at the
zero-rank division and passes the repair, including rank-two and full-rank controls.
Four native-process test methods cover exact limits, both overflow streams,
group termination after overflow/timeout/leader exit, and retained pin/authority
refusals.

A fresh read of the original V2 archives checked 190 bundles, 981 unique members,
168 sealed candidates and all 168 evaluation rows. Protocol, source, candidate,
history and prediction bindings passed. This verifies retained bytes and bindings;
it does not rerun model inference, training or a new held-out test. The optional
runtime-capsule byte check and external Git-anchor existence query were not
requested by that invocation.

The official formatter only dispatches its configured source families.
Qualification Python and this configuration change may produce a scoped no-op;
that outcome is not a formatting certificate for all research Python. Repository
CI has independent gates and must be read at the published candidate.

## Scientific status retained from the completed studies

| Stage | Retained result | Scope |
| --- | --- | --- |
| Identifiability | Endpoint null spaces remain; independent excitation and richer observations can restore rank in the controlled system. | Not arbitrary LLM weight recovery. |
| Direct solve | Quadratic readout updates have a computable central solution. | Frozen representation and common coordinates. |
| Peer consistency | 12 real SmallHCSN two-host cases agree with the independent central solve; maximum relative difference 1.2581e-10. | Two authenticated peers, including real crash/recovery. |
| Structure | Value/risk minus equal-dimensional tanh averages +1.931 percentage points, with 22 negative pairs. | Descriptive fixed synthetic task; three initialization seeds. |
| Circuit | Learned minus fixed recurrent weights averages -0.087 percentage points. | No stable benefit established; topology itself is fixed. |
| Cross-user use | Twelve fresh-process candidate reloads reproduce 24 open test partitions exactly. | Research model reuse; real independent users and native adoption remain unqualified. |

The full matrix completed 168 runs, but only 68 reached the preset 85% test gate.
Dev-selected BP minus the supervised ridge initialization averages -0.206
percentage points. These results remain unfavorable where observed; the repairs
above do not reverse them. See [the completed V2 report](../CLOSURE_V2.md).

## Exact native integration gap

[SOURCE_AUDIT.json](SOURCE_AUDIT.json) binds the review to the original PFT source,
private-ci #7104 and runtime #150/#157. The existing paired loader admits coding
Cells and routed Circuits, not a complete SmallHCSN physical-state profile.
Original-material reads are not training, adoption or final-use receipts. The
reviewed restoration path evaluates the restored parent, so it cannot establish
a second use of the learned candidate.

Completion still requires a real model/profile adapter and original-owner learning
consumer, actual authorized A material, an independent B arriving after candidate
freeze, preservation of prior ability, and two distinct authorized uses of the
same learned candidate. Source hashes, supplied identity fields and synthetic
events cannot supply those missing observations.

For future nonlinear direct solves, the frozen QVI custom backward supports
first-order differentiation and is marked `once_differentiable`. Hessian/HVP or
reverse-over-reverse JVP support needs separate implementation. Its continuous
analytic boundary root also does not by itself prove optimality of the finite
reflected CTMC used for propagation. Neither limitation invalidates the retained
first-order experiments.
