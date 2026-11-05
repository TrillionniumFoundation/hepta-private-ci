# Input-chain diagnosis after the first real dual run

The prior run completed real generation but returned nine byte-identical VLM
texts, including critiques of different images. Its original evidence is
preserved under `evidence/real_20261105`; these interventions cannot rewrite it.

The diagnostic crosses three actual images (the prior 512-thumbnail input,
the prior generated draft and a new white image) with two neutral prompts.
The prompts contain no bee/flower answer or previous plan. Cases run in a
registered forward/reverse image order, each with a newly loaded model.
Module imports, process allocators and OS file caches can remain warm.

The existing `LocalModels.describe()` path is observed with spies that return
its unmodified real template and generated tensors. Each case retains:

- Original image and instruction identities plus the rendered chat template.
- Input token IDs and the hashes, shapes and dtypes of actual input tensors.
- Vision encoder hidden-state hashes when the architecture exposes the hook.
- Output token IDs, EOS/length stopping reason, full text and its hash.
- Actual generate call count, model identity, CPU/wall cost and process peak RSS.

An empty vision trace does not prove encoder execution: it remains a diagnostic
gap. Changed input/feature hashes alone do not demonstrate useful conditioning.
Different outputs alone do not validate semantic correctness. If the outputs
remain constant on blank and changed images, a generator training experiment
must not hide that failure by fitting one memorized caption.

The CLI requires six completed real calls, but never sets semantic acceptance.
Tracing overhead and fresh loading are included in measured intervals; these
timings are not a performance comparison with the earlier untraced run.
The dedicated workflow verifies input hashes against the prior review, saves
source identity, reuses exact model pins and preserves original failures.

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.diagnostics --models /tmp/dual-models --original /tmp/input.png --generated /tmp/direct.png --output /tmp/diagnostics --source-sha EXACT_SOURCE_SHA
```
