# Shared Stem → Specialized Neuron Cells → NDU System 2: Architecture Decision (2026-10-15)

**Research-only / DENY_ALL.** This child study is stacked on #2065 and its
inherited #1923 P0–P6 research. No production Neuron/NDU worker, registered
selected model, Q24/Q32 wire, FinalUse, CNS, Reader, objective or blocking CI is
modified. This report makes no new pretrained forward, natural-task, FBSDE
global theorem or future-window outcome claim.

## 1. Decision and actual evidence

Prefer physically shared immutable Encoder residency and individually
addressable lightweight Cell Heads as the architectural default. Run the
smallest adequate set of actively selected Cells, not 4,096 mandatory
forward passes per question. Treat FBSDE/NDU as an optional **cost-gated**
System 2 planning and credit mechanism, not a solver to instantiate at
every Cell and not an automatic language reasoning theorem.

Independent source observations and binding limitations:

| Source | Existing concrete observation | What it does NOT establish |
| --- | --- | --- |
| [#1885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1885) | 384D shared feature, 64D state, rank-8, 8-output gated Head with 9,744 parameters, scoped immutable snapshots and research fan-out | Real multimodal task advantage or deployed 4096-Cell inference |
| [#2065](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2065) | Actual archived AG News val2 128 independently reviewed source-label cases: Granite97 learned **122/128**, linear **119/128**; mmBERT-small learned **73/128**, linear **70/128**. Granite p99 reported CPU single-input encoder **68.20 ms**, mmBERT **106.54 ms**. | General model winner, matched cross-family controls, independent future task performance, full lifecycle/4096 serving |
| [#1923](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1923) | Exact rational global obstruction, 4096 **Head-only synthetic-feature** batch, 160 synthetic expected-utility decisions: exact Bellman **0.743346**, learned gate **0.732948**, trained linear **0.730853** | Real learned NDU superiority, pretrained encoder Head batch or natural language inference |
| [#2014](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2014) | 576 historical generated mmBERT-derived independent-leaf finite BSDE predictions reproduce cheaper AND/OR polynomial to numerical precision | Incremental semantic reasoning from adding that BSDE |
| [#2003](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2003) | 60 bounded nonlinear **discrete binary tree** coupled FBSDE tests, 48 admitted by specified global contraction, explicit wrong-boundary controls | General continuous stochastic existence, learned FBSDE or Reader task success |
| [#2053](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2053) | All 192 source-bound synthetic decisions have an independently outward-rounded discrete action-gap certificate. Faster interval auditor still loses to the cheap full reference for the all-in online cost. | Online cost-adjusted System 2 advantage |
| [#2068](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2068) | Real ModernBERT 32 unique source cases / 3 seeds: Token Query improves retrospective Brier/NLL but slightly reduces accuracy against pooled features | General superiority of token cross attention |

Current model ranking must therefore be **conditional on workload**. For text,
retrieval and code MemoryCell pilots, place **Granite Embedding 97M
Multilingual R2** first in the research queue and retain mmBERT-small as an
independent token-rich/multilingual competitor. Do not automatically select
Granite for every task: AG News is a single retrospective source family.
Keep a **one-shared-421M + identical Head** arm alongside **4096 independent
421M copies** so weight sharing and compact-model substitution are not
confounded. Fix Reader, token budget, Head count/training/compute, source,
groups, and task objective across causal arms. Stronger reference Reader
results must be reported as capacity diagnostics, not credited to Stem.

### Current candidate specifications, not Hepta-qualified results

- Granite Embedding R2 multilingual 97M: 384D, ~200+ languages, code,
  32,768-token model-card maximum context, Apache 2.0. Its retrieval
  training objective does not imply semantic reasoning.
  https://github.com/ibm-granite/granite-embedding-models
- mmBERT-small: 140M total, only 42M non-embedding parameters, 384D,
  8,192-token context, 1,800+ languages; masked-language pretraining is
  useful as an alternative information-preserving token representation.
  https://huggingface.co/jhu-clsp/mmBERT-small
- **EmbeddingGemma 2** (October **6, 2026**) is NOT the historical
  Gemma2/Laya 421M baseline of #2065. The native multimodal model has
  **270M text/code + 170M optional vision + 300M optional audio = 740M
  total**, native 768D (Matryoshka 128/256/512/768), with 270/440/570/740M
  modular loading profiles. It is the strongest architecture-specific
  native aligned multimodal control to include in the next experiment,
  but is not yet physically scored in the Hepta paired study.
  https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2

## 2. Quantified shared-weight advantage and its limitation

Research profile: 4,096 logical Cells, 9,744 scalars in every Head, declared
FP32 weights-only, all Heads resident. These weights are not the 7,434
parameter trained #2065 Head or the separate 2K/8K/16K variants.

| Hypothetical weight geometry | Bytes |
| --- | ---: |
| 4,096 independent full 421M models | 6,897,664,000,000 |
| One shared 421M model + 4,096 Heads | 1,843,645,696 |
| One shared 97M model + 4,096 Heads | 547,645,696 |
| All 4,096 Heads alone | 159,645,696 |

This *does not report measured resident RSS*: activation/storage/optimizer,
cache/feature lifetime, model weight precision, concurrent training, modality
towers, graph overhead, Decoder and Verifier are excluded. Running 4096
different source sequences still requires up to 4096 Encoder forwards,
even with one shared weight tensor. Only **identical source/scope/generation/
tokenizer/model/normalizer/option identities**, plus actual authorized
fenced caching, can reduce their forwards to one. Sharing model residency
is NOT equivalent to sharing FLOPs. The physically measured #1923
4096-Head batch alone is NOT an end-to-end 4096-Encoder result.

The accompanying self-contained budget.py implements only these three
weight profiles, typed full-identity fan-out and declared System 2 work
counts. It rejects cross-scope/epoch/feature reuse and impossible graph
counts. Its output explicitly contains **measured=false** and DENY_ALL.
It neither trusts a supplied digest as a signer nor invents p99/energy or
admitted worker execution.

~~~
python3 -m unittest discover -s qualification/shared-stem-system2-architecture -p 'test_budget.py' -v
python3 qualification/shared-stem-system2-architecture/budget.py --cells 4096
python3 qualification/shared-stem-system2-architecture/budget.py --cells 4096 --distinct-inputs
~~~

## 3. Multimodal differentiation from one text-first Stem

Native architecture proposal (each arrow must carry typed provenance):

~~~
approved text/code → Granite97/mmBERT text Stem → pooled + token features
approved image/doc → vision tower → patch/region embeddings + OCR control
approved raw audio → audio tower → segment/time embeddings + ASR control
approved video → frame vision + ordered temporal state, not mean-only pooling
approved sensors/events → normalized values, type, units, event time
       ↓   train-only paired projection/contrastive/conditional fusion
 shared semantic interface 384D (or explicitly converted native 768D)
       ↓
 organ adapters → scope-isolated Cell state → sparse trainable gated Heads
       ↓
 typed Neuron Circuit / bounded Graph with cheap Critic and explicit stop
       ↓
 on-demand NDU System 2 / optional qualified FBSDE for difficult subgraphs
       ↓
 verified plan/evidence/citations → separately qualified Decoder + Verifier
~~~

The same **semantic interface** is not a claim that image/speech/video can
be processed by an unmodified text-only tokenizer. Shared latent space
requires actual modality-specific perception, fitted bridges or a native
aligned multimodal Encoder. Freeze modality towers first; train projections
on training-only aligned pairs, and compare shuffled/unfitted/OCR-only
controls, crossmodal retrieval plus complete task success. An EmbeddingGemma
2 native shared-768D control must preserve its distinct revision and
projection identity, not be silently treated as 384D Granite.

A single pooled vector can erase token order, object relations, temporal
reversal, source truth changes and which evidence span supports an answer.
For multi-hop and video reasoning expose selected token/patch/time-aligned
features and test option-conditioned attention against cheaper pooling,
keeping all feature/training costs. A Head cannot reconstruct information
discarded by every frozen input representation.

## 4. Why local short-horizon FBSDE uniqueness does not grant global solve

Let the augmented forward state S include task state, Cell/Organ memory,
bounded preference, resource budget and **frozen** selected weights. In a
registered stochastic model (not a free analogy for Encoder layers):

~~~
dS = b(t,S,Y,Z,a)dt + sigma(t,S,Y,Z,a)dW
dY = -f(t,S,Y,Z,a)dt + Z dW
Y(T) = G_J(S(T), independently observed terminal outcome)
~~~

Y is recursive utility, not a token; Z is martingale sensitivity, **not**
dY/dparameters; a is an admissible policy control; the filtration must not
contain future observations at the current node. A branch denotes an
action/observation alternative, not by itself a Brownian driver.
Local existence/uniqueness theorems require declared regularity,
admissible boundary/terminal data, adaptedness, and qualified coupling.
They cannot be pasted into arbitrary neural layers as an existence proof.

The original #1923 obstruction already captures the relevant error:

~~~
dX = Y dt, dY = 0, X(0) = x0, Y(T) = g X(T)
global constraint: (1-g*T)*Y(0) = g*x0
~~~

At g*T=1 and x0 ≠ 0 there is **no solution**; with x0=0 there are
multiple. Even when algebraically unique, a regular decoupling field can
have a pole. A concrete wrong-reset example: x0=1, g=1, T=1/2.
The genuine global trajectory is Y=2, X(T)=2. Solve interval [0,1/4]
using a locally imposed Y(1/4)=0: it gives Y=0 and X(1/4)=1. Then
solve [1/4,1/2] using the true terminal Y=X(1/2): its unique local
solution is Y=4/3, X(T)=4/3. Both local pieces satisfy **their own**
equations and terminal conditions, but Y jumps 4/3 at the stitch.
The last segment reaches the required terminal relation and still does
not define a global solution.

Thus “stop when the last iteration equals some branch's global FBSDE”
is **circular** unless an independent global oracle or certified full-path
error bound is available. A full-Graph FBSDE admission must independently
check all interfaces X^- = X^+, Y^- = Y^+; initial and *every relevant*
terminal boundary; forward/backward dynamics; a common adapted filtration;
martingale representation and centered conditional Z Sigma = B;
regularity/global continuation, discretization and learned-coefficient
uncertainty, and stability conditions before translating a small residual
into a solution-error certificate. Unsupported covariance or missing
support fails closed. A zero local residual or correct leaf answer
alone never passes.

Use cheap **exact Bellman/finite BSDE** first on small belief trees.
Only for a demonstrably nonlinear forward/backward-coupled case is a
costed iterative full-tree Picard/Newton/FBSDE potentially worth trying.
#2014 already reports a negative additional-BSDE result in a simple
case. #2053 proves valuable discrete offline intervals but the online
certification overhead currently defeats the cheap reference. Preserve
these negative results, do not extrapolate them to general SDE theorems.

## 5. Cost-gated System 2 and Cell learning

The proposed computational scheduler offers STOP, answer, observe,
memory hop, tool call, enlarge evidence, subgraph search and abstain
as **typed legal actions**. A cheap, separately validated Critic estimates
task value and uncertainty. Pay for deeper processing only if its supported
expected value of information / decision gain exceeds *all* compute,
latency, token, risk, Decoder/Verifier and certification costs under the
registered fixed objective. An independent certified action-gap can allow
an early decision without solving every full value to high precision;
otherwise retain cheap fallback/abstain. The graph's solved-node count
and physical worker count must be measured separately.

A qualified System 2 may distill value/advantage and error signals into
candidate-only lightweight Head training. Its value Y and Z must not be
mistaken for the parameter gradient; differentiate an actual frozen
model/unroll or use an independently supported policy-gradient estimator.
Keep supervised prediction accuracy/calibration separate from behavior
policy and utility. The true external success measure, data permission,
objective, legal action set, revocation and current selected snapshot
are not trainable. New Heads only replace old ones via independent
future-window selection, retention and rollback. The language Decoder
requires a genuine conditional decoder or task-limited deterministic
renderer, followed by evidence/citation Verifier. Prompt-injection content
is untrusted data, never authority to redefine NDU reward or boundary.

## 6. Causal gate order (fail closed)

| Stage | Minimum required next test | Matched counterfactual |
| --- | --- | --- |
| E0: Reader adequacy | Four identical questions with no evidence, ordinary retrieval, independently verified sufficient evidence, and key premise removed | Same Reader/prompt/tokens; stronger Reader only diagnostic |
| E1: Text Stem | Physically pinned and uniformly measured Granite97, mmBERT, shared421, distinct421, EmbeddingGemma2 text-270; source-family/time-disjoint tasks and 2K/8K/16K matched Head learning | no-change/frozen Head, cheap linear, fair costs, no family leaks |
| E2: Multi-modal | Real paired image/OCR/audio/video/temporal truth-flip future groups and exact source/label provenance | text/OCR/ASR-only, unaligned tower, learned bridge, native aligned |
| E3: Cell/Graph | Actual 64/256/1024/4096 cells plus per-scope revocation, target-host RSS/GPU/p95/p99, sparsity, checkpoint and recovery; future multi-hop tasks | equal-total-params homogeneous Cell, no edge, frozen learned-edge, fixed depth |
| E4: NDU/FBSDE | Independent complete time-tree interface certification, OOD, model/observation noise and costed real task outcomes | cheap exact Bellman/direct BSDE, fixed-depth tree, learned Critic, Newton/Picard, offline verifier |
| E5: Distillation | Frozen teacher/Reader and complete training/search/accounting; independently observed future utility + old-task retention | frozen Head/no-change, linear policy, equal-work Head and no System 2 |

**Production acceptance remains false** until independent future task utility,
safety and negative-transfer criteria, authentic source/model/target-host
receipts, final-use authorization, original owner CAS/fences and passing
exact-head plus synthetic-merge blocking CI are obtained. No new model
selection, physical 4096-Stem result, globally qualified continuous FBSDE
or causal emergent language reasoning is claimed here.

## Mathematical references

- Qian Qi, *Existence and Uniqueness of Neural Differential Utility* (2025):
  general square-integrable martingale FBSDE under explicit well-posedness
  and control continuity/regularity assumptions; no automatic language
  reasoning theorem. https://ssrn.com/abstract=5267854
- Short-time fully coupled FBSDE discussion and Antonelli-type obstruction
  against arbitrary global extension: https://doi.org/10.1016/j.jmaa.2021.125540
- Huré, Pham, Warin, *Deep backward schemes for high-dimensional nonlinear
  PDEs* (2019): approximation/recursive error analysis and solver limits.
  https://arxiv.org/abs/1902.01599

**Disposition:** production_accepted=false; stem_globally_selected=false;
fbsde_global_theorem_established=false; net_online_System2_win=false;
authority=DENY_ALL.
