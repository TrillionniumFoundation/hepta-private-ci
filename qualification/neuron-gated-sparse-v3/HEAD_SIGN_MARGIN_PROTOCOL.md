# Conservative Q24 Head sign-margin gate (research-only)

This additive shadow qualification is stacked on **PR #1884** at original
commit `a9fc5178b9db1a9dab71573d347e328232950e`.
The parent PR is frozen while its exact-head GitHub Actions wait in a
repository-wide queue. This branch does not change the selected V1,
Cell Owner, CNS routing, journal format, final-use authority, or main.

## Goal and proof boundary

The `neuron_trained_q24_shadow.rs` model reads physical SHA-pinned
`safetensors`, runs the existing native Q24 V2/V3/SSM/minGRU mechanism,
and applies a **separately versioned** Q24 linear Head to the resulting
native sparse activation `a`.

For an original, exact IEEE-754 binary32 `w_i, b` in [-8,8], define
`Q=2^24`, `W_i=round_ties_even(Q*w_i)`, `B=round_ties_even(Q*b)`, and
native activation `a_i` in [-8Q,8Q]. The real-weight linear readout on the
**identical** activation is
`L_real=b+Σ_i w_i*(a_i/Q)`.
The native integer readout is
`L_Q=(B+Σ_i round_ties_even(W_i*a_i/Q))/Q`.

The exact rational bound is:

- `|b-B/Q| <= 0.5/Q`.
- Per channel, source-coefficient quantization contributes at most
  `0.5*8/Q = 4/Q`.
- Each native Q24 dot-product rounding contributes at most `0.5/Q`.
- Therefore `Q*|L_real-L_Q| <= (9*n+1)/2`, where `n=width`.

A **sufficient**, not necessary, uniform sign invariant is:

    2 * abs(native_Q24_logit_integer) > 9*n + 1

All comparisons use integers, Rust `i128` for the absolute i64 magnitude,
and Python unbounded integers for the independent reference. Equal or smaller
margins produce `QUANTIZATION_AMBIGUOUS_ABSTAIN`. Otherwise the emitted
research status is `ACCEPT_POSITIVE_RESEARCH_ONLY` or
`ACCEPT_NEGATIVE_RESEARCH_ONLY`. None of these statuses is an authority
grant or a production effect decision.

This bound **does not** establish bitwise equivalence with:
- Torch floating-point accumulation (whose finite-precision rounding is
  outside this ideal real-arithmetic proof);
- shared-Encoder, input-normalization, temporal, top-k or inhibition
  differences between surrogate training and native Q24 execution;
- probability calibration, abstention coverage, prospective utility or NDU;
- actual signed selected-model load, persistent checkpoint CAS, crash/reopen
  or generation-fenced final use.

## Executable research acceptance

- Rust physical runner schema:
  `hepta.neuron.physical-trained-q24-mechanism-replay.v3`.
  Each event includes its Q24 logit, margin status and twice-bound in Q24 LSB
  units. Receipt declares the margin as research-only and expressly denies
  final-use authority.
- Independent `head_q24_oracle.py` computes the margin in integer arithmetic.
  Every stored event is rechecked against the physical F32 weights, Q24
  activation, Q24 logit and claimed status/bound. A forged accepted status,
  enlarged/smaller bound or missing event fails the entire model.
- `run_native_physical_matrix.py` executes 20 physical private candidate
  artifacts × two independent Rust processes, requiring identical complete
  typed checkpoint/Head/margin frontiers. The frozen V1 no-change baseline
  remains separately selected and untrained; the 20 candidates are only four
  experimental arms × five private parameter ceilings.
- `native_physical_canary.py` also loads a **valid** all-zero Head, checks
  its events abstain, and retains six deliberately corrupted-model/trace
  rejection probes.
- Hosted CI is required to run exact-source Rustfmt, native Cargo tests,
  strict Clippy, physical 20-model/40-process execution and independent
  Python margin verification. A queued, skipped or cancelled workflow is
  not a PASS.

## Future scientific decision

If the gate runs, independently report *coverage*, wrong-accepted-sign
rate against the ideal same-activation linear reference, calibration and
latency on real future, heldout and OOD windows, with the exact no-change V1
baseline, Cell-clustered uncertainties, negative transfer, and measured
abstention opportunity cost. An accepted sign does **not** mean selected
action/effect approval.

The present branch has no authenticated live A0 Cell Owner census, true
future labels, native CI success, real Q24-to-F32 model-prediction parity,
signed NDU benefit or A4 target-host 64/256/1024/4096 Cell receipts.
**NO_PROMOTION / NO_PRODUCTION_CUTOVER**.
