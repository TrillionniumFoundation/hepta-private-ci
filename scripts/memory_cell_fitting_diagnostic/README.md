# One fixed fitting diagnostic

This separate development diagnostic distinguishes first-token fitting from
save/load and teacher/prefill differences after the exposed retention screen.
It is not a new retention arm or an eight-round experiment.

The single registered configuration uses the pinned SmolLM2 base, seed 24029,
rank 8, completion CE, learning rate 0.001 and the original 256-update schedule.
A fresh local synthetic source owner issues new cell/source identities and
disjoint roots. The old textual scope and forty training questions are retained
to reproduce the token inputs. No old withdrawn checkpoint is loaded, and no
old source owner's withdrawal is reversed.

The complete reservation is 376 actual forwards: 256 training, 40 in-memory
teacher-forced, 40 reloaded teacher-forced, and 40 reloaded prompt-only prefill.
No autoregressive generation is called. Public forward hooks verify actual
inputs, target masks, order, cache mode and per-stage quotas against independently
registered token arrays. Entered and completed calls are durably logged
separately; incomplete calls remain charged. The two fresh children are serial,
limited to two CPUs, and share a 600-second whole-run deadline. New retained
artifacts must fit within 5,000,000 bytes. The runner permits one attempt and no
budget refund. A failed child prevents dispatch of the following phase.

Teacher observations include the source target in the input by definition.
Their first target token is predicted from the prompt prefix; later teacher
positions are not a free-generation quality measurement. The saved/reloaded
comparison hashes all supervised logits. The paired prefill comparison records
the full first-token logit-vector maximum absolute difference and argmax.
Small numerical differences alone do not prove a cache or serialization defect.
These measurements cannot establish an intrinsic rank/capacity limit, future
retention success, long-horizon quality, or production authority.

Run the pure checks before freezing; they do not load a model:

```sh
python -B scripts/memory_cell_fitting_diagnostic/test_fitting.py
```

After explicitly reserving the model lane, register a new output directory with
`fitting_protocol.py --out OUT --screen COMPLETED_SCREEN --base PINNED_BASE`.
Retain the printed canonical protocol digest, then invoke exactly once:

```sh
python -B scripts/memory_cell_fitting_diagnostic/fitting_runner.py \
  --out OUT --protocol-sha256 FROZEN_DIGEST
```

Source pins cover the current formatted shared source closure and this directory.
The final reader uses the real local publication/current-owner path, then revokes
one newly issued source and verifies both revoked-key and stale-cell reads make
zero callbacks. This is a local research authority; external production authority
and the complete future task gate remain open.
