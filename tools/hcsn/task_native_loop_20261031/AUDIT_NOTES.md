# Independent native loop audit

The new factorial columns are **fixed posterior boundary** and **full task-value
control**. They are not a relabelling of the earlier myopic/value columns. The
ordinary exact posterior and fitted-observation-law DP remain strong references.

The audit uses fresh native subprocesses. The host supplies a public manifest,
frozen content and policy identities, a continuation count and an acknowledged
checkpoint; it does not choose task actions or provide posterior/driver values.
Constructed constant critics are explicitly labelled policy interventions on
identical fresh public prefixes. Existing checkpoints are never silently rebound
to new policies. Tests using these critics establish mechanisms, not efficacy.

Required causal sequence: public prefix → native legal action decision → READ
authorization → actual packet access and frozen FullHX → observed posterior →
task/cell/cost checkpoint. Missing or modified unread packets cannot affect an
earlier decision; labels are absent from the native process input.

Task semantics are checked independently of the executor. STOP has no duration;
READ/SKIP reserve the final submission slot; FIRE consumes up to two available
public durations, advances the job and resets the posterior/cell. Failed reads
retain incurred query and latency charges. Task durations and measured hardware
time are different quantities.

Recovery evidence must contain distinct real process IDs and exact semantic
continuation, not an in-process JSON round trip. Tests cover acknowledged action
boundaries; they do not establish arbitrary-crash atomicity or external rollback
resistance without an externally retained acknowledgement.

Every new native invocation records child-process user+system CPU, wall time,
owner loading, and the available artifact-loading/action-stage measurements.
Continuous and per-boundary restarted executions retain their complete startup,
loading, I/O, failure and persistence costs. A single development-pair overhead
comparison is not a statistical performance claim. The first genesis-failure
attempt and its early direct-recovery diagnostic preceded the process-CPU
instrumentation; their unrecorded CPU remains unknown rather than zero.

An intrinsic-boundary intervention that changes latent probabilities or counts
but leaves the actual READ path unchanged **fails the causal content gate**.
A constructed sensitivity witness does not prove that a trained model improves
quality or net utility. Held-out efficacy and complete CPU costs are separate
gates, and unmeasured energy remains unknown.

The current task Bellman oracle is exact for its TRAIN-fitted confusion law.
Fitted-law regret and realized return are reported separately; decoder-law
misspecification must not be reassigned to controller approximation error.

Independent matrix-exponential/gradient agreement validates the declared finite
CTMC. It does not qualify its coarse grid as equivalent to continuous Brownian
first passage. Discretization error and gradient-implementation error are
separate evidence requirements.

## Recorded execution

The original `evidence/causal_audit` attempt exposed a real genesis recovery
failure: an inspection-only checkpoint could not be reopened for its first
action (`BootstrapRequiresEmptyJournal`). Its process records and original
audit source are retained. The separate early direct-recovery diagnostic showed
that recovery after an actual completed READ already worked; it did not waive
the genesis failure. Native build attempt 03 repaired that case and added a
regression for unknown nonempty genesis journals.

The fresh `evidence/causal_audit_attempt02/REPORT.json` then passed all 50 native
invocations against the rebuilt binary. It includes both state families, all
four native-selected actions, causal pre-read checks, acknowledged recovery,
identity rejection, failed-read charging, and positive/negative boundary
mechanism controls. Total native process CPU was 0.377127 seconds. One-process
versus six-process recovery CPU was 0.016966 versus 0.046958 seconds for ordinary
state, and 0.018965 versus 0.046844 seconds for distribution state. These are
development audit costs; they establish neither performance superiority nor
trained-policy utility improvement. The raw process records retain every
measured load, action, persistence, failure and rejection cost.
