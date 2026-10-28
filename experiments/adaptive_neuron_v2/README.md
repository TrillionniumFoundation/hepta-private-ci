# Adaptive spiking owner and resource-credit study

This is a new registered batch above the immutable `free_boundary_neuron`
study. It connects task-trained hard spiking inference, a finite-horizon
stopping decision, actual native-owner state transitions, conserved terminal
credit and an episode-level resource controller.

## What is trained and deployed

The six causal inputs feed eight bipolar integrate-and-fire cells and a
task-trained readout. Three arms share initialization, evidence, supervision,
step counts and weight-update budgets: a fixed logistic surrogate, the fixed
first-passage surrogate, and the first-passage surrogate with jointly trained
drift, noise and cancellation parameters. A fixed soft query objective
differentiates through one actual hard-SNN support adaptation. The analytic
mixed reverse pass includes clipping and projection. This is a one-step
bilevel derivative of an explicitly specified update rule, not the classical
derivative of a hard spike or a gradient through the entire training history.

The native port executes the trained hard network. A finite-grid Bellman
boundary converts its current probability readout into continue, positive,
negative or abstain actions. The original `AgentdNeuronOwner` applies those
actions, writes its journal and witness, and stops observation purchases.
The raw-belief DP and myopic baselines see the same information and execute
zero neural cells. The task is discrete Bernoulli evidence; no diffusion
approximation is silently treated as its exact transition law.

After every episode, measured work and observed reward update a durable
resource balance and price. The original `finalize_credit_batch` validates
the terminal organ allocation and conservation. The resource account is a
research sidecar with DENY_ALL authority and a local synthetic permit; it
does not append to the authenticated production `LedgerWriter`.

The surrogate cancellation parameter lambda and the resource shadow price
are distinct. The former changes the learning rule; the latter prices
future execution and enforces budget admission. This separation prevents
changing the task environment to manufacture a training improvement.

## Registered comparison

`PROTOCOL.json` fixes five screening and ten confirmation seeds, three
training arms, 128 support/query updates per fit, and final-checkpoint-only
deployment. Screening does not select or revise the method. Confirmation
deploys nine policies in two domains: 180 independent organ sequences,
16 episodes each, 2,880 episodes total. Every policy sees the same complete
evidence streams and can buy only causal prefixes.

The two primary OOD contrasts are joint-meta/live-credit minus
fixed-parameter/live-credit, and joint-meta/live-credit minus
joint-meta/frozen-credit. Independent seeds are the statistical units.
Two Bonferroni-adjusted paired 97.5% intervals must each have a lower bound
above 0.005 to support its corresponding superiority claim. Functional
closure does not require, and cannot imply, a positive scientific result.

## Execution and evidence

Commit all executable inputs first, then create a new source seal:

```sh
python3 -m experiments.adaptive_neuron_v2.provenance freeze /absolute/new/SOURCE_SEAL.json
python3 -m experiments.adaptive_neuron_v2.batch \
  --source-seal /absolute/new/SOURCE_SEAL.json \
  --destination /absolute/new/scientific001 \
  --build-root /absolute/new/sealed-builds \
  --compiler /absolute/pinned-rust-toolchain/bin \
  --vendor-root /absolute/checksum-verified-vendor
```

The Linux research driver requires the pinned NumPy/SciPy versions in
`requirements.txt`. Its timing encloses subprocess startup, source and
dependency checks, two independent builds, all 45 fits, independent
checkpoint audits, native execution, all 2,880 cold replays and statistics.
The two binaries must have identical bytes. Every scientific native build
and execution must match the source seal and trained checkpoint.

Progress checkpoints are published before scoring summaries. Receipts are
exclusive and failures stay visible. Independent audits reconstruct evidence
streams, optimizer updates, parameter changes, native actions and resource
accounts; changing a receipt and its containing hash is insufficient to pass.
Three finite-difference scales re-solve the complete one-step adaptation at
each final meta checkpoint. No missing, duplicate or unregistered case can
enter statistics.

The complete natural raw directory and exact binary are delivered as a
separate downloadable artifact. Source, protocols, small receipts and
statistical summaries stay in Git. Archive and transfer costs are separate
from the measured batch. Nested CPU/timing receipts are not added twice;
operation counts are summed and allocation peaks use maxima. Budget work
is a stated resource proxy, not measured Joules.

Development checks, failed attempts and portability evidence remain under
`results/development`. Source editing and earlier unmetered engineering
setup are explicitly outside registered execution totals. Historical results
and seals retain their original commit identities.

See `learning/THEORY.md` for the derivative and boundedness argument and
`owner/README.md` for native replay and authority contracts.
