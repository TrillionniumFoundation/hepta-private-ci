# Token evidence V4 reproduction

This research stage retains the frozen V3 Granite checkpoint and native binary.
It does not consult hosted CI or authorize production promotion. Run phases in
the order below; fresh official validation is evaluated only after both model
campaigns have frozen their artifacts.

## Inputs and environment

- Python 3.12, CPU FP32, PyTorch 2.6.0+cpu, Transformers 4.57.1.
- Granite `ibm-granite/granite-embedding-97m-multilingual-r2`, revision
  `835ad14087e140460703cf0fae09f97d469d65c2`, acquired by `group_encoder.acquire`.
  Retain its five pinned files and `material.json`; no remote code or network
  lookup is used during fitting/evaluation. All 74 tensors remain frozen.
- Official SuperGLUE-v2 MultiRC archive, extracted to `$source`:
  `https://dl.fbaipublicfiles.com/glue/superglue/data/v2/MultiRC.zip`.
  Archive SHA256 `b3cd440856e72eb166b2edcd37b798455f1ebd51f2c3de64c0c2a4e1971d2737`.
  Exact `train.jsonl` SHA256
  `bb73d0838618f8269190a2533fead3140607558975ea0df6511fa534e8d3535c`;
  `val.jsonl` SHA256
  `d2b480195b15574ac00d52c4479f630bc161a7ab2de77e970fd00652846953ee`.
- `$previous` is the exact V3 `design.json`, SHA256
  `f0c8feb8b6fdfb36a3a6273111bebab001f0c5445dcaa6882769c1c5e2076283`.
  It is present in the V3 raw evidence archive. All 83 validation paragraphs
  were parsed previously; only V3's scored 16 paragraphs are excluded from the
  new held-out sample. They are retained as a separate regression panel.
- `$native` is the existing `ndu-group-control` binary. Rebuild with
  `build_group_native.py --repo "$repo" --output "$build" --binary ndu-group-control
  --cargo "$cargo" --clippy` if needed. V4 does not modify native Rust sources.

Set `$repo`, `$python`, `$source`, `$snapshot`, `$previous`, `$work`, `$native` to
local paths; `$work` must be a fresh directory. Run from the repository root.
The CLI fixes PyTorch to one thread. Do not run latency comparisons concurrently.

## Nonfinal preparation and tiny fitting gate

```bash
"$python" qualification/stem-cell-v1/token_prepare.py prepare \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --output "$work/prepared"
"$python" qualification/stem-cell-v1/token_prepare.py gate \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --prepared "$work/prepared" --output "$work/gate" --steps 1000
```

The gate uses eight complete training questions and four generated binding
groups. It requires ≥95% natural training accuracy and ≥95% paired-world
correctness. This establishes tiny-set learnability only. It does not establish
generalization, genuine reasoning, or an optimal shared Encoder.

Token features preserve all original non-special token IDs. The frozen Encoder
processes chunks of at most 64 model tokens independently; it does not provide
cross-chunk contextualization. Public facts, question and candidate remain
distinct. Whole cases exceeding registered limits fail explicitly. Pooled and
token models have the same parameters and common token projection; the pooled
control collapses tokens before alignment. Their arithmetic cost differs.

## Fit and freeze before fresh evaluation

```bash
"$python" qualification/stem-cell-v1/token_campaign.py train \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --prepared "$work/prepared" --gate "$work/gate" --output "$work/main" --steps 1000
```

Five models per seed use seeds 41/47/53: pooled one-step, token one-step,
token one-step with interventions, token depth 1–3 with interventions, and a
separately trained evidence-masked query control. One-step and state-reset
inference reuse the recurrent model. Every model has 38,466 parameters.
Intervention updates replace approximately 50% of natural updates; actual
exposures and depths are recorded. Equal update limits do not imply equal cost.

There are 64 natural training paragraphs and 16 source-disjoint tune paragraphs.
Each inference arm selects a probability threshold on the same complete tune
questions, using the fixed grid 0.05 through 0.95. Selection maximizes F1a, then
question EM, then closeness to 0.5, then lower threshold. Raw probability >0.5
scores and all-positive/negative baselines are also retained.

Before calling `token_campaign.py evaluate`, train/freeze the native campaign:

```bash
"$python" qualification/stem-cell-v1/token_native_campaign.py train \
  --campaign "$work/main" --prepared "$work/prepared" \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --native-binary "$native" --output "$work/native" --steps 1000
```

Its verifier uses eight additional source paragraphs; critic fitting and calibration
each use eight further disjoint paragraphs. Native control uses a frozen
next-correctness surrogate. It is not a general FBSDE solver or certified future
gain estimate. All native comparison arms use the same argmax decision rule.

