# Controlled SmolLM native pair execution

This adds execution wiring for two existing ignored tests from Hepta source
`3e9efb15faa261a4dc3ffc3205cd259aaee41a3f` (PR #3293). It does not change their
Rust code or create an issuer, product bootstrap, independent holdout, release
publisher or installation permission. The new workflow source and actual PR
merge must still be executed; static checks do not satisfy native acceptance.

## Source and environment

The existing `hepta-pon-native-pair.yml` supplies the exact Hepta source/base/tested
tuple and matching Chain tuple. Its checkout, canonical merge checks, V8 setup,
Rust/nextest installation, offline dependency preparation and final source checks
remain the owners of that configured environment. The new script also reuses
`candidate_plan` for both repositories before and after work. No source result is
borrowed for another lane, tree, run, attempt or job. Chain source/actual-merge
pins are an explicit integration input; this patch does not invent new pins.

Only the existing `ubuntu-24.04` x86_64 source-head and base-merge lanes run these
model experiments. The original ARM and Windows gates are unchanged; their model
execution is not claimed. The existing isolated `pon-model-env` receives the
previously exercised Python 3.12 CPU versions: torch 2.9.1+cpu, transformers 4.57.3,
peft 0.18.0, safetensors 0.7.0, tokenizers 0.22.2, numpy 1.26.4 and accelerate 1.12.0.
Transitive installed versions are retained, not presented as a fully hash-locked
Python environment. No GPU wheel/profile or fallback is used.

The public model is `HuggingFaceTB/SmolLM2-135M-Instruct`, revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`. All seven upstream files use the
unchanged Chain family/runtime byte lengths and SHA-256 pins. The 269,060,552-byte
weight file has SHA-256
`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
The source files and original material manifest remain auditable. Model downloads
live outside the uploaded observation directory; the manifest is retained there.

## Commands and owners

Preparation calls the existing `scripts/llm_inherited_runtime.py train` once per
generation with its original supervisor, `--threads 2 --steps 10`, and the 12
original public `runtime.tasks()` training rows. Generation 1 uses explicit
`--bootstrap`; generations 2 and 3 consume the prior actual parent descriptor and
its SHA-256. This bootstrap produces test training material, not a product
bootstrap. The script never resamples training, retries a failed generation or
substitutes a reported gain. Training files and receipts remain under `gen1/`,
`gen2/`, and `gen3/`; only complete pinned parents produce the two absolute configs.

The workflow uses these original commands through `hepta_ci_exec.py`, with a
minimum of exactly one observed passing test per command:

```sh
just test --locked --profile smollm-pair -p codex-hepta-infer-worker-host --lib -E 'test(=smollm_neural_read::tests::native::real_smollm_parent_query_original_control_final_use_and_terminal_unload)' --run-ignored only --retries 0 --test-threads 1 --no-capture
just test --locked --profile smollm-pair -p codex-hepta-agentd --test neural_comparison_native -E 'test(=real_gen2_gen3_forwards_score_only_after_original_holdout_consumption)' --run-ignored only --retries 0 --test-threads 1 --no-capture
```

`HEPTA_PN3_NEURAL_NATIVE_CONFIG` and `HEPTA_PN3_NEURAL_COMPARISON_CONFIG` point to
the prepared JSON files. The first test owns FinalUse claims, cross-owner/body
refusal, denied reads, exact control recovery and terminal unload. The second
owns the original holdout consumption, 32 paired decisions/64 forwards, 66 control
requests/FinalUse claims, scoring, qualification disposition and unload. A failed
first test does not prevent the second independent experiment from retaining its
own result, provided preparation succeeded and the workflow was not cancelled.

## First declared harness budget and qualification boundary

The new `smollm-pair` nextest profile matches only those two selectors, uses one
test thread, zero retries and a finite 15 × 60-second harness watchdog. Its
default inheritance works with the pinned nextest 0.9.103; the newer explicit
`inherits` feature is not required. Old profiles and internal worker/FinalUse/
holdout deadlines are unchanged. Outer CI owners bound dependency setup to 900s,
preparation to 1200s, each native command including compilation to 1200s, and
readback to 180s. The existing total job limit remains 60 minutes. These are
experiment ceilings, not throughput/latency guarantees or reclassification of
any earlier timeout. Insufficient time or resources must remain a failed run.

Preparation requires at least 6 GiB currently available RAM and 8 GiB free disk
after the existing builds, CPU execution and outbound HTTPS to the pinned public
materials/package sources. Two model sessions coexist in the comparison. A runner
that cannot meet these requirements needs an appropriately provisioned existing
executor; a smaller substitute experiment cannot satisfy this lane. No local
Hepta Rust, Cargo or Bazel execution is needed to review the patch.

All original raw seed/precommit, logs, forward rows, control journals, dispositions
and failed attempts are retained under the existing per-run-attempt artifact.
Readback checks the actual command, source/run identity, log digest, parent links,
false qualification flags, journals and complete original observations. The
original disposition is retained even when it is Ineligible. `readback.json`
always says `adoption: no-update`: a controlled fixture does not become an
independent holdout, ordinary cognitive qualification, product installation or
public reward authorization, even if its original statistical gate passes.

Static validation is `python3 -m unittest -v scripts.tests.test_hepta_ci_smollm_pair`.
It parses shell/configuration and exercises rejection paths without running a
model, Rust command, simulated successful native execution or substitute owner.
