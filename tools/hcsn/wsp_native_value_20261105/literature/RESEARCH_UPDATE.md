# Weight-space programming: pinned source update and stronger controls

Review date: **2026-11-04, America/New_York** (source check completed on
2026-11-05 UTC). This file extends the preceding WSP follow-up's literature
review. It is a review of primary source records. **It contains no newly
executed model, training run, checkpoint repair, or measured Hepta benefit.**
All quantitative evidence below comes from the fixed revisions in
[SOURCES.json](SOURCES.json). Interpretations and proposed Hepta controls are
identified as this review's inferences.

The observed MIT release remains
`RikiyaT/lm_understand-logs@4d09ba6d6a7e891dd8063974dfe81b3d78e3494f`.
The observed Turing release remains
`alan-turing-institute/weights_editing@9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca`.
Unchanged source identity does not mean that all its experiments had been covered
by the earlier review.

## 1. What the MIT result establishes, and what it does not

The released harness identifies the editor as `gpt-6-astra`. Experiments 1, 2
and 4 use reasoning effort `high`; 3, 5, 6 and 7 use `xhigh`; experiment 8
uses `max`. The CLI's built-in tools were disabled, but in experiments 3, 6,
7 and 8 the authors executed submitted Python and returned its output. Thus a
tool-free CLI event stream does not mean an experiment had no computational
tools. The release contains the runs reported by the authors; earlier prompt
trials are excluded. [M1]

For Qwen, the permitted interface included generation and teacher-forced reads
of practice data. The latter could return log probabilities, hidden states, MLP
activations and attention. A request called a forward pass could contain up to
512 generation problems or 1,024 teacher-forced texts. The Python kernel was CPU
only; target-model execution was delegated to a separate service. Gradient
descent, backward passes and iterative loss fitting were forbidden. Consequently,
the experiment supports **target-weight editing without gradient training**;
it does not establish editing without data, search, activations, model execution,
or editor-inference cost. [M2]

The authors' retained scores under their common evaluation settings are:

| Target-model result | Base | p50c edit |
|---|---:|---:|
| MATH-500 accuracy | 7.90% | 48.10% |
| MATH-500 answers at the token limit | 93.00% | 33.05% |
| MATH-500 mean output tokens | 30,868.43 | 22,037.15 |
| GSM8K accuracy | 13.84% | 67.10% |
| IFEval strict prompt-level accuracy | 20.98% | 62.29% |

These are the authors' generated-answer records, read in this review and not
rerun here. MATH-500 uses 500 problems with four samples per problem. Those
2,000 samples are not 2,000 independent edit discoveries. [M2], [M5], [M6]

The retained p50c discovery run uses 50 forward requests, 158 CLI turns, 80 Python
runs and four conversations. Its reported 20.3 hours include 4.7 hours of waiting
for an unavailable editor service. Those hours are neither GPU compute hours
nor a complete priced cost of the research programme. Failed target requests
did not consume the nominal request budget; their actual resource costs cannot
therefore be inferred from the number 50. [M2]

In the authors' final practice confirmation, 576 of 579 rescued answers had
previously been truncated. This supports a loop/termination repair mechanism.
The non-looping Gemma follow-up did not establish a math-capability gain; its
reported 6.8% baseline and 7.0–7.7% edited scores also use a different,
format-agnostic grading rule. Neither finding is a theorem about all possible
weight edits. [M7], [M8]

## 2. The exact edit is stronger than an orthogonal projection deletion

The p50c notes specify, for each affected layer,

```text
W_new = W_base - 6 * outer(u, mask64 * (u @ W_base))
```

The edited matrices are
`model.language_model.layers.15.mlp.down_proj.weight` and
`model.language_model.layers.19.mlp.down_proj.weight`, each of shape
1024 by 3584. With a unit direction and before rounding, the component along
that direction in a selected column changes from a to -5a. The operation is
therefore a direction-selective reversal/amplification; it is not merely
removing the projection, which would use coefficient 1. This algebraic
description follows the recorded formula, rather than inferring the mechanism
from a headline. [M3]

The manifest distinguishes addressed positions from realized BF16 changes:

| Tensor layer | Addressed positions | Bitwise-changed BF16 entries | Recorded relative change |
|---|---:|---:|---:|
| 15 | 65,536 | 65,260 | 0.10636 |
| 19 | 65,536 | 64,928 | 0.08106 |
| Total | 131,072 | 130,188 | — |

The 884 remaining addressed positions round to their original values. A count
of edited parameters does not by itself bound the magnitude or downstream
effect of a change. The base and edited tensor SHA256 values are in the source
manifest. This review read those identities; it did not recreate the tensors. [M4]

