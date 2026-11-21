# H1: shared value/risk information pilot

Three arms use identical fixed HCSN dynamics, feature width, eligible readout mask,
train-only normalization, ridge objective (.001), train/dev permissions and zero
NoUpdate selection. `same_generator` retains all features. `drop_value_risk` zeros
last/mean call/risk (effective rank can fall; this is an ablation).
`ordinary_tanh` replaces these four columns with last/mean outputs from the two
explicit input projections in ablation.py. Neither projection accesses labels.
Every arm has access to the same task description and complete feature banks.

The campaign computes each complete flow/ordinary feature bank once and records
that actual shared cost. Each arm's standalone cost lower bound includes the
full bank cost; summing those lower bounds is not the campaign's elapsed work. This holds
feature computation fixed to test incremental information. It does not test
whether dropping a value solve or replacing the entire encoder saves wall time.
All other dynamics, features and readout dimensions remain identical.

Use `python -m qualification.hcsn_confirmatory_v1.ablation freeze|fit|final` with
the same CLI arguments as stage A and a new `hcsn-feature-confirmatory-v1/`
namespace. Source, backend and protocol freeze precedes generation. Selection SHA
must be bound externally; final consumption is exclusive and failures are retained.
Each of four tasks has three paired training seeds, 48 train/24 dev/48 final IID
and 48 final shifted-clock examples, length 12. Shared fit+final budget is 180s;
operation-boundary accounting must be accompanied by the root's process watchdog.

Primary contrast: `same_generator` minus `ordinary_tanh` MSE per task and clock.
The drop arm is a diagnostic contrast. Report all three seed differences/ranges
and all failures; do not pool task scales, pick a final winner or claim significance
from three seeds. The independent generators and clock-shift limitations are in
PROTOCOL.md. Adaptation cost omits unknown human/assistant design costs; no total
training-speed advantage can be inferred from this representation pilot.
