# Independent runtime bank media review

The first execution of the published independent auditor passed for all three
frozen-model seeds and both registered fitting/selection roles. The receipt is
`/tmp/hepta-field-v3-run/INDEPENDENT_RUNTIME_BANK_MEDIA-frozen.json`, SHA-256
`1983cf15a80e7cfd00cefda02097d2b212acb5f1fb720b8804d58bf788d87ecd`.
The first-attempt log is retained beside it. No scientific source, threshold,
target, controller, or generated output was changed during this verification.

## Coverage

| Independently checked item | Count |
| --- | ---: |
| Complete source/corruption trees | 2,304 |
| Actual terminal rewards and charged values | 195,840 |
| Logical output deliveries | 195,840 |
| Public 16-coordinate events | 48,384 |
| Simulated partial-verifier feedback packets | 46,080 |
| Complete-tree journal nodes | 6,120 |
| Unique physical H3M records | 175,104 |
| Physical H3M bytes | 190,771,892 |
| Exact discrepancies | 0 |

The auditor independently reconstructs the registered source pairs, corruption
batch seeds, target layout, and public masks. It checks the entire 85-node tree,
including all branch identities, parent-to-child delivery order, and the absence
of missing or additional nodes. Every H3M component is decoded from its actual
bytes; PNG profile/CRC, UTF-8, retained little-endian public logits, component
hashes, container extents, and first-delivery versus physical-reuse flags are
checked. All physical records must be referenced.

Each terminal reward is recomputed from its decoded image/caption and the pinned
reward observer, including the actual initial-plus-revision charge. Each of the
21 decision-node events is rebuilt from the public outputs and, where permitted,
the independently recomputed feedback. The resulting records must agree exactly
with both the journal and the fitted `bank.npz` arrays. The complete resource
ledger is also reconstructed rather than inferred from elapsed time.

## Verification cost and provenance

This additional verification used **258,048 reward-observer digit forwards**,
with zero audit-observer, generator, or native-kernel forwards. The observer cache
served 244,224 logical image-pair requests; logical requests and executed digit
forwards are separate quantities. Wall time was 253.939 seconds and process CPU
time was 245.880 seconds. These costs belong to independent verification, not to
the originally reported study computation.

Both observers' original asset identities were checked, and their parameters
remained unchanged. The receipt binds every bank archive, H3M container, journal,
parent/child completion receipt, registered source freeze, and auditor source.
The separate native fitting audit binds the same bank artifacts and independently
checks the head fitting, candidate-owned continuation targets, and frozen
selections. Together these receipts cover actual-output label truth and the
subsequent calculations using those labels.

## Limits

The retained public logits are checked against the exact H3M bytes and their
public softmax is recomputed. This audit does not regenerate neural decoder
logits, reexecute generators, or establish a new independent experimental
replication. It does not determine whether the selected policies outperform
fixed or equal-information historical controls.

Only `runtime_fit` and `runtime_select` tasks were constructed for this audit.
No `runtime_audit`, `primary`, or `retention` tasks were constructed or scored.
Independent selected-path qualification remains necessary. These results do not
change the V2 negative or uncertain findings, do not close held-out efficacy or
retention questions, and make no claim about production calibration, native
owner integration, unrestricted media, or LLM-scale behavior.

The audit implementation is [runtime_bank_media_audit.py](runtime_bank_media_audit.py).
Its pre-execution synthetic receipt is
[RUNTIME_BANK_MEDIA_CONTRACT_TESTS.json](RUNTIME_BANK_MEDIA_CONTRACT_TESTS.json).