## 3. New strong baseline: change configuration without editing weights

A separate primary execution record from Carlos Toledo evaluates the unchanged
Qwen checkpoint under three predeclared configuration arms. The pinned record
is `cert-machine@76805430d50e396cae81a704bd17dc68152414fc`; its
`certs/wsp-baseline.json` was generated at 2026-11-03T18:58:52Z.
Each completed condition uses all 500 MATH-500 problems, four samples per
problem, seed 0, an H200, vLLM 0.33.0 and Transformers 5.20.2. [B1], [B2]

| Unedited arm | Settings | Correct / 2,000, with refused answers counted wrong | Grader-refused answers | At token limit | Generated tokens | Recorded seconds |
|---|---|---:|---:|---:|---:|---:|
| C1 | MIT settings; thinking; temperature 0.6; 32,768 tokens | 144 / 2,000 = **7.20%** | 7 | 93.10% | 61,731,466 | 4,984 |
| C2 | Card thinking settings; temperature 1.0; 81,920 tokens | 445 / 2,000 = **22.25%** | 23 | 74.95% | 135,529,511 | 21,590 |
| C3 | Card non-thinking settings; temperature 1.0; top-p 1.0; presence penalty 2.0; 32,768 tokens | 879 / 2,000 = **43.95%** | 232 | **0.30%** | **18,114,139** | **991** |

“Recorded seconds” transcribes the source's `meta.seconds`; it does not
claim to include startup, complete workflow cost, editor work or prior
training. The three conditions change multiple configuration variables, so
they do not identify the causal contribution of each individual setting. [B2]

The auditor uses a three-valued exact grader, not MIT's math-verify. In C3,
879 of the 1,768 decided answers are correct, or 49.717%; the remaining 232
answers were refused by the grader. We use the conservative 43.95% whole-sample
figure in the table and keep the decided-subset figure distinct. Neither
quantity should be silently substituted for MIT's grading convention. We also
do not adopt the auditor's maximum of first-sample and four-sample accuracy as
our estimator. [B1], [B2]

This is external execution evidence, not a result of the present Hepta run.
C4, an edited model under recommended thinking settings, was not run under
the auditor's budget. There is no complete editing-by-configuration factorial
comparison in that record. These data therefore do not prove that editing has
zero benefit. **They show why an unrepaired default configuration is an
insufficient sole baseline for a claim of superior weight optimization.**
That last sentence is this review's experimental-design inference. [B2]

The prior public record also contains an edited-model HF replication claim.
This review could not retrieve an immutable revision and its raw evaluation
files for the ML-Intern-lab repository with the available tool. Its quantitative
claim is consequently excluded from this pinned evidence table. It must not be
identified with another owner's checkpoint solely because the descriptions
are similar. The unresolved source is retained in `SOURCES.json`.

## 4. Turing controls: policy code and previously unseen mechanics

The same fixed Turing revision includes a direct program-policy comparator.
The model is asked to return a Python policy instead of neural weights, with
the same game objective and subsequent scoring. The reported Astra results
are: [T1], [T2]

| Game | Python policy score | Program discoveries | Weight-network mean score | Network discoveries |
|---|---:|---:|---:|---:|
| Breakout | 695.7 | 1 | 457 | 3 |
| Asterix | 127.0 | 1 | 66.2 | 3 |

These numbers are a screening comparison, not a well-powered paired
superiority test. The 1,000 evaluation episodes per generated controller do
not increase the count of independent controller discoveries. Turing's plan
also records missing model prices and missing usage from some timed-out
calls, so its published result table is not a complete dollar-cost comparison.
Its executed plan explicitly drops experiment 8; the existence of Qwen
setup notes in `SPEC.md` is not evidence that it replicated Qwen editing. [T2]

The later custom-game pilots provide a useful failure boundary. Three Astra
attempts per task reliably identify some spatial patterns yet fail to identify
whacking or shooting semantics in the custom games. The poisoning pilot
likewise reports failures to diagnose the actual trigger/behavior from raw
weights alone. These are small external pilot reports read here, not newly
executed trials or general failure-rate estimates. They caution against
equating a plausible circuit narrative with demonstrated causal understanding.
[T1]

## 5. Implications for the current Hepta study

The following are proposed controls and claim boundaries, not new empirical
results:

1. **Keep a strong zero-edit arm.** Compare the frozen incumbent with changes
   only to known terminal, sampling or controller configuration. If a policy
   bug can be repaired without weight changes, report that effect separately.
2. **Keep a code-policy arm.** A fixed, same-information Bellman or other
   program controller can distinguish finding a useful policy from compiling
   that policy into a small head. Include its planning and execution cost.
