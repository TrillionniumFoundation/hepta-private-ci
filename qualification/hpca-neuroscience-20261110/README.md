# HPCA — heterogeneous plasticity and credit-assignment qualification

**Status:** QUALIFICATION_ONLY / HOLD_NO_GO  
**Scope:** deterministic, standard-library Python reference; zero model, network, file-owner or deployment authority.  
**Location:** qualification/hpca-neuroscience-20261110  
**Existing owners:** neuron.runtime eligibility/checkpoint, learning.plasticity next-snapshot proposals, learning.ledger source/outcome provenance, independent evaluator and Agentd orchestration.

## Research question

Can differentiated update cadences, correctly routed local credit, event-bound delayed feedback, and separated memory replay outperform information- and resource-matched controls **on independently evaluated downstream tasks**? The answer is not established by the reference. This harness makes the first mechanisms and confounds executable and preserves negative controls.

The biological and nested-learning references below are motivation for falsifiable hypotheses, not authorization to infer that Hepta or the brain uses the same algorithm. Citation details were supplied for this research discussion and have not been independently reverified in this run:

- Action timing / cell-type plasticity: https://pmc.ncbi.nlm.nih.gov/articles/PMC13473605/
- NeurIPS 2025 Nested Learning: https://proceedings.neurips.cc/paper_files/paper/2025/hash/4309616aaed8e848009bc4a7ef73b493-Abstract-Conference.html
- Nature 2026 dendritic instructive signals: https://www.nature.com/articles/s41586-026-10190-7
- PNAS 2026 sparse-feedback neuromodulation: https://pmc.ncbi.nlm.nih.gov/articles/PMC13598169/
- Self-evolving agent memory interference: https://arxiv.org/abs/2610.25858

## Freeze before running

- Code: exact Git tree / Python version and SHA-256 source manifest written to RESULT.
- Data: synthetic environment functions plus calibration seeds 9001..9006 and held-out test seeds 11001..11016.
- Action and evaluation rules: fixed in code, no online tuning on held-out seeds.
- Scope: all parameter changes are **in-memory research candidates**; no selected Cell weights, ledger or source revisions are modified.
- Results: report all arms including failures. Do not promote a claim from a one-seed plot or a non-neural control's superiority.
- Resources: count optimizer writes, feedback, replay selection reads; actual compute, wall time, energy, persistent storage and acquisition cost remain unmeasured.

Run from this directory:

    python3 -m unittest discover -s . -p 'test_*.py' -v
    python3 run.py --out RESULT.json

The first command tests contract invariants; the second reports deterministic paired diagnostics. Neither is production evidence. Use the workflow artifact or pin the complete RESULT and identity in the research log; do not replace a failing result with a success-looking summary.

## Arm matrix and failure modes

| Hypothesis | Candidate | Mandatory controls | Outcome | Limits |
| --- | --- | --- | --- | --- |
| H1 lineage-specific cadence | Heterogeneous scheduler: PERC 1/16, PRED 4/16, CTRL 8/16, ACT 3/16 | Uniform scheduler 4/16 each; both rate-tuned on same calibration seeds | Paired mean squared prediction error by lineage, total 256 updates per seed | Proxy streams; no learned encoder, Cell or live optimizer; data and neural compute not measured |
| H2 routed local credit | Scalar delayed reward multiplied by action eligibility on observed causal group | Same-information contextual policy gradient (mathematically identical), random routing, permuted group, full broadcast with 3× update accounting | Held-out correct-action probability and all update costs | Observed context makes contextual policy gradient an equivalent baseline; not a novelty result |
| H3 event-bound delayed traces | Event-ID eligibility retained to feedback | Last/current-event trace, at 0 and 8 delays; dense and 15% feedback | Accuracy, observed feedback and data parity | Not a simulation of neurochemical diffusion or real ACT tool outcomes |
| H4 differentiated replay | Uniform, recency-only, old-kind stratification, error-prioritized replay | Immutable exact-key source retrieval; equal neural training updates; priority scan costs counted | Old retention, new correctness, procedure/recovery proxy labels, revoked non-resurrection | Hashed-head collisions are deliberate; no actual skill learning or multilingual retrieval claims |

