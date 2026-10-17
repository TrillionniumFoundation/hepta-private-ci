# P7 — P5 original Qwen3 physical evidence and marginal-compute no-go (DENY_ALL)

**RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / DRAFT / NO MAIN MERGE / NO MODEL PROMOTION.**

This is a strictly additive child of P6 PR #2613, exact proposed parent commit `73b1a5d247e45c0d1e78237d0e8ca554c96b21de`. It preserves P5 PR #2581, original Qwen3 physical model protocol and independent score, P6 synthetic World Model, production Neuron/NDU/World Model owners, `blocking-ci`, and all source/selection/effect authority. It does not train or select a model, replace an FBSDE solver, certify hardware/causal outcomes or claim inference savings.

## New original physical observation — not a synthesis or planned run

The immutable P5 exact-head Actions run [39000773484](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39000773484) **completed successfully**. Its four authenticated-to-GitHub *self-metered* artifact groups are:

- SHA-pinned public TRAIN and label-blind HELD (`12089824906`): 16 real AG News publisher TRAIN records and 16 balanced historical-public held examples, 4 per source class.
- SHA-pinned held publisher labels (`12090595870`): joined **only after** the physical Qwen execution.
- Original completed Qwen3-0.6B execution and ordered start/done journal (`12091821534`): 48 TRAIN + 112 physically paid seven-policy held + 32 additional matched 96/96 thinking/nonthinking calls, **192 distinct original forwards**. Frozen plan is journaled before held dispatch.
- SHA-pinned separated P5 postseal publisher review (`12094070817`): actual original outcome and cost report. This is code-separated but **not a third-party signed/hardware-attested review**.

Model weights and tokenizer were checked in the P5 worker; this gate validates their recorded pinned digests but cannot independently re-read unloaded model bytes.

## Mechanism of the independent P7 checker

`physical_evidence_gate.py` imports **neither** the original model worker, P1 allocator, P5 review, P6 planner nor their core calculation helpers. It separately:

1. Reads **seven** original uncompressed source/evidence files with a hardcoded exact SHA-256 preimage lock, rejects duplicate JSON properties, non-finite values and unknown/missing sources.
2. Confirms original public train/held text digests, label privacy, held independent gold binding, original class balance and preserved *historical-public* scope without claiming independent families.
3. Recomputes the frozen plan and original TRAIN predictions against source labels. Checks 112 recorded held action assignments, seven physical policy arms, all 32 independent 96/96 comparison calls, action budgets and an **ordered 385-event** durable journal (192 starts + 192 dones + one pre-held frozen plan).
4. Recomputes **every original answer** with the already-predeclared exact P5 whole-string parser, rejecting unfinished thinking as missing final answer; re-scores all 16 held publisher labels, action costs and paired wins/losses from original call rows.
5. Verifies the independently published reviewer totals (including original input + output tokens, CPU/wall costs, before/after task outcomes, training, cold-start, time profiles and no physical savings claim); reports a permanently authority-free **NO_GO or INSUFFICIENT_EVIDENCE** result. There is no acceptance path.

The report does not reinterpret P4 historical mistakes using the P5 parser. It also does not infer a new invocation or cost saving from a retrospective alternative choice: **all P5 arms were already called and paid**. Original source labels came from a historically public dataset, not a future cohort or independently established news families.

## Physically observed result (source SHA-pinned, local P7 independent replay)

| On-policy original arm | Correct of 16 | *Full* input+output tokens |
| --- | ---: | ---: |
| Direct | 5 | 2,155 |
| Fixed reasoning | 5 | 2,331 |
| Greedy | 5 | 2,189 |
| Neutral Bellman | 5 | 2,189 |
| Fixed risk | 5 | 2,189 |
| NDU-discrete | 5 | 2,189 |
| Same-profile ordinary | 5 | 2,189 |

NDU-discrete and ordinary same-profile selected the same original actions. NDU had **one task rescue, one task loss** relative to Direct; total correctness did not improve despite **34 additional full input+output tokens** and additional observed CPU. These small paired observational counts are not a robust inferential comparison.

The independently paid equal-cap experiment shows: thinking-on **0/16** and **1,536** generated tokens, with **16/16 unfinished**; no-thinking **5/16** and **64** generated tokens. Task-wise thinking gains/losses/ties: **0/5/11**. This identifies a concrete *96-token unfinished-thinking problem* in this particular model/task setup; it is not a universal theorem about thinking or long reasoning.

Whole-study original self-metered total CPU **1,224.414927387 s**, wall **655.848818851 s**; original TRAIN CPU **473.713663853 s**, model-load CPU **13.185505947 s**. Cost must not be manufactured as cash or energy, or shared calibration incorrectly charged seven times.

**Conclusion:** `OBSERVED_NO_NDU_TASK_COST_LIFT`. Under the registered original full-serving-token tariff, Direct dominates NDU in *aggregate observed task correctness and serving tokens*, not necessarily each individual task. This **does not prove that NDU cannot help on different models, tasks or budgets**. A mathematically identical Bellman objective cannot establish NDU-specific optimization superiority.

## Reproduction (Python >=3.11, standard library)

Place GitHub artifact ZIPs for the exact P5 run in four directories by unpacking `train-public.json` and `held-public.json` into `public/`, `held-private-labels.json` into `gold/`, original execution/plan/journal into `original/`, and the original review into `review/`. Seven original content digests must match hardcoded locks. No raw AG News text or original model answers are committed to this research PR.

```bash
P7=experiments/ndu_tree_fbsde_gates/merton/physical_evidence_p7
HEPTA_P7_EVIDENCE_ROOT=/tmp/hepta-p5-evidence \
  PYTHONPATH="$P7" python -W error::ResourceWarning -m unittest discover -s "$P7" -p 'test_*.py' -v
HEPTA_P7_EVIDENCE_ROOT=/tmp/hepta-p5-evidence \
  PYTHONPATH="$P7" python -O -W error::ResourceWarning -m unittest discover -s "$P7" -p 'test_*.py' -v
python "$P7/physical_evidence_gate.py" \
  --public /tmp/hepta-p5-evidence/public \
  --gold /tmp/hepta-p5-evidence/gold \
  --original /tmp/hepta-p5-evidence/original \
  --review /tmp/hepta-p5-evidence/review \
  --output /tmp/hepta-p7-audit.json
```

The standalone Actions workflow uses `actions/download-artifact@v4` and `actions: read` for the **exact historical run**, not any mutable latest run, and binds the entire original content before re-evaluation. Missing/expired/tampered original artifacts cause failure, never success. The original P5 artifacts have seven-day retention; long-term independent custody is a **separate unresolved gate**.

## Next falsifiable research target (not implemented or claimed here)

On newly sourced family/time cohorts, preregister competing direct, short-thinking, output-reserved long-thinking and independent verification policies with identical source information, true token/latency tariffs, complete lifecycle costs and independent publisher/human outcome custody. Estimate the task-conditioned *marginal* effect and covariance of additional compute before comparing an NDU-constrained portfolio against ordinary same-profile Bellman. P7 alone does not approve that study or any production deployment.
