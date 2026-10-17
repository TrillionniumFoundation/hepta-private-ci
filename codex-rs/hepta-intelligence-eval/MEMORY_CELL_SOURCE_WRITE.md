# Source-only knowledge writing after the controlled reader diagnosis

This bounded research stage reuses observed controlled events, their calibrated
persistent hybrid baseline, event correction projection, exact source delivery,
verified ReferenceReader, and the existing LoRA artifact consumer. It neither
changes default serving nor authorizes a production model. It follows the useful
controlled Qwen event-reader result, not a claim that human-reviewed natural
language capability has passed. The pending independent review stays pending.

## What is newly tested

The write command takes only original observed Documents, an externally pinned
source file and the pinned model. It cannot receive a task plan, question file,
answer labels or retrieved test windows. At preregistered logical revision 2,
explicit correction closure derives all current unambiguous atomic relations.
They supply short controlled-schema question/value training examples. Unknown
conflicting keys are not arbitrary positives or null answers. This is authored
schema supervision from actually executed observations, not external human QA or
a newly learned general reasoning rule. Multi-hop final task labels never enter
the writer. All source dependencies, including revisions not used in loss, remain
in conservative revocation lineage.

A shared rank-4 query/value LoRA is trained for at most 128 updates and 65,536 input
tokens at learning rate 0.0002. Query examples are derived solely from source
relations; prompts are masked from completion loss. The BF16 base is immutable.
The artifact uses the existing safe tensor/layout/base/source consumer contract.
Every weight/manifest is synced before READY, and a NEW process loads that externally
pinned snapshot before opening the fixed test plan. The source corpus and public
schema are not novel independent observations; this is execution-order isolation,
not an assertion that old public tasks have become unseen prospective tests.

Both base and adapter-enabled conditions use one explicit memory-aware system
instruction, allowing evidence or stored knowledge but forbidding citations to
undelivered labels. This avoids making the parameter-only control impossible by
instruction. The system profile differs from older evidence-only experiments;
compare only matched new calls, never attribute cross-profile gains to memory.

Five arms share the same reader, token budgets and original candidate pool:
hybrid/base, organized/base, organized/module, parameter-only, and empty/base.
The parameter comparison keeps the exact actual evidence and prompt identical.
The learned-policy arm is not implemented in this stage and is explicitly reported
as missing; fixed correction rules are not relabelled learned policies. Source
facts are memorized before task exposure; training on sources is not evidence
that new procedural skills or cross-domain generalization were acquired.

The original eight controlled test cases cover new facts, corrections, relation
composition and program choices. Every generated procedure choice is executed by
the same fixed worker as the baseline, with no extra tool privileges or generated
code. All original answers are synced before scoring. Failed answers stay in the
complete census and fail execution. The scorer's narrow identifier grammar is
not an independent semantic judge. Module roots are ancestry, not citations.

## Costs, recovery and non-claims

The report preserves original source bytes, physical pre-export snapshot bytes,
model inventory, actual write/training/read time and token work, plus inherited
measured extraction/index costs with their original provenance. It also measures
the common procedure worker and a current-withdrawal rejection of the valid saved
adapter. Production retention, maintenance and cross-host recovery are unknown;
total lifecycle cost remains null rather than treating them as zero. An adapter
larger than its source is not called a compression achievement.

This is an isolated process reload and supplied-withdrawal experiment, not a real
production cutover, distributed consensus proof, unlearning certificate or three
qualified snapshots/two future windows. The read-only execution workflow stages
the already pinned Qwen research reader, runs all regressions, and does actual
training/inference offline. Neither base nor derived model weights are included
in the downloadable evidence artifact; manifests/hashes and original outcomes
remain. No production or superiority flags can become true here.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_experience_*.py' -v
HEPTA_MEMORY_TESTED_COMMIT=EXACT_SHA python3 scripts/memory_cell/experience_write_trial.py write SOURCES.json MODEL NEW_SNAPSHOT --source-sha SOURCE_SHA --stage-sha STAGE_SHA
HEPTA_MEMORY_TESTED_COMMIT=EXACT_SHA python3 scripts/memory_cell/experience_write_trial.py read PLAN INPUTS MODEL SNAPSHOT NEW_TASK_RUN --plan-sha PLAN_SHA --stage-sha STAGE_SHA --ready-sha READY_SHA
```

A temporary formatter may create a separate reviewed AST-equivalent candidate;
it never updates main or the PR head and removes itself from its candidate. The
actual experiment requires the repository format gate before any model work.