3. **Separate read, intervene and verify.** A raw-weight explanation proposes
   a mechanism. Matched causal interventions and retained-behavior tests
   establish its consequences. Neither alone proves long-horizon NDU gain.
4. **Keep the statistical unit honest.** Multiple worlds evaluated on one
   discovered edit do not create independent edit discoveries. Reused fit
   seeds and unknown historical selection remain explicit limitations.
5. **Charge the whole measured procedure.** Account for targets, observations,
   planning, candidate search, failed arms, editor inference, validation,
   replay and serialization. Unknown historical CPU/energy/API cost is
   unknown, not zero. A shared-preprocessing-free solver timing is not a
   complete method speedup.
6. **Keep mathematical scope typed.** A certificate about a fixed rounded
   linear subproblem, a norm ball, or a finite decision graph does not certify
   all weights, an unknown true environment law, full NDU optimization,
   device-level quality, or permission to install a model.
7. **Require new efficacy evidence for new claims.** A direct solve can be
   globally optimal for a declared quadratic while producing no useful policy
   improvement. A successful rebuild or independent byte verifier is separate
   from generated-answer evaluation and from independent edit discovery.

For Call/Put, reset, belief and continuation components, this means recording
exactly which algebraic identity or execution contract is preserved, and
separately testing the policy that consumes it. Preserving a probability
identity is useful feasibility evidence; it cannot substitute for full
task-value and cost evaluation.

## 6. Reproduction levels and release constraints

The MIT application script can reconstruct the published final edit from
the fixed base revision
`Qwen/Qwen3.5-0.8B@2fc06364715b967f1860aea9cf38778875588b17`:

```sh
python apply_edit.py BASE.safetensors RUN_EDIT_DIRECTORY OUTPUT.safetensors
```

It needs NumPy and the adjacent `st_numpy.py`. It checks tensor dtype, shape,
base SHA256 and rebuilt SHA256. This is a reproducible edit replay, not a
rediscovery of the direction. A new discovery run needs an independently
implemented compatible harness because the complete original agent/forward
harness and intermediate work directories were not released. [M2], [M9]

A capability replay additionally needs the frozen generation protocol and
complete outputs. An independent-discovery claim additionally needs hidden
edit hints, a declared discovery budget and repeated discovery sessions.
Hepta transfer additionally needs its actual checkpoint and freshly frozen
evaluation. None of these later stages follows from an earlier stage alone.

No original source code or large log excerpt is imported by this update.
For future reuse, MIT's scripts are MIT licensed, its logs/data/networks are
CC BY 4.0, and MinAtar source embedded in experiment-5 prompts is GPL-3.0.
Third-party benchmarks retain their own terms. Turing's code is MIT and its
copied content/run logs are CC BY 4.0, with the same MinAtar caveat. [M10], [T3]

## 7. New November 3 preprints: narrower repairs, stronger cost controls

The final source check on November 5 also found the primary manuscript
**Weight-space programming for auditing clinical decision networks**, arXiv
`2611.05341v1`, by Humza Nusrat and Omar Nusrat. Its code and records are fixed
here at `hnusrat1/weightspace-rt@19506e63f3ec859624ead33495469bc760e079ea`.
This is external experimental evidence that has not been peer reviewed; this work did not rerun it.

The study uses small synthetic rule-checking networks, with 433 parameters in
the main panel and up to 4,801 in its size check. Its frozen result table reports
detection in all 15 confound/threshold-drift networks but only one of three
trigger networks. The repair CSV has one record for each of 18 flawed networks:
16 successful diagnosed repairs, one failed forced edit, and one unchanged
missed trigger. Thus neither 16/16 conditional repair success nor hundreds of
thousands of evaluation requests represent 16/16 blind audit success. [C2], [C3], [C4]

The diagnosed repairs changed a median of three parameters. Fine-tuning also
repaired all 18 networks across five seeds per setting: the paper reports about
0.6 seconds per constant-rate run or three seconds using the original training
schedule. Weight audits took minutes. Simple flaw-specific statistics found the
same localized confound/drift defects; black-box audits were faster. These facts
do not support a general compute advantage for language-model editing. The
paper also reports that every repair writing weights of at least `1e5` failed
under FP16, and that a false alarm on a healthy network caused 2,018 new errors.
Only two of five healthy networks were cleared without forcing. Finite
double-precision repair is consequently not deployment qualification. [C1]

