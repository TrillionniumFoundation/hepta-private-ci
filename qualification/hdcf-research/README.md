# HDCF shadow qualification: Stem economics and reasoning-graph interfaces

Status: **RESEARCH_ONLY / DENY_ALL / NO MODEL SELECTION / NO CODE EXECUTION**.

This package is intentionally independent of the live Neuron, NDU, Agentd,
CNS, CellSplit, model Worker, Artifact CAS, FinalUse and OS effect owners.
It adds no runtime API and never grants capabilities.

## Reproduce

From this directory:

```sh
python3 -m unittest -v test_hdcf_gates
python3 -O -m unittest -v test_hdcf_gates
printf '%s' '{"schema":"hepta.hdcf.shadow.v1","mode":"stem_cost","payload":{...}}' | python3 hdcf_gates.py
```

The executable uses **canonical bounded JSON**, rejects duplicate keys,
nonfinite values, identity omissions and unknown fields. Valid output is a
non-authorizing source-bound diagnostic receipt.

## Hypotheses and limits

1. **Weight-only Stem accounting.** Compare `N * Encoder` with
   `Encoder + Organ + N * Head` under explicitly matched weight precision.
   This estimates weight bytes only, not physical resident memory, encoder
   forwards, CUDA scheduling, FLOPs, energy, model accuracy, negative transfer,
   cache eligibility or lifecycle TCO. A claimed same input is not a verified
   physical input/authority receipt. Cross-principal reuse is not admitted here.
2. **Finite DAG consistency.** A topologically ordered reasoning graph
   requires bounded local residuals, forward and backward parent-child
   continuity, terminal-leaf coverage, matched declared terminal utility,
   exact source/objective identifiers, and total budget within an explicit
   upper bound. A DAG does **not** establish stochastic filtration,
   conditional expectation validity, well-posedness of an FBSDE, global
   solution existence/uniqueness, reasoning correctness or task success.
3. **No execution authority.** CPU JIT, GPU module load, executable memory,
   OS accessibility mutations and arbitrary action/tool calls are not
   implemented. Unknown modes fail closed. Any future native-action backend
   must use independently verified FinalUse, durable effect ownership,
   current generation and outcome reconciliation.

## Required evidence before stronger claims

* Frozen exact pretrained Stem/Reader weights, tokenizer, normalization,
  source-family and task split, independently held labels and genuine
  task-reader execution. Compare pretrained ModernBERT, mmBERT,
  EmbeddingGemma 2 and an exact legacy 421M checkpoint if available.
* Actual 64/256/1024/4096 live Head inventory and real Encoder forward
  counts, CPU/GPU RSS, p99, power, concurrency, cache reuse and restart.
* Matched no-change, cheap baseline, recurrent, critic and NDU ablations.
  External outcome and total paid learning/inference/evaluation costs matter.
* Real image/audio/video temporal necessity and generator-decoder evidence.
* For any native Computer Use, identical tasks/authorization and actual
  observation, planning, dispatch, external effect and readback timing vs
  existing tool/MCP path; never call pure binary-vs-JSON echo an MCP comparison.

Existing owners and specification remain authoritative:
`docs/DEVELOPMENT.md`, `docs/learning/NDU_FBSDE_SPEC.md`,
`docs/cns/TECHNICAL.md`, `docs/hnmf/TECHNICAL.md`.
