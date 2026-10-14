# Hepta Adaptive Memory Cell Network — five-stage SHADOW increment

**2026-10-14. Source: stacked on PR #1697, itself stacked on #1546 and #1452.**
This package is a proposal/experiment reusing existing HNMF and DecisionCell
owners, not a second Memory OS, production model loader, source writer,
independent evaluator, network consensus system or Selector.

No component grants model activation, user/tool authority, FinalUse, signed
reviewer independence, future-window acceptance or split/merge publication.
Model efficacy cannot be inferred from passing unit tests. Keep shadow-only
until the full repository CI and independent review are complete.

## Five stages and evidence limits

| Stage | Executable research portion | Still missing |
| --- | --- | --- |
| 01 Reader | Strict immutable four-arm request identity, prompt/budget equality, premise removal, family isolation and review-receipt binding. Existing #1697/#1546 provide actual Reader dispatch and authenticated reviewer intake. | New independent human sufficiency decisions and model-answer execution. Source hashes alone are not signatures. |
| 02 SemanticMemoryCell | **Actual PyTorch Head.fit optimization** using the existing shared Head implementation; same-init frozen control, TRAIN-only labels, sealed source-bound predictions and feature identity. | New externally pinned pretrained Encoder weights/runs and future-task benefits. Mechanics fixture must never masquerade as HF model. |
| 03 HNMF graph | Source-bound frozen graph, topology-safe edge-weight training, independent/fixed/learned routing and transparent lexical BM25 control. | Strong hybrid RAG, calibrated entailment, integrated production HNMF graph ABI and proven real task improvement. |
| 04 Split/merge | Two genuinely trained child Heads from a detached parent and a genuinely distilled student. Initialization preserves parent output; actual per-stage parameters and training work recorded. | Same-budget unsplit control, future outcomes, old-task retention, error-free owner migration and production Selector. Refer to #1726/#1733/#1742. |
| 05 LongMemEval-V2 | Text-only lexical control matching official Memory.insert/query and persistence interface, provenance labels, checksum verification, query-only input and explicit screenshot limitation. | Actual 451-question run, trained AMCN backend, multimodal encoder, official judged scores and full end-to-end resource measurements. |

## Additional executed research interfaces

- amcn_native.py calls the existing physically loaded, locally tensor-verified
  LocalEncoder with canonical question plus exact source bytes and performs
  actual shared-feature batching. No model is downloaded or simulated when
  the pinned files are unavailable. An unsigned local tensor check is NOT an
  independent signed production admission. Real Head tensors can be sealed as
  safetensors with source manifest, model and prediction digests.
- amcn_multimodal.py adds typed text/image/audio/video spans and TRAIN-only
  pairwise contrastive projection. It executes actual PyTorch connector
  optimization on supplied feature tensors but loads no physical media tower;
  positive co-reference and negative cross-event training pairs are distinct.
- amcn_score.py compares the four original Reader arms using matching raw
  answer digests, independently supplied descriptive judgments, source
  citation labels, tokens and family-level conservative confidence intervals.
  It never declares actual reviewer independence.
- amcn_routing_audit.py compares independent Cell, fixed graph, learned routing
  and **externally supplied** genuine strong hybrid RAG outcomes under the
  same source, Reader and prompt identities. It cannot replace the original
  strong RAG execution or the independent Evaluator.

New work does not reinterpret HNMF's seven populations or any production
wire version. This is a research-only typed projection and training path.

## Commands and owner integration

From repository root in a CPU Python environment with PyTorch, numpy and Ruff:

    python -m unittest discover -s qualification/amcn-v1 -p 'test_*.py' -v
    python -m compileall -q qualification/amcn-v1
    ruff check --select E9,F63,F7,F82 qualification/amcn-v1/

The existing physically verified pretrained integration surface is
experiments/shared_stem_cell/execution.py LocalEncoder/encode_cases.
All pretrained experiments must reuse exact manifests, complete source and
input hashes and owner receipts. Fixture tensors are never real model evidence.
The package directly reuses this same branch's existing Head/fit optimizer;
no parallel trainer service, production Artifact writer or model call spine.

## Official LongMemEval-V2 adapter

Source: https://github.com/xiaowu0162/LongMemEval-V2 .
After separately installing the official environment:

1. Copy lme_v2_bridge.py to LongMemEval-V2/memory_modules/amcn_shadow.py.
2. Explicitly import AMCNShadowMemory from .amcn_shadow at the bottom of
   memory_modules/memory.py, so the official register_memory decorator runs.
3. Supply the following JSON as a memory config to official evaluation/harness.py:

    {"memory_type":"amcn_shadow_lexical",
     "memory_params":{"top_k":4,"max_records":100000,
                      "max_text_bytes":4096,"per_item_chars":2800}}

4. Use the official required data/domain/Reader flags and independently score
   the exact original answers. The bridge is a lexical-only control, not a
   learned Cell. It rejects source-cap overflow rather than silently omitting
   memory, and reports that screenshot queries have no vision model.

Compare real AMCN models against the official no-retrieval, RAG, notes and
AgentRunbook controls with the identical frozen Reader, question, source cut,
effect permissions and resources. Preserve original evidence source IDs,
citations, cost and omitted-source receipts.

## No-go and required production evidence

Still missing: sufficient-evidence Reader certification, strong cached hybrid
RAG comparator, proven family-independent memory-learning gain, same-budget
Cell split/merge advantage, independent future retention, full multimodal
evaluation, parameter unlearning, fleet crash/restart/rollback, independent
semantic citation evaluation and signed production admission.

Existing gates remain at least 200 effective independent samples at the
registered 95% confidence policy, three independent snapshots, two actual
future calendar windows, strict subgroup retention, zero resurrection,
independent Evaluator/Selector, and all required blocking CI. Simulation,
generation on prior source, fixture gradient steps, a hash receipt or a
Green check on older commits cannot substitute for those gates.

Cross-branch research #1726/#1733/#1742 must be semantically reviewed and
rebased by exact SHA; do not blindly overwrite more advanced owner fixes.
