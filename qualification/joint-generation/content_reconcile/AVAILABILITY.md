# Saved TRAIN information available for code-pair reconciliation

This is a read-only field/endpoint inspection. No softmax, encoder/head forward,
decoder observer, Q construction, repair, optimizer, training or formal evaluation
was executed. The current weak-head-anchor proposal is paused and unrun.

The inspector checked250 owned NPZ inventories:142 from
`runs/content-control-train-r2-20261023`,108 from
`runs/content-block-train-v1-20261023`. It read only those runs' existing TRAIN
receipts/output samples and the pre-adaptation feature-cache shapes. Its
[source](../runs/content-reconcile-availability-20261023/inspect_saved.py) and
[full result](../runs/content-reconcile-availability-20261023/availability.json)
bind the inspected artifacts by SHA256. CPU before the receipt was.183743701s;
this is separately reported R&D inspection cost, not a model-build credit.

## What can be recovered without a new model computation

The saved per-row `consistency` is an exact expectation of decoded semantic
agreement under the original independent head law. Therefore `1-consistency`
gives the expected *decoded semantic* contradiction rate on all768 inner TRAIN
rows per seed, rather than a Monte Carlo frequency from a few PNGs.

| Original strong model | Seed11 | Seed23 | Seed47 | Mean |
|---|---:|---:|---:|---:|
| H | 1.928198% | 2.187600% | 1.854520% | 1.990106% |
| A | 1.683337% | 1.928871% | 1.540982% | 1.717730% |

The newer joint/alt models' existing semantic rates are also in the JSON; they
are not selected as a weaker comparison for this probe. H/A each has only ONE
retained sampled inner output per seed (all are the first inner row). These six
samples all have equal raw code11/11. That is neither a population contradiction
estimate nor evidence that all original draws agree. Other batch outputs were
retained as hashes/costs, not full probability vectors or all sampled pairs.

`consistency` was computed using the external decoded observer. It is an
evaluation endpoint and is **not legal input to the proposed runtime repair**.
Raw code disagreement `1-sum_c p_c q_c` only equals this semantic rate if the
frozen decoder's complete code-to-semantic mapping is identity. The few stored
PNG samples do not certify all12 decoder codes. No such identity is assumed
from sampling accuracy or training intentions.

## What is missing for the strong dense models

Selected H/A archives contain weights and endpoint metrics, not full p/q,
original-head greedy argmax pairs, joint outcome Q, or the raw fixed R tensor.
`greedy_joint_success` is one correctness indicator, not the original argmax
codes. Sampled `choices` are not greedy decisions. The model weight keys `text`
and `image` are parameter matrices, not head probabilities.

The few scalar expectations do not identify the12-way probability vectors,
confidence margins, legal action frequencies or repaired joint law. Exact Q,
rho1.5 CE and repaired greedy outcomes cannot be calculated from those endpoint
metrics alone. A new fixed TRAIN forward could reconstruct p/q from the saved
weights/inputs without retraining, but it is new billed work and has NOT been
run here. Original R can be deterministically reconstructed from the frozen
decoder/original observer source, but this is also new offline billed work;
the observer and target must never flow into the runtime action rule.

## A useful distinct cache: base logits, not adapted-model probabilities

For each seed11/23/47, `features-SEED.npz` persists fit/inner h,t,i:

- fit_h[2304,32], fit_t[2304,12], fit_i[2304,12];
- inner_h[768,32], inner_t[768,12], inner_i[768,12], all float64.

These t/i are logits of the supervised **pre-adaptation base**, bound to
`base-SEED.npz`. The original softmax could recover its legal p/q with no new
neural forward, but that operation has not been run in this inspection. Those
logits cannot stand in for the much stronger adapted H/A probabilities. A
base-only mathematical fixture, if ever authorized, must be labeled separately
and cannot establish a strong-baseline decoding win.

The [fixed draft](PROTOCOL_DRAFT.md) consequently binds the original strong
H/A weights and accounts for the missing probability capture. Existing fields
establish a semantic inconsistency opportunity; they do not establish the
proposal's information value, quality improvement or deployment savings.
