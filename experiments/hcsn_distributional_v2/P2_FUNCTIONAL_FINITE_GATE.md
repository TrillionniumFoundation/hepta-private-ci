# P2 expected event/reward accumulation finiteness gate

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false /
production_activation_allowed=false.** A narrow post-reduction finite guard;
not a neural-memory improvement, event-physics certification or production pass.

## Source-exact negative witness

Parent #4434 head: `760364ca5fd7c9df608dd8eca34293ee01ab13fc`.
Original source blob: `stable_probability.py`
`968da5fb2297e1f5b8ffbe7687f8723381942100`.

For binary32, the otherwise permitted input
`p=[0.50000006,0.50000006]` has measured mass
`1.0000001192092896`, within the declared `8*eps` input guard.
With identity transition and per-state event vector
`[float32_max,float32_max]`, the original function returns `events=+inf`.
With signed reward vector `[-float32_max,-float32_max]`, it returns
`reward=-inf`. All the **input tensor entries** are finite; the error
occurs after multiplying and accumulating. The analogous permitted
near-unit-mass binary64 input also overflows.

This is a deliberately adversarial numeric input-domain witness, not a
claim that normal physical event rates approach these magnitudes.

## Fix

Check `torch.isfinite(expectation)` **after** the actual weighted sum.
Reject a nonfinite accumulated event or reward expectation with `ValueError`.
The original dtype, operator semantic tag, batch-shape gate, nonnegativity
policy, mass budgets, autograd and finite-value result are unchanged.
Never silently clip an expected count or reward.

## Actually executed local CPU evidence

Python 3.13.5, PyTorch 2.10.0+cpu; no CUDA machine.

- Exact original parent blob `968da5fb2297e1f5b8ffbe7687f8723381942100`
  reconstructed locally by matching `git hash-object`.
- Existing `test_probability_functional_shape.py` original source blob
  `cc4b91f57cfe064129a34c0105fa0d6f5c5a06d3`
  independently matched.
- On original source, new regression module **fails with 4 assertion
  failures**, exit 1, including both binary64 functionals.
- Patched source + unchanged existing five tests + four new tests:
  **9/9 PASS, 0 skipped**; `compileall` passes.
- New tests include float32 event and reward overflow rejection, float64
  event and reward rejection, and exact maximum-finite binary32 edge
  retention with autograd.

Reproduction:

```sh
python -m unittest -q \
  experiments.hcsn_distributional_v2.test_probability_functional_shape \
  experiments.hcsn_distributional_v2.test_probability_functional_finite
python -m compileall -q experiments/hcsn_distributional_v2
```

Committed Git blobs match locally executed bytes:
- `stable_probability.py`: `2ebf722bb89941ddfbf9f30a3252f5434e6859d4`
- `test_probability_functional_finite.py`:
  `6b3c8a39f4be86e7b273eb69304101c3a4320fef`

## Limits

This only guards the finite profile's event/reward *expectations*, not
actual spiking, random realizations, Poisson-tail certification, exact
operator construction, long-memory training or model selection. Genuine
multi-firing Selective Copy, MQAR, overwrite, irregular timing, and
repeated reset tests remain open (P2). So do P0 full HX/coupled QVI,
P1 controlled mechanism gain (registered 0/4), P3 text-image-audio-video,
P4 native Rust/GPU 64–4096 Cell and power/recovery, and P5 equal-budget
trained backbone superiority. No CI or full-repository checkout claimed.