### Separating seven Hepta responsibilities

- **PERC:** freeze or slow-update a shared encoder; candidate adapter evaluation at longer intervals; held-out multimodal perception/grounding.
- **MEM:** event/source fact ingestion immediately, immutable revision and tombstone semantics; replay/consolidation on eligible snapshots only.
- **PRED:** medium-frequency world-model updates; compare calibration, state uncertainty, and delayed outcomes.
- **CTRL:** rapid candidate heads for action probabilities, stop/risk and NDU; downstream policy evaluation, not proxy CRPS alone.
- **VERIFY:** independently measured checker sensitivity/specificity and value of checking; missing labels are not zero failure bounds.
- **ACT:** asynchronous procedure/recovery replay; actual goal effects and delayed owner readback take priority over synthetic skills.
- **LEARN:** orchestrate cadence, routed credit, candidate-only training, independent evaluate/NoUpdate/Adopt and cold recovery.

All lineage clocks are hypotheses to tune with blocked validation. They are not hard-coded production scheduling policy. Exact retrieval, security checks, policy admission, signatures and durable effect bookkeeping remain deterministic.

## Fair inference contract for a real successor experiment

1. Freeze the same actual pretrained backbone, encoder, tokenizer, model and adapter manifests, task splits, source permissions, native owners, host binaries and legal action masks. Commit identities and independent evaluator must be pinned. Do not use post-action labels, task outcomes, or private future state in a pre-action feature or credit route.
2. Run matched A/B/C/D: ordinary core + ordinary controller; ordinary + NDU; Hepta core + ordinary; Hepta + NDU. Report B−A, D−C, D−B, (D−C)−(B−A). For local credit additionally compare information-matched contextual policy gradient, global scalar × eligibility, routing permutation, delayed-ID permutation and supervised-gradient control where labels legally exist.
3. Match sampling, labels, VOI, model FLOPs, training/tuning/selection cost, total wall time, GPU RAM, checkpoint/storage I/O, deadline and failure burden. Report Pareto frontiers; full broadcast is not cost matched in this microbenchmark. Validate strong fixed, direct, contextual, MPC, fixed-rate and no-learning controls.
4. Test text-sufficient, image/text-complement, selective correction, prepare-then-benefit, timely-stop, procedure repair and old-task retention. Report per-family and pooled results. Delayed/sparse rewards are a separate stratum; dense labels must retain simple gradient as a strong baseline.
5. Reserve independent seeds not used for model choice; register primary net downstream utility, sample size, minimal useful effect and exact Holm-corrected comparison family before confirmatory run. Example gate for a proposed deployment: at least +0.02 in predefined normalized net utility units, multiplicity-adjusted 95% lower CI above zero, no critical safety/revocation failures, no prespecified old-task/OOD regression and resource budget met. The +0.02 threshold is a proposed gate, not a result or universal standard.
6. Validate cross-scope denial, source corrections, delete/forget non-resurrection, contradictory evidence abstention, queue failure, duplicate feedback, exact owner fence/checkpoint recovery, and independent observer-signed outcome. A missing/late result is UNKNOWN, never success.
7. Produce a next-snapshot candidate only through the existing learning.plasticity owner-evidence and trust-region path. Only independently signed evaluation and authorized selection may install it; otherwise NoUpdate. Repeat on a different next task after a cold owner restart.

## Interpreting the present reference

The simulation uses contextual bandits, noisy scalar streams and synthetic hashed-key memory; it contains no transformer, spiking hardware, procedural tool executor, qualified encoder, independent actual task owner, production memory-sharing service, or end-to-end pretrained model adaptation. The exact-key control has a richer memory representation but no gradient steps, so compare its measured lookup cost before a value claim. Contextual policy gradient is intentionally mathematically equivalent to the three-factor routed update here; superiority to broadcast or a deliberately wrong route does not establish a new learning algorithm.

**Release decision for all reference results: HOLD_NO_GO.** A red/green unit test protects implementation semantics, not future-time causal utility or real-world benefits.
