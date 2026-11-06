# Independent internal audit of the frozen local model pilot

**Verdict: execution evidence passes; task delivery and model-selected tool
success do not pass.** This review independently reconstructs the recorded
qualification and pilot without generating another model token or altering any
frozen source, task, weight, response, or ledger file. It is an internal review
by `/root/theory_bounds`, not an external review or scientific confirmation.

## Observed outcome

| Run or arm | Model responses | Delivered / planned | Actual tools | Wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct task arm | 8 | 0 / 8 | 0 | 93.295715 | 147.585743 |
| Model-selected tool arm | 8 | 0 / 8 | 0 | 98.584078 | 157.937439 |
| Main run envelope | 16 | 0 / 16 | 0 | 191.885837 | 305.523182 |
| Separate qualification | 1 | Exact `[1]` received | 0 | 11.362962 | Not separately recorded |

The 16 task calls used 2,348 input and 1,452 output tokens. All returned valid
transport envelopes from the expected model. Every task failed the frozen strict
JSON parser before a tool or semantic verifier could run: 15 outputs begin with
Markdown fences and one begins with explanatory prose. Fourteen outputs reached
the 96-token limit; the other two contain 70 and 38 tokens. The audit independently
reproduced each stored `JSONDecodeError` and its message. This establishes a
format/delivery failure, not 16 independently evaluated semantic wrong answers.
No fence removal, extraction, repair, retry, or substitute answer was applied.

The successful qualification used 54 input and four output tokens. It is a
separate execution check and is not added to either task arm. The two runs contain
17 real responses in total. The main run used 16 of its maximum 24 model calls;
invalid first-stage outputs prevented all eight optional second-stage calls.
These counts and each request binding are in [audit.json](audit.json).

## Evidence independently checked

- All seven physical model files match the pinned manifest and materialization.
  The 269,060,552-byte weight file has SHA-256
  `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
  Model identity is `HuggingFaceTB/SmolLM2-135M-Instruct`, revision
  `12fd25f77366fa6b3b4b768ec3050bf629380bac`.
- Without instantiating a model, the audit read all 272 stored BF16 tensors and
  expanded their bits to float32 in chunks. The resulting 134,515,008-parameter
  fingerprint is
  `a711cd24baa0c1046b72c16c7bff836fefca65f760831db4d4f8900e8eafeef8`,
  exactly matching all 17 before/after receipt pairs. This checks a representation
  independent of the worker's live-parameter hashing implementation.
- All 17 payload hashes reconstruct from public questions, answer formats, the
  declared SQL schema, and frozen instructions. The model receives only a prompt;
  no expected answer or scripted oracle output appears in these inputs. Offline
  tokenizer-only replay reproduces every input token count and every decoded
  output. The audit does not run model inference, SQL, source tools, or verifiers.
- The main ledger contains 16 intent/terminal pairs and 16 host meters; the
  qualification ledger contains one pair and one meter. Every launched request
  has exactly one corresponding response and final event, and every response is
  accounted for. Raw receipt bytes match the recorded stdout hashes. All 16 saved
  episodes match the aggregate result, including all failures and their costs.
- The frozen source uses a fresh offline CPU worker per request, disables
  gradients, and verifies model identity and weights before generation. The
  actual Python/platform metadata and all 34 package versions and `RECORD` file
  digests match the frozen runtime manifest. These are software evidence checks,
  not an independent attestation of every installed binary or operating system.
- Request clocks, intent durability order, host coverage, serial execution, and
  UTC/monotonic consistency reconcile. Main request times range from 8.112637 to
  13.465848 seconds, within the 30-second request cap; every episode is within
  70 seconds and the run is within 1,200 seconds. These observations do not prove
  hard real-time behavior for unseen requests or an optimized stopping policy.
- All 63 audited input files have identical SHA-256 hashes before and after the
  audit. The source and result claims are checked against actual files, not only
  accepted from their embedded Boolean fields.

## Publication and cost boundaries

The GitHub API anchors commit
`611884815ee7c1b8ea87b282493aa1b5e014f829`, tree
`c0d94497e45eed6dc0f0a314bcf5cc3dbcbfa37b`, at 11:47:00 UTC on 6 November
2026; [draft PR #4971](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4971)
was created at 11:47:02. Qualification began at 11:47:03.160640 and the pilot at
11:47:52.314189, ending at 11:51:04.200009. The remote freeze bytes match the
local freeze. A second API check matches every one of the 17 frozen source files
plus `freeze.json` to its Git blob and size at that immutable commit. See
[remote-anchor.json](remote-anchor.json) and
[remote-source-binding.json](remote-source-binding.json), with the retrieved
directory inventory in [remote-directory-entries.json](remote-directory-entries.json).
Ordinary commit/PR timestamps are not independent external preregistration or
proof of all prior activity outside these recorded runs.

Actual host currency cost remains **unknown (`null`)**, while external paid
model API calls are zero. The main run records 305.523182 child CPU seconds and
0.055297 outer-process CPU seconds; the workers report 290.578300 CPU seconds,
176.797030 wall seconds, and 94.175339 generation seconds inside that envelope.
Qualification worker CPU is 12.960270 seconds, not a measurement of its complete
child-process lifetime. Host, worker, and generation wall times overlap and must
not be added as separate charges. Intent and terminal entries describe one
request, not two billable requests. No monetary net benefit can be computed from
these receipts without the missing host price information.

## Closed and open claims

The acquisition and real frozen-model execution blocker is closed for this
specific model, runtime, and task list. Public-input isolation, complete recorded
request accounting, parameter invariance, and observed deadline compliance are
supported within the inspected software boundary. There is no claim of an OS
security sandbox or unrelated-host-activity audit.

Task delivery fails at 0/16. Actual model-selected tool use is unobserved at zero
calls. A useful tool policy, NDU improvement over strong baselines, untouched task
confirmation, and positive net benefit remain unsupported. The eight disclosed
tasks come from two source clusters. No parser adjustment, larger model, extra
sample, or confidence claim is introduced to convert this frozen failure into a
success. No external reviewer endorsement is claimed.

## Reproduce the receipt audit

Run [audit_pilot.py](audit_pilot.py) using the original local runtime and an unused
output filename. It loads only the tokenizer; it never loads or executes a model.

```bash
/workspace/scratch/3f6a885bb83c/round3_resources/local_lm/venv/bin/python -B \
  /workspace/scratch/3f6a885bb83c/round3_pilot_audit/audit_pilot.py \
  --repo /workspace/scratch/3f6a885bb83c/hepta-research \
  --resources /workspace/scratch/3f6a885bb83c/round3_resources \
  --output /workspace/scratch/3f6a885bb83c/round3_pilot_audit/audit-replay.json
```

`--recorded-workspace` defaults to the original workspace because transport
hashes include the absolute paths used by the actual run. The JSON receipt
contains the auditor-script hash and every checked input hash. Its assertion
checks are not additional independent task observations.
