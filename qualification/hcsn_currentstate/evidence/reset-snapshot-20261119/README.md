# Event-time reset snapshot repair

The original emission constructors retained the caller's `physics.reset`
tensor directly. A valid reset supplied as an `nn.Parameter` could therefore
change inside an already emitted Atom or Flux when the caller later updated
that parameter in place. The dataclass being frozen did not freeze tensor
storage. This violated the documented event-time reset semantics.

The repair changes exactly the two emission sites to `physics.reset.clone()`.
Each packet now owns its emission-time tensor values while retaining the
ordinary autograd connection. It does not detach the reset or freeze a learned
parameter globally. It also does not promise that an entire live autograd
tape remains valid across arbitrary optimizer in-place updates: these controls
cover forward event-time snapshots and their specified single-gradient paths.

## Actual pre-fix failure and post-fix result

Both controls use a two-state CTMC, lower rate `[1.7,0]`, no upper exit, delay
1/5, and probability/signed-content channels `[1,0]` and `[-.3,0]`. At emission
the reset is `[.25,.75]`; a later in-place parameter update changes it to
`[.8,.2]`. The reference retains the old emitted reset and uses the same new
physics for continuation. Atom is queried at .2; Flux emitted on `[0,.1]` is
queried at .3.

| Control | Pre-fix maximum active-state error | Post-fix error | Post-fix reset aliases parameter? |
|---|---:|---:|---|
| Atom | 0.55 | 0 | No |
| Flux | 0.08598435087198897 | 0 | No |

Both retained reset vectors remain `[.25,.75]` after the repair. The reset
packet VJP against weights `[1,2]` remains exactly `[1,2]`. For the actual
future active score, the independent Atom derivative is `[1,2]`. The Flux
derivative is `[lambda*.1*exp(-lambda*.1), 2*(1-exp(-lambda*.1))]`, since the
original release flux is `lambda*exp(-lambda*u)` for `0<=u<=.1`. Maximum
gradient errors are respectively zero and 1.1102230246251565e-16.

The six existing current-state tests and the two new Atom/Flux regressions
all passed in the local bounded verification. This includes the existing
full-state finite-difference gradcheck and two-layer flux/content gradient
check. That local verification did not rerun the old long-time study, system
identification training, Erlang campaign, or C2 model. The later automatic
hosted run below is a separate experiment on the repaired source.

The two measured child phases used 2.161540 + 3.652792 = **5.814332 CPU
seconds** and 2.190111 + 3.685128 = **5.875239 wall seconds**, below the combined
20 CPU / 40 wall budget. Each process was single-threaded and capped at 4 GiB
address space before numerical imports. Stdout, stderr, source identities,
raw observations, and per-phase resource receipts are retained verbatim.
The pre-fix diagnostic's exit code zero means its observations were recorded;
its nonzero semantic errors and `aliases_parameter=true` are the failure.

## Automatic hosted verification on the repaired source

The existing pull-request workflow automatically ran on commit
`9b20d29391a23fe7f1d4fbb5b1377b10130a1c69`, with repaired kernel SHA-256
`6dfcef11fa6ee43163bb72e661a8aec0c33453cfd2d353668049d2b0ad24be5e`.
Run [44479509254](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44479509254)
passed the six original checks and completed 60 finite-CTMC identification
updates. Its final MSE was `1.748380655708663e-7`, maximum DDE discrepancy
`2.631272977282606e-11`, and maximum probability/signed conservation error
`1.1102230246251565e-15`. The study reported 2.291058704 wall / 2.284129904 CPU
seconds and peak process RSS 407,068 KiB. These timers cover the study after
imports, not total workflow setup or complete fresh-process wall/CPU cost.

The [exact 2,717-byte artifact ZIP](hosted-ci1/artifact-14506983967.zip),
including source head, runtime, study result and both logs, is retained with
SHA-256 `0fed7cee45fcb4aabbe378d762061a0872254f1cbdde11ed5d315cc9300f3096`.
[Its member inventory](hosted-ci1/IDENTITY.json) records exact bytes and hashes.
No model was rerun to verify or archive these originals.

That workflow version did not execute the two new snapshot regressions.
This follow-up adds an explicit, two-test step with its own stdout/stderr and
kernel/test identities in the same uploaded artifact. Its future result is
not claimed here. The original six-check/60-update step remains unchanged.

## Scientific source identity remains distinct

Pre-fix kernel SHA-256:
`fccee9781c86af243c5f691f876d0dec34296edfedc327d6f4a100bcd2def949`.
Post-fix kernel SHA-256:
`6dfcef11fa6ee43163bb72e661a8aec0c33453cfd2d353668049d2b0ad24be5e`.

Pre-fix controls and their runner/tests were committed at
`f83aa353a15` before the repair. The earlier complete-state studies and their
costs remain evidence for their original published source. In particular,
`study_longtime.py` still binds the old kernel SHA and must be run from that
published source when reproducing its original experiment. Its freeze is
not rewritten to accept this repair. `ERLANG_FREEZE.json` is also unchanged;
that campaign imported only the independent Gamma reference and never ran
the complete-state kernel. No old numerical result is reassigned to the new
kernel identity.

The fix is an additive, separately reviewed change stacked on the existing
current-state research branch. It does not change the ongoing C2 execution,
any existing qualification gate, or the attribution of historical results.
