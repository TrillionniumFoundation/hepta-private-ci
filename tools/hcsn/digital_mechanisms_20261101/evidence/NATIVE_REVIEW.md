# Read-only native execution review before model seal

Reviewed the prospective runner and its Rust dependency against published source
commit `d3d71246a49664a050e04ef4a44a782350990865`. This review did not execute the
native experiment or rerun the earlier test suite. The reviewer implemented this
subsystem; this is a separate read-only source/provenance check, not a claim of
reviewer independence from authorship.

## Published bytes and chronology

The GitHub connector returned these Git blob identities at the exact source
commit; local `git hash-object` matched all three:

| File | Git blob |
| --- | --- |
| `native_confirmation.py` | `8ab640575d11619c18a67bb01c3429743647814c` |
| `renewal_native.rs` | `fa6ece489ce1e02d3f2411991c58f195586dae2f` |
| `protocol.json` | `b06fe4cfc1d3234c9a3b088395d263aede982403` |

The current runner SHA-256 is
`c4a0b7ac78d34df76c44ec10345fde3a379ecacd6f4c7354960b41b19f60fc96`.
The current native SHA-256 is
`64df3f47465ba0d66451830e8cc845339b8dd67fedd64727b14fab5ca988f2fc`.
The earlier actual verification and retained development source both identify
`d37e25193c318a34f6e79a025b0661c23147a9af840bfcc3bfaa7cfc33cb80ef`.
An actual byte diff found exactly the replacement of the combined `std::fs`
import with two imports. No numerical, event, checkpoint, or CLI code changed.
The prior execution remains bound to the prior source; the proposed new run
will establish its own current-source runtime observations.

## Prerequisites and declared execution

The runner rejects mismatching current source/protocol, unregistered or duplicate
fits, an incomplete full candidate-key set, and a missing/invalid 40-character
`verified_remote_commit`. That field's remote publication must be established by
the external publication/readback workflow; the runner checks its recorded value
and syntax, rather than contacting GitHub itself. It also verifies every selected
model's SHA-256 before and after execution and the source/freeze identity after
execution. Completeness of unselected model bytes relies on the published freeze
creator; this native run only reads the 16 selected model artifacts.

The registered fits are 501, 503, 509, 521, 523, 541, 547, 557, 563, 569, 571,
577, 587, 593, 599, 601. Each supplies
`first_passage_bank__structured_on`. Loading verifies family, fit, structured
terminal mode and sustained drive. Only the resulting physical parameters are
used; neural decisions are not executed by this Rust program.

Eight fixed cases per fit yield 128 trajectory cases. Each case requires three
separate native processes and exactly equal final stdout/checkpoint bytes and
concatenated signed-event traces: 384 planned executions, excluding compiler
version and compilation. Seeds are `870000000000 + 1000*fit + case_index`.
Cases include active states, both initial refractory states, held-constant
declared inputs, external cuts, and horizons 3, 6 or 9. Actual refractory state
at each cut and actual event multiplicity must be counted from the final run;
initial refractory coverage alone does not prove every cut is refractory.

Raw process stdout/stderr, PID, status and child CPU; generator files;
checkpoints; event timestamps; compiled binary; and model/source/binary hashes
are retained. Per-case failures are preserved and make overall acceptance false.
Global exceptions retain a failed-run record after output initialization. Python
module-import and experiment CPU are separately recorded; child CPU includes
compiler-version lookup, compilation and every native attempt. Shared-host timing
is not a deployment latency or energy result.

## Scientific and operational limits

This is the separately declared finite upwind CTMC, with exponential refractory
release and folded Gaussian resets. It is not the frozen neural experiment's
image-bin interval law and is not exact Brownian propagation. Transferring fitted
physical parameters does not transfer task efficacy, learned predictive
calibration or training gradients between those two different processes.

The runner does not open or generate TRAIN/validation/IID/OOD task cohorts. It
does not tune a model or select a successful seed. The 128 cases are runtime
cases, not 128 independent training fits or efficacy observations. The old
numerical reference/MC checks remain separate historical evidence.

The checkpoint preserves an already sampled absolute pending jump and target,
RNG state, voltage/refractory state, logical time and counts. This supports
identical paths across cuts under an unchanged generator. It does not demonstrate
interrupted-write recovery, crash-atomic event/clock publication, restart
authentication or rollback resistance. FNV64 is an accidental-corruption replay
fingerprint. The executable is standalone and does not implement the production
NeuronRuntime/ACK owner, content calls, policy inference, resource charging,
cross-host or cross-architecture determinism, or production authorization.

**Disposition:** source/provenance review found no blocker to running this bounded
prospective experiment after a verified model seal. Execution and its counts are
pending; no native result is asserted by this review.
