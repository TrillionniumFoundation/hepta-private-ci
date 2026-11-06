# Frozen local-model pilot: execution passed, task contract failed

This is the outcome of the protocol published before inference in draft
[#4971](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4971),
commit `611884815ee7c1b8ea87b282493aa1b5e014f829`. The model is
`HuggingFaceTB/SmolLM2-135M-Instruct` at the registered immutable revision.
The source/task freeze remains unchanged. All results below are disclosed
engineering development evidence; no independent confirmation is claimed.

## Complete observed outcome

| Arm | Planned and completed episodes | Correct | Delivered | Model calls | Tool calls | Inclusive episode wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct answer | 8 | 0 | 0 | 8 | 0 | 93.295715 | 147.585743 |
| One model-selected tool | 8 | 0 | 0 | 8 | 0 | 98.584078 | 157.937439 |

The separate qualification request returned exactly `[1]` in approximately
11.345618 measured request seconds. It is not a seventeenth task episode and
is not included in task accuracy. There were **17 real model responses total**,
including this qualification. No paid external model API was used.

Every task model request completed with transport status OK and the expected
observed model identity. Every output then failed the registered exact-JSON
parser. Typical outputs were fenced Python programs, explanatory prose or
unfinished structured examples. The raw generated programs were treated as
text and never executed. In particular, no tool plan passed admission, so no
SQL/source tool or task verifier was invoked by either arm. Calling these
episodes successful tool use would be incorrect.

All malformed outputs remain failed episodes with quality zero. There was no
retry, code-fence stripping, output repair, task deletion or oracle fallback.
The deadline includes model loading, hashing and generation. Actual CPU and
wall time are distinct resources; nested host/request envelopes must not be
added together as independent elapsed time. Monetary host cost is unknown.
The public-weight acquisition and runtime installation records remain in
`evidence/acquisition/`; failure does not erase those development costs.

## Evidence and reproduction

`evidence/execution/archive-index.json` binds every original byte of the
qualification and task runs. Two deterministic gzip/tar archives contain all
37 original files: raw model responses, request intent/terminal/host records,
16 episode reports and both run reports. Compression changes storage only.
Restore and verify the complete originals into a new directory:

```bash
python experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_frozen_lm_pilot_20261106/restore_execution.py \
  --destination /tmp/ndu-local-model-originals
```

The independent internal audit is recorded alongside these archives. It is
separate from the execution and cannot turn these failed task outcomes into
successful confirmation. A later model follow-up, if executed, is a separately
declared development experiment on the same disclosed tasks; it cannot replace
this result or count as untouched validation.

The missing-callable-model constraint is resolved for this specific public local
model. Task-level JSON compliance, model-selected tool execution, superiority
over strong baselines, real monetary net benefit and independent generalization
were not established by this pilot. The NDU scale-up gate remains closed.
