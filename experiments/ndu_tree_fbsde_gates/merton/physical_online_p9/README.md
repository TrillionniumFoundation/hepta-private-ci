# P9 — prepaid real-token cognitive portfolio with frozen Qwen3 and independently verified quotes

**Draft · Research-only · Shadow-only · DENY_ALL · No main merge · No model promotion.**

Stack strictly on [P8 PR #2631](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2631) at immutable source commit `2a918832a7c8b27384481942274102388dd4dfd2`. This changes **only additive P9 experiment and read-only CI files**, leaving P5–P8, production Neuron/NDU, selected weights, journal owners, protected `main`, `blocking-ci` and FinalUse unchanged.

## The P8 defect this experiment isolates

P8 imposes **four checker calls** and adds mean observed physical tokens to a utility tariff. Four calls are **not** a hard full-token budget: inputs have different lengths, thinking may consume all 256 generated tokens, and an unchosen checker can be priced dishonestly. A trial labeled a *reasoning-token investment portfolio* requires enforcing real token availability **before** each selected generation, not only reporting incurred cost after it has happened.

P9 gives each of seven independent policies exactly **1,500 additional actual input+output token units** and **four checker call slots** over 16 held tasks. Each *direct* first-pass call is separately paid and included in full lifecycle cost; it is **not** counted as free inference. Before a checker invocation, P9 must durably reserve `original tokenizer input length + max_new_tokens(256)`; only then may it emit the original model start and call Qwen. After completion, it checks the physical input length against the original quote, charges the actual generated tokens, refunds **only unused reserved output tokens**, and persists the receipt. Missing ACK, crash or quote mismatch leaves the attempt incomplete/unavailable, never a successful conservation receipt. A quote is *not* a model inference and does not grant dispatch authority.

A separate postseal evaluator downloads **only the frozen original tokenizer**, SHA256-verifies it, reconstructs the P8 prompt and independently checks *both* plain and thinking-mode quotes on every held direct answer, including **unchosen** alternatives. The evaluator recomputes the SHA-chained reservation → start → done → settlement sequence, original paid-call census, policy, token conservation and publisher truth, but is still a shared-author research program on a self-metered GitHub Actions host, not a signed independent hardware auditor.

## Original source and model separation

Reuse P5's original immutable `Qwen/Qwen3-0.6B` weights (`16706fc57485378d4ffaf54139b29ccc66ae08fa`), original model SHA256 and tokenizer SHA256, and original `szhuggingface/ag_news@98c532231d96ae10e176a909192ecac548949288` Parquet source verification. This is a new original **historically public** source panel, **not** a prospective time/family split:

- Publisher-owner chooses original fourth and fifth occurrence per each of **4 labels × 2 original text-length strata × 2 row-index parities** for TRAIN = 32 real examples; picks original third occurrence for HELD = 16 source-label-blind examples. This excludes P5's first and P8's second/third TRAIN and P8's second HELD examples.
- TRAIN independently pays 32 × (`direct`, `check_plain`, `check_think`) = **96 original Qwen3 generation calls**. The TRAIN labels and paired completion outcomes fit the frozen empirical opportunity model. If support is missing, the policy cannot invent a counterfactual.
- At inference, all seven policies separately pay their own direct model forward on every held example (**112 calls**) and may independently buy at most four additional checker forwards each (**0–28** calls), subject also to the strictly enforced 1,500-token escrow. Thus the declared *possible* whole-study range is **208–236 original generations**, **not** a claim those generations have already run.
- Gold labels remain unavailable to the Reader/Controller until the original model has completed and sealed its start/done journal. The postseal reviewer independently regenerates the exact publisher train/public/gold packets before scoring.

The seven research arms are `direct`, `fixed_plain`, `fixed_think`, `myopic`, `neutral_shadow`, `ndu_shadow`, `ordinary_same_profile`. NDU's bounded risk weight comes only from TRAIN smoothed success, group minimum, observable initial answer parse status and conserved in-run resource state. `ordinary_same_profile` uses the **same objective, information and heuristic** and must select identical actions to `ndu_shadow`, otherwise review fails. Its equality is a negative control: changing a soft risk weight alone cannot be advertised as a unique NDU algorithmic gain. The future-token shadow price is a *declared empirical heuristic* on frozen TRAIN/bucket information, **not** globally optimal Merton, an exact dynamic program for unknown future Qwen outputs, a learned neural FBSDE or a proven risk bound.

## Local/source tests and physical execution

```sh
D=experiments/ndu_tree_fbsde_gates/merton/physical_online_p9
export PYTHONPATH="$D"
python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -m compileall -q "$D"
```

The P9 tests use a synthetic `FakeReader` and an original-source-shape fixture; no real Qwen call or claimed model quality arises from those. They verify quote admission, no optimism from missing support, conservation, refused in-flight reuse, wrong actual prompt cost, unclosed thought, independent comparison, leaked gold, source/meter/journal tampering, explicit independent tokenizer quote requirement, and fail-closed/recovery posture.

The dedicated `.github/workflows/hepta-ndu-merton-p9-prepaid-online.yml` stages (1) source-only tests, (2) SHA-pinned original publisher acquisition with label separation, (3) genuine original Qwen model calls in a token escrow, and (4) fresh publisher reselect plus frozen original tokenizer and original paid-call independent postseal replay. Normal passing tests do **not** mean physical calls have completed. No app effect is executed, no external capability is issued and all results remain `DENY_ALL` regardless of an apparent gain.

## Decision and scientific gates

Primary outcomes are publisher classification success at **equal explicit hard checker-token + call ceilings** and the **full physically reported** TRAIN/direct/verification/model-load/inference CPU and wall/token costs. Report paired wins/losses and unchanged P8 historical results; never equate a self-reported cap or unrealized counterfactual budget with actual compute saving. Independent future source-family/time windows, authenticated physical metering, retention/negative transfer and statistically supported NDU-over-identical-profile progress remain unproven. This experiment cannot promote its own artifact, remove `blocking-ci` or alter current-run objectives.
