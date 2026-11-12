# CfC reference and qualification

The NumPy challenger implements the default cell equation from
[ncps cfc_cell.py at commit 695ec22d7d1831f2ced67346ef7d2f08c525bd47](https://github.com/mlech26l/ncps/blob/695ec22d7d1831f2ced67346ef7d2f08c525bd47/ncps/torch/cfc_cell.py),
with `backbone_layers=0`. It uses the existing PRED-1 action-conditioned head
and Adam state. It does not copy the ncps initializer.

| Input | SHA-256 | Git blob |
| --- | --- | --- |
| Exact upstream cell source | `79dcc1cbb3b6898dc2310e9086a2e031e31cbaeb129d69adcbf45eaa16d6b74d` | `564885f723882dc4b9f8d3046ada152474eb9294` |
| Upstream Apache-2.0 LICENSE | `aedff72c6a199d144f3425c92e2727292785609432d243347b5acaca0450ff31` | `1bfc00af83c2e8f07aaedb844af4dd1432a13b7c` |

Retrieve both files from that same commit and preserve their exact bytes.
The probe refuses mismatched bytes before executing the reference.
[The license is available in the same pinned repository revision.](https://github.com/mlech26l/ncps/blob/695ec22d7d1831f2ced67346ef7d2f08c525bd47/LICENSE)

## Reproduce the numerical comparison

Use an environment with NumPy and PyTorch, then run from `scripts/`:

```sh
python -m hepta_cells.cfc_reference_probe \
  --reference /path/to/pinned/cfc_cell.py \
  --license /path/to/pinned/LICENSE \
  --output /path/to/new/parity-output
```

The output directory must be new. No training, acquisition or model selection
occurs. Torch is imported only by the explicit probe entry point.

The probe copies identical explicit weights and biases into both implementations
in float64. It checks three seeds with batch sizes 1, 2 and 3, hidden width 3,
four observations, elapsed times 0, 0.001, 0.2 and 20 seconds, and nonzero previous
states. The final input feature supplies elapsed time both as an ordinary feature
and as an explicit `(batch, 1)` argument to the official cell.

The comparison covers every transition, all parameter gradients through the
four-step coarsened-label loss, and finite differences for every input and
previous-state coordinate. The time derivative at zero uses a second-order
right difference. The direct official cell avoids the separate sequence
wrapper's squeezed-time broadcasting behavior.

`REPORT.json` retains pass/failure, source hashes, versions, tolerances and measured
costs. `ARRAYS.npz` retains explicit weights, inputs, outputs and gradients.
The exact upstream source, license and tested Hepta sources are copied beside
the report. Reported wall/CPU time begins after Torch import and ends before
final artifact serialization.

A pass establishes numerical agreement for these cases and this mode. It does
not establish matching initialization, optional mixed-memory behavior,
performance under every shape or dtype, task benefit, or promotion eligibility.
Zero elapsed time is not an identity transition in the default CfC equation;
duplicate-event handling remains the owner's responsibility.
