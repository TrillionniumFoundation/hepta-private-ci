# Shared-encoder System2 ablation: development candidate

Source dependency: MemoryCell PR #1452 at
`6008cecc1835de574f0cc4e4980dbd659223bd1e`.
This research extension does not change selected models, native NDU Rust APIs,
main, production owners, objective authority, or deployment configuration.

## What is implemented

`finite_tree_bsde.py` lives under the existing NDU owner and implements a bounded
finite binomial-martingale forward/backward solver. It is a research numerical
reference, NOT native signed-Q32 parity, a continuous Brownian solver, an
existence/uniqueness theorem, calibrated environment uncertainty, or a learned
production FBSDE policy. The forward transition and terminal continuation are
small shared PyTorch networks. The default primary matrix uses zero forward/value
coupling to avoid confounding ordinary tree versus deterministic NDU with another
state-feedback factor. Positive coupling is separately exercised by numerical
tests. General multidimensional centered covariance regression is tested, while
the initial scenario model itself uses a declared scalar two-point martingale.

The forward state is a latent evidence accumulator. The backward profile is
`f=-cost-rho*Y-eta*Z^2/2`, with implicit linear discount. Nonlinear risk is an
explicit research profile, not a claim covering every NDU aggregator. Each
candidate action path has its own chance tree. Chance outcomes use conditional
expectation. The maximization is over admissible action paths, not favorable noise.
Backward continuations come from the SAME terminal critic. The wrong-stitch arm
intentionally replaces interior boundaries by local critic values, and retains
its backward residual even when the terminal residual is zero.

`system2_ablation.py` consumes the existing frozen `Features` interface. Existing
`StemHead` linear/gated heads remain per general/temporal Cell. One shared latent
transition/continuation serves all cells and nodes; the 384->16 configuration has
7,809 trainable parameters. There is no encoder-per-node or model replica per
cell. The native runner reuses `SharedFeatureCache`, strict as-of indexes,
`FrozenPairEncoder`, `TrainingCut`, native support supervision, `EvidenceBundle`,
and `FrozenBundleReader`. It does not concatenate unrelated sources under a fake
single-source label or use benchmark answers to build policy features.

## Matrix and limits

Eight arms: `rag`, `linear`, `gated`, `recurrent`, `tree_critic`,
`ndu_deterministic`, `fbsde_stochastic`, `wrong_stitch_control`.
Linear and gated are separate arms, hence eight instead of six conceptual rows.

The existing development question selection supplies 48 train examples and 32
nontraining examples (selection, retention, test, transfer: eight each). Three
persistent checkpoints (16,32,48) schedule 768 policy/question/checkpoint records.
The four reader conditions schedule another 128 records before policy training.
These corpora and question choices have been previously exposed; `test` here is
a dataset split name, NOT an untouched confirmation set.

Each arm has the same evidence cap (3), candidate proposal cap (4), scalar
operation-count ceiling (100000), and wall-time ceiling at operation boundaries
(30 seconds). Neural calls, backward steps, training pairs, actual reader tokens,
measured latency, and failures are recorded. Operation counts are NOT FLOPs and
a GRU call is NOT equivalent in cost to a Reader call. There is no claim of exact
matched compute, hard kernel preemption, matched training time, or latency
superiority. Compare observed cost frontiers before drawing matched-resource
conclusions. No artificial padding is counted as useful computation.

Frozen and head-only baselines choose up to three evidence windows with a zero
frozen null score or the existing trained Head null score. All policies retain
an empty-evidence alternative; the Reader still generates abstention itself. Search chooses
bounded ordered subsets of the same top-four proposal pool. This proposal ceiling
must appear in interpretation: search cannot recover evidence missing from it.
The recurrent control evaluates greedy prefixes; the tree control enumerates
subsets. The native primary training and all policy arms use the same 0.1-step latent
time integrator as the NDU paths. NDU introduces
cost/discount, then the stochastic arm introduces the declared noise profile.
Arm order is deterministically counterbalanced by question identity.

The continuation training target is ANY native source-support hit. Native positive
windows may be alternatives, not jointly necessary premises. This training signal
must NOT be called multi-hop semantic sufficiency, genuine multimodal reasoning,
or independent correctness supervision. Additional reviewed joint-requirement
training and untouched compositional tasks remain necessary to test that claim.

## Reader diagnosis and trust

Four conditions are no evidence, ordinary retrieval, externally authenticated
human sufficient-evidence claim, and removal of the first externally named
critical requirement. The original `reviewed_bundle.conditions` implementation
validates original UTF-8 source spans and deletes the entire requirement group.
Ordinary retrieval and no-evidence use the SAME FrozenBundleReader and 4096-token
input cap as all policy arms. Answers are not postprocessed.

Human conditions require a separate SHA256-pinned trust registry, a separately
pinned review map, Ed25519 signatures, matching question/frontier, valid identity
time bounds, and a non-revoked independent-human role. The experiment author
`ProfHepta` cannot authenticate as the independent reviewer. The owner must verify
the registry and independence out of band; a signature authenticates bytes and an
identity under that registry, NOT semantic truth. No real reviewer identity, key,
review, verdict, or successful observation is generated by this code. Unit-test
keys are ephemeral and explicitly fixture-only.

Missing reviews are retained as `unavailable`; they are never replaced with a
literal answer-containing source span or a model's self-score. The runner requires
`--development` to proceed to exploratory policy evaluation with missing controls.
It never sets reader adequacy, reasoning superiority, or production acceptance
true. Even complete control generation requires independent answer adjudication.

Optional input arguments:
`--reviews reviews.json --reviews-sha <sha256> --trust trust.json --trust-sha <sha256>`.
Review map keys are question identities; values are `{review, signature}`.
`review` follows `reviewed_bundle.py`'s exact external-review schema.
The trust registry schema is `hepta.system2.review-trust.v1` with `reviewers` keyed
by external identity, each supplying `public_key` (base64 raw Ed25519), `role`,
`revoked`, `valid_from`, and `valid_until`. Do not commit private keys or sensitive
source/review data.

## Reproduction and current evidence

```sh
python -m unittest discover -s scripts/memory_cell -p 'test_system2_ablation.py' -v
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_native_trial.py \
  /path/to/memory-inputs /path/to/pinned-ranker /new/output --development
```

The dedicated workflow installs the existing pinned model environment, fetches the
unchanged historical regression fixture, runs ALL discovered MemoryCell Python
tests, and only then stages native models and runs the development matrix. It
retains partial rows and failure logs with the actual generating commit/tree.
A workflow file is not a completed run. A green mechanics job is not model efficacy.

At authoring, 28 local mechanics/protocol tests passed under CPU PyTorch 2.10.0 and
cryptography 46.0.4; the hosted environment remains the repository's PyTorch 2.5.1
profile and must pass separately. No local pretrained model download/native Reader
execution was possible in this working environment. The separate exact-rational
boundary probe's six tests were rerun; it is mathematical evidence only.

Remaining evidence: completed exact-head hosted regressions and all native rows;
real human controls and independent answer judgments; observed compute-matched
comparisons; genuine multimodal inputs and joint-premise learning; out-of-family
confirmation and retention confidence. No superiority or emergence is claimed.
