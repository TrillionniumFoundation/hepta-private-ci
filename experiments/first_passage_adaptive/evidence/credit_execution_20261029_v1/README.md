# Selected physics to native resource-credit execution

This mechanical integration run connects the selected A1 v2 physical model,
the existing first-passage simulator, the existing native NDU evaluator, the
frozen native owner bridge, real bounded source reads and a research dual-price
feedback ledger. It does not activate a production Organ Credit API.

## Preserved selected model

The exact A1 checkpoint SHA-256 is
`4b731f8500e13a033a61956aa999cd5dd1e7e36c22937c2cf894ebc4644f3226`.
Its selected final parameters are:

| Training parameter | Retained value | Execution interpretation |
| --- | ---: | --- |
| Upper-barrier drift bias mu | 0.6500460029976326 | Existing lower-distance cell uses drift = -mu with declared offset zero |
| Diffusion sigma | 0.2 | Passed unchanged to the physical cell |
| Independent physical cancellation lambda | 0.0 | Retained as zero; never replaced or updated by the credit price |

The source-bound checkpoint loader verifies the original training/runtime
identity and registration. A selected-model bundle binds the checkpoint hash,
all three physical parameters, the coordinate conversion and the existing
cell's model identity. That bundle enters every NDU snapshot; the original
NDU receipt enters the native owner's committed request. Physical cell
checkpoints independently bind the actual model, random stream and event state.
The selected lambda is kept in the research cancellation-clock contract because
the original cell V1 checkpoint has no cancellation-rate field. This run has
lambda zero and does not constitute a nonzero physical-cancellation validation.

## Explicit resource-credit rule

For a candidate read, the research adapter computes

\[
c_t = 0.05 + \pi_t E_t[\text{read attempts}],\qquad
\pi_{t+1}=\operatorname{clip}\bigl(\pi_t+0.8(u_t-0.25),0,2\bigr),
\]

where the expected resource is one attempt and `u_t` is the actual attempt count
returned by the native owner. The physical read fee is recorded separately
from the shadow resource charge. A price is not a measured hardware energy
cost and is not the physical cancellation rate.

The next NDU snapshot includes the settled price and the prior feedback-record
hash. Actual source results also enter the next snapshot: a found answer makes
further reads infeasible. A completed owner replay cannot update the credit
twice. If a replay arrives without the corresponding local credit settlement,
the adapter refuses to infer a missing settlement.

Both comparison arms use the same selected physical model, initial state,
seed, files, legal actions, budget, deadline and frozen relevance prior. The
disabled arm holds the price at zero. There is one additional native evaluation
at the same observed successor state with the dual price set to zero; it is
retained as an intervention receipt and executes no counterfactual source read.

## Actual results

The independently frozen source is
`d66c47b7693fd70c88d0cbd41d803c6a5c836515447724225d2588a02ad82ec1`.
The five focused provenance/settlement tests passed. This run made eight actual
native NDU calls, including the one evaluation-only price intervention, and
seven original native owner ticks. All thirteen registered mechanical checks
passed.

| Fixture | Executed actions | Actual attempts | Successful reads | Found answer | Physical task return |
| --- | --- | ---: | ---: | --- | ---: |
| Feedback enabled | READ, STOP | 1 | 1 | No | -0.05 |
| Feedback disabled | READ, READ, READ, STOP | 3 | 3 | Yes | 0.85 |
| Invalid UTF-8 source with feedback | READ, terminal ReadFailed | 1 | 0 | No | -0.05 |

After the first attempt, the enabled arm's price increased from zero to 0.6.
At its next decision, READ was still legal, had remaining budget, and had the
same physical and observed task state as the disabled arm. The price raised
its decision cost from 0.05 to 0.65, so native NDU selected STOP. Setting only
the price to zero in the retained intervention made the actual native NDU
select READ. The STOP performed zero source attempts. Settling that zero-usage
decision subsequently reduced the price from 0.6 to 0.4 according to the same
declared update rule.

The invalid-UTF-8 fixture opened the source but returned no successful read.
Its one real attempt nevertheless incurred the base fee and raised the price
to 0.6. All three completed replays performed zero new attempts and left the
credit ledger unchanged.

These results establish the research connection and the effect of a resource
price on legal actions. The enabled price reduced work and failed to obtain
the answer; its physical task return was lower. The run is not evidence of
better task utility, energy efficiency, optimal credit parameters, dual
convergence or general Hepta performance. No seeds, targets or step sizes were
retuned after the run.

## Evidence and reproduction

`SOURCE_FREEZE.json` was written before execution and independently binds this
adapter, tests, original cell/NDU sources, selected training model, frozen owner
build and contract. It does not rewrite the earlier native v3 freeze or
scientific study protocol. `CREDIT_EXECUTION.json` is an exact readable copy of
the run summary. `original_run.tar.gz` contains all 58 original run files,
including physical checkpoints, actual NDU requests/receipts, native journals,
anchor witnesses, credit settlements and source fixtures.
`ARCHIVE_MANIFEST.json` gives every original file's byte count and SHA-256;
all archived contents were re-read and checked. Tar metadata is normalized,
while file contents are unchanged. No compiled binary is included.

To perform a new mechanical run after restoring the retained NDU binary and
building the frozen owner adapter, choose new evidence paths:

```bash
FPT_OWNER_BUILD=/absolute/path/to/native-owner-build/NATIVE_BUILD.json
FPT_CREDIT_FREEZE=/absolute/path/to/new-credit-source-freeze.json
FPT_CREDIT_OUTPUT=/absolute/path/to/new-credit-execution

python -m unittest experiments.first_passage_adaptive.tests.test_credit_execution -v
python -m experiments.first_passage_adaptive.credit_execution freeze \
  --checkpoint experiments/first_passage_adaptive/evidence/train_20261029_v2/checkpoint.json \
  --owner-build "$FPT_OWNER_BUILD" --output "$FPT_CREDIT_FREEZE"
python -m experiments.first_passage_adaptive.credit_execution run \
  --checkpoint experiments/first_passage_adaptive/evidence/train_20261029_v2/checkpoint.json \
  --owner-build "$FPT_OWNER_BUILD" --freeze "$FPT_CREDIT_FREEZE" \
  --output "$FPT_CREDIT_OUTPUT"
```

This preserves the existing serial trusted research boundary: original V1
owns its sparse checkpoint; full FPT, post-I/O task and credit state are bound
research sidecars. The package does not add a native credit API, production
TaskFlow activation, a concurrent transaction protocol, or a power-loss
durability certificate. Native owner calls use separate processes, but the
credit account lives in one Python process with retained receipt links. This
run does not implement or claim cold-process restoration of the credit account.