The main Reader was fitted with zero feedback, leaving its feedback weight
columns at their initial values. Before native fitting or fresh evaluation, the
native CLI therefore wraps every loaded main Reader in `ZeroFeedbackReader`.
This preserves the exact parameter digest and always passes `feedback=None` to
the original state update. The policy is `disabled_untrained_channel`; verifier
observations control acceptance/stopping and never correct the Reader state.
The critic still consumes six state/logit/step features, not verifier
probabilities. Under this policy, fixed3/no-verifier Reader predictions should
match; their measured verification cost can differ. Main runtime sources remain
unchanged; only the separately frozen native CLI supplies this wrapper.

```bash
"$python" qualification/stem-cell-v1/token_campaign.py evaluate \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --prepared "$work/prepared" --gate "$work/gate" --output "$work/main"
```

The main phase evaluates seven arms and full/deleted evidence on 945 new
candidates (187 complete questions), the old 747-candidate regression set, and a
separate generated final domain. Only then run native evaluation; it restores
the already measured final token cache:

```bash
"$python" qualification/stem-cell-v1/token_native_campaign.py evaluate \
  --campaign "$work/main" --prepared "$work/prepared" \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --native-binary "$native" --output "$work/native"
```

## Audit, cost and interpretation

The historical native CLI rejects its first evaluation before inference:
its document schema replaced the membership schema, but its guard compares both.
Retain that failed command receipt and log. The separately versioned
`native_token_schema_recovery.py` validates both namespaces and every remaining
membership field, repeats the original full source checks, and maps only the
returned membership copy's schema. It leaves the original forty runtime files,
models, verifier, critic and cost policy unchanged. It refuses any existing
native final directory. The recorded campaign continued using:

```bash
"$python" qualification/stem-cell-v1/native_token_schema_recovery.py \
  --campaign "$work/main" --prepared "$work/prepared" \
  --source "$source" --snapshot "$snapshot" --previous-design "$previous" \
  --native-binary "$native" --output "$work/native" \
  --failed-command-receipt "$failed_receipt"
```

`$failed_receipt` is the original supervisor JSON: its two `commands` record
main exit 0 and native exit 1, with the rejected native command's `log` path.
The recovery entry point and its start/completion attestations are additional
execution provenance created after main evaluation. Fitted artifacts and
numerical policies remain those frozen before main evaluation. Never overwrite
the original failure or count it as a successful native evaluation.

Run `token_review.py --help` for official-label, paragraph isolation and physical
batch review, and `token_binding_review.py --help` for independently solved
ownership/storage worlds. The natural reviewer also replays internal threshold
selection and checks frozen model file bytes. Reviewers do not independently
authenticate execution timing or model provenance beyond their stated checks.

The official MultiRC files have no evidence-sentence annotations. Only the
generated ownership/storage domain supplies explicit support and opposite-label
worlds with identical question, candidate and word counts. Natural deletion
keeps the original labels and measures sensitivity; it is not a causal target.
Generated final people and objects differ from generated fitting vocabularies.

Physical batch CPU/wall receipts are charged once. They include padding and
measurement overhead; they are not individually measured per-answer latencies.
Outer phase receipts additionally include loading, hashes, serialization and
verification. Inner receipts are decompositions and must not be added again.
Encoder reports preserve cumulative cache-origin encoding cost separately from
current reload/restore cost. Unsupported complete formula counts remain null.
Native child CPU is additive to parent CPU; native wall is already inside
parent wall. Report training, preparation and inference separately. No strict
equal-compute or full lifecycle economic qualification is claimed.

The repeated model seeds evaluate the same source items; they do not multiply
the number of independent held-out examples. Persist
`all_scored_validation_source_hashes` when preparing future stages so neither
V3 nor V4 paragraphs return as a fresh holdout.

For local tests, provide `HEPTA_NATIVE_CONTROL_BINARY`,
`HEPTA_NDU_GROUP_CONTROL_BINARY` and `HEPTA_NDU_GROUP_REPLAY_BINARY` using the
actual binaries described above. Preload `torch._dynamo` outside measured scopes
before discovery: the first optimizer initialization otherwise imports it inside
an older strict-meter test and fails on unrelated warmup operations. The final
local run uses:

```python
import sys, unittest
import torch._dynamo
suite = unittest.defaultTestLoader.discover("qualification/stem-cell-v1", pattern="test_*.py")
result = unittest.TextTestRunner().run(suite)
sys.exit(not result.wasSuccessful())
```

Run repository-required `just fmt` after final code changes; do not wait for
hosted CI.