The released run table includes 71 audits; the seven initial audit attempts at
maximum effort were stopped after 65.8 minutes without answers. The authors'
README explains faulted-harness repeats, forced replies, and missing or partial
token counts. These must remain in a cost ledger; the successful final reply's
token count alone is not complete cost. Reproduction uses retained networks and
answers, while `reproduce.sh` also reruns gradient comparators and overwrites
results. The authors request at least 8 GB free RAM. Code is MIT; weights,
prompts, outputs and results are CC BY 4.0. [C2], [C5]

A second new primary preprint, Zheng and Doubao's
[arXiv:2611.04268v1](https://arxiv.org/abs/2611.04268v1), submitted November 3,
proposes localization, sparse edits and recursive evaluation for diffusion
image restoration. It explicitly labels itself conjectural. Its proposed
forward-call budget and recursive gains are hypotheses, not measured results.
No Git or downloaded-file identity was obtained for that manuscript, so it is
listed separately from the SHA-pinned empirical evidence in `SOURCES.json`.

For Hepta, the useful transfer is a protocol with explicit known mathematical
invariants, simple analytic diagnostics, strong non-edit alternatives, dtype
checks and real task-value gates. Sparse parameter count alone is not an
efficiency or reliability measure. This is a methodological inference from the
reported controls, not a new Hepta result.

## 8. What an REA-like native subsystem can borrow

The official REA project is **Reverse Engineer Anything**, a software analysis
tool, at `morluto/rea@71f680d7c1aa7a45ba0325fe87b104744b0c105f`. Its documented
MCP architecture preserves complete evidence records and stable parent
identities, exposes bounded projections, distinguishes unavailable observations
from empty observations, and carries explicit coverage. A completed static
inventory does not assert runtime equivalence. Its MIT license permits reuse
subject to the license conditions; no REA implementation was imported or run in
this review. [R1], [R2], [R3]

The corresponding Hepta design inference is to expose typed operations over
immutable checkpoint identities: inspect, form a bounded proposal, verify
declared constraints, evaluate a frozen task, and accept or restore. A proposal
should link every claimed circuit to observations and causal tests, and every
certificate to its exact variables, arithmetic and model-law assumptions.
Evidence pagination should preserve complete retained data rather than convert
an omitted tensor or state into an empty one. An AI planner can select the next
bounded operation while native primitives enforce those contracts. This
architecture does not itself establish that an agent understands an arbitrary
neural circuit, discovers optimal weights, or improves global NDU value.

## Primary sources

Every link below fixes a full Git commit. `SOURCES.json` records the associated
Git blob identities and claim limitations. These are provenance identities
obtained from source retrieval, not independent proofs of the empirical claims.

[M1]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/README.md
[M2]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/README.md
[M3]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/work_notes/experiment_history.md
[M4]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/edit/manifest.json
[M5]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/eval/unedited/merged.json
[M6]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/eval/p50c/merged.json
[M7]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/final_answer.md
[M8]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/gemma_followup/README.md
[M9]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/code/apply_edit.py
[M10]: https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/LICENSE
[B1]: https://github.com/carlostoledo1891/cert-machine/blob/76805430d50e396cae81a704bd17dc68152414fc/notes/wsp-stage3-preregistration-2026-11-02.md
[B2]: https://github.com/carlostoledo1891/cert-machine/blob/76805430d50e396cae81a704bd17dc68152414fc/certs/wsp-baseline.json
[T1]: https://github.com/alan-turing-institute/weights_editing/blob/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca/README.md
[T2]: https://github.com/alan-turing-institute/weights_editing/blob/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca/PLAN.md
[T3]: https://github.com/alan-turing-institute/weights_editing/blob/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca/LICENSE
[C1]: https://github.com/hnusrat1/weightspace-rt/blob/19506e63f3ec859624ead33495469bc760e079ea/paper/paper.md
[C2]: https://github.com/hnusrat1/weightspace-rt/blob/19506e63f3ec859624ead33495469bc760e079ea/README.md
[C3]: https://github.com/hnusrat1/weightspace-rt/blob/19506e63f3ec859624ead33495469bc760e079ea/data/table2_panel.csv
[C4]: https://github.com/hnusrat1/weightspace-rt/blob/19506e63f3ec859624ead33495469bc760e079ea/data/fig3_repairs.csv
[C5]: https://github.com/hnusrat1/weightspace-rt/blob/19506e63f3ec859624ead33495469bc760e079ea/runs_table.csv
[R1]: https://github.com/morluto/rea/blob/71f680d7c1aa7a45ba0325fe87b104744b0c105f/README.md
[R2]: https://github.com/morluto/rea/blob/71f680d7c1aa7a45ba0325fe87b104744b0c105f/docs/mcp-contracts.md
[R3]: https://github.com/morluto/rea/blob/71f680d7c1aa7a45ba0325fe87b104744b0c105f/LICENSE

