# Post-study selected-policy moment accounting diagnostic

This is an accounting and estimand repair after the completed natural studies. The actor, all generator checkpoints, continuation, original reports and the two durable evidence parts are unchanged. The 16 calibration video sources were previously consumed; this is not fresh qualification and it does not claim a policy or generation-quality improvement.

## What was repaired

The original scalar calibration bias pooled events/draws, although the NDU population CE used equal original-video source mass. Sources have different event counts. In addition, the candidate heads were fitted to candidate generation returns, without the complete actor's online feature/selection overhead. A candidate head is therefore not automatically a critic of the whole deployed selected policy.

`natural_selected_critic.py` reloaded the exact frozen seven-candidate actor and checkpoints, then executed the complete policy on the original 27 development events from eight sources, with two newly fixed draw IDs per event. Every one of the 54 traces includes online features, actual actor selection, selected generation, PNG/WAV/FFV1/UTF8 serialization, actual readback, scoring and measured self/child CPU cost. All 216 saved media hashes were independently verified.

The new positive critic is `softplus(linear public-context features)`. It is fitted directly to `exp(-gamma * actual_net_return)` with equal source, then equal event, then equal draw weights. It neither exponentiates a mean return nor factors quality and cost under an independence assumption. The critic has 400 predeclared Adam steps, learning rate 0.01 and ridge 0.001; no calibration values enter fitting or hyperparameter selection. It is not deployed to select new actions.

## Descriptive calibration on the existing independent-source records

| Estimate | Actual moment | Predicted moment | Bias |
|---|---:|---:|---:|
| Original event/draw-pooled report | 0.428344907 | 0.396425673 | -0.031919235 |
| Same original candidate heads, corrected source weights | 0.413589142 | 0.390848094 | -0.022741048 |
| Complete selected-policy critic, corrected source weights | 0.413589142 | 0.402787124 | -0.010802018 |

The new critic's source-weighted RMSE is 0.194406492, versus 0.244047288 for the original selected candidate head. Its descriptive source-bootstrap 95% bias interval is [-0.089190775, +0.069387419]. These estimates quantify this retrospective diagnostic; they do not provide a new generalization or efficacy claim. The original qualification CE tables were already source-weighted and are not changed by this correction.

Average complete hot-policy CPU per new development draw was 0.229905 seconds; online actor features/selection contributed 0.000704 seconds. One-time model loading is recorded in the total diagnostic CPU, outside the hot per-episode cost. New critic prediction overhead would have to be charged if it were later inserted into a deployed policy.

## No rigorous tail certificate

The existing profile has no enforced future upper bound on total CPU cost. Observed cost maxima are not future support bounds. Accordingly `tail_certificate.issued=false`, `rigorous=false`, and `enforced_future_cost_upper_bound=null`; the finite-support API remains closed. Positive moment estimates and average calibration cannot certify rare extreme tails. The bootstrap intervals here are descriptive and are not substituted for a rigorous certificate.

## Bindings

- Original actor SHA-256: `87b0e6c3fcbe93a462fd610bfa00e91420eb27eb62b819335f451846f2ce8ff8`.
- Unchanged evaluated profile: `12ca5adbc8829ef063984e6c0c0f3006c6616cf2965eb515a56b63ddba87d9e7`.
- Unchanged continuation: `4abf66314111744789a6fb75cff2e063816e36f872432b9933c48f4b87f044dd`.
- New critic file SHA-256: `0a7e95b20ce269e170d749c4ffd37528477efa7467bf449981e76682436785af`.
- Diagnostic protocol SHA-256: `68ac3b150dcddece7a043176ae2321e2a988e522b28fa5298a9613340327e747`.

The protocol and critic bind every generator checkpoint file and parameter hash. The original models were frozen during critic fitting and their parameter hashes were checked unchanged. Full development traces and their delivered media are in the separate supplemental evidence archive; the original two archives remain immutable.

```bash
python -m experiments.multimodal_output_portfolio.unified_20261028.natural_selected_critic \
  --root /path/to/restored/natural/evidence \
  --output /path/to/new_explicit_replay_directory
```
