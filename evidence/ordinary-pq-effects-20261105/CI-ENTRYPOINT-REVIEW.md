# CI entrypoint review and ordinary PQ Chain continuation

## Reviewed source and scan scope

Implementation pin: Hepta `ee57cd57c322a8fecdf674a662c741452baf6478`. The complete scan was performed at `369a021af4a045da2feb7480a119e549694a5033`, compared with base `1556a4df6e279055fd8196f81a4ca2fe0f19384a`, then carried forward by final-pin tree/blob comparison and review of the new test and workflow step. Actual native execution records are kept in [the evidence index](README.md), separately from this entrypoint scan.

The complete directory inventories were read. Text inspection covered 88 workflow YAML files, 44 executable script sources under `.github/scripts`, 14 action files, all 103 Rust sources under `hepta-infer-worker-host/src`, its sole integration test `tests/cell_host_cli.rs`, 38 executable qualification sources and 9 QA sources/data files. The searches included legacy effect key/signature fields, provider kind, effect-host configuration names, schema selectors and ordinary daemon calls. No additional generator of schema 1/3 **automation effect host** configuration was found in this scope. Unrelated observation and FinalUse schemas were distinguished from effect-host configuration.

The final-pin directory trees were independently retrieved. The workflow tree changes only `hepta-pon-native-pair.yml`, from blob `7c0cb5ead4fb0a811ed286afee1472a903bd2200` to `7d2d0026784f8a3c92b0b000d8d986b966252ecd`; its five-line addition is described below. The inference-host source/tests, qualification and QA trees also remain identical to the scanned pin.

| Directory | Tree at base / scanned pin | Tree at implementation pin |
| --- | --- | --- |
| `.github/workflows` | `09d7a4af6e339a59078c606dd73803f62787d3b5` | `8b959648613076624e98aad279bf4df7429ea807` |
| `.github/scripts` | `5d637e47e514c9cd98a8dde7886aefe555c0393d` | Same |
| `.github/actions` | `ee95035049d3fa683e244e8c14b74a0e63844afc` | Same |

The [public-initial workflow][public-ci] invokes ordinary inference cases in [smollm_initial_agentd_tests.rs][initial-tests]. Their [fixture configuration][initial-fixture] loads Agentd and stages Evidence recovery, while separate PQ inputs supply inference authority; it does not configure the automation effect host. [PQ policy renewal][renewal-ci] selects authbus and Evidence recovery controls. Neither workflow supplies positive ordinary PoN effect evidence.

## Existing native Chain path

The [native-pair workflow][pair-ci] builds the original Node and signed-task fixture:

```sh
cargo +1.95.0 build --locked --release \
  --manifest-path ../chain/trillionnium/Cargo.toml \
  -p trnm-pon-node --bin trnm-pon-node --example hepta_task_fixture
```

It binds `HEPTA_PON_CHAIN_BINARY`/`HEPTA_PON_CHAIN_SHA256` and `HEPTA_PON_TASK_FIXTURE`/`HEPTA_PON_TASK_FIXTURE_SHA256`. Its original source-head is `04be5f02c84cf5cb626a53f34bc03a5bd6ff5137`; its prospective merge is `d7b97e4fc54ad5f25bae4da1393a94094352d5ff`, with base `dd6e1c3cbeacbdc532b0679297835b3a0aac78f0`. These are the existing workflow pair, separately identified from the broader source review of Chain `7ae0d1b2...`.

The two original positive selectors are:

- [real_chain_sealed_submit_reconcile_confirm_reorg][chain-test]: actual `status` and `make`, sealed adapter submission, lookup, confirmation and reorganization.
- [real_chain_signed_task_acceptance_confirm_and_reorg][task-test]: actual fixture `plan` and `prepare`, retained `accept.packet`, adapter submission and task observation.

Both construct `PonLocalProviderEffectAdapter` directly. Neither traverses ordinary `AgentdAutomationEffectHost::open`, FinalUse admission or AutomationStore. Passing either cannot fill that composition gap.

## Added continuation: native FAIL, full-path qualification BLOCKED

The [new independent ignored test][ordinary-test] `real_chain_ordinary_pq_loader_dispatches_once_and_reads_original_receipt` reuses the first case's native `Chain::call` and `Chain::packet` helpers, plus the existing signed Unix `PqFixture`. Only test visibility and module declarations change in those helpers. Its published blob is `704544993b0c83aa1eb1333390577de4823c5fa2`, checked against the frozen source. This is separate from the earlier [inert-ELF loader and tampering control][loader-tests], which passed at the implementation pin in the 38-test ordinary effects group and still makes no Chain-execution claim.

It specifies schema 4 ordinary loading, a real ML-DSA grant, original AutomationStore execution and actual Node submission on **both** `legacy-v2` and `authenticated-v1` backends. Its assertions cover stable provider identity, exact wire/payload, one consumed nonce, matching native block/receipt, and exact terminal readback after owner reopen, local trust shutdown and relocation of the test-owned Chain namespace. On a successful run, the last control would show readback independence from provider availability; it does not measure process-start counts.

The original 30-second command/adapter deadline, 64-KiB output limit and 1-MiB packet-helper ceiling remain. Ordinary Agentd's stricter **24-KiB wire limit** also applies: an oversized real packet must block qualification. Evaluation/task/model profiles remain `legacy-first-two-v3`, `legacy-task-v1` and `linear-expert-dev-v1`; the test makes no claim that Chain task authority is PQ.

A five-line workflow addition, adjacent to the original pair cases, requires:

```sh
python3 scripts/hepta_ci_exec.py \
  --output "$RUNNER_TEMP/pon-pair/pon-pq-ordinary-owner.json" \
  --minimum-tests 1 -- \
  just test --locked -p codex-hepta-agentd --lib \
  -E 'test(real_chain_ordinary_pq_loader_dispatches_once_and_reads_original_receipt)' \
  --run-ignored only --no-capture
```

No existing assertion, selector, source-pair constant, timeout or workload budget is weakened. Missing environment pins cause failure when the ignored test is explicitly selected; there is no successful missing-input skip. Whole-image rollback with independently deployed custody and physical power loss remains untested.

### Actual execution at the frozen source

The exact selector above was run through the original lower-level `just test` command at Hepta `ee57`, using the verified `04be` Node with SHA256 `095458755051afd137478145a42b5edb94ee32587837e4723931317900a955d9`. The local run did not execute the full-checkout `hepta_ci_exec.py` wrapper. Authoritative job `1a1ac341327-fc05-52dc` exited **100**, with **1 test run / 0 passed / 1 failed / 259 skipped**. Both attempts under the original retry policy failed at `49,508 > 24,576` bytes.

The first `legacy-v2` iteration generated the real packet and stopped before constructing the signed PQ fixture or ordinary host. The `authenticated-v1` iteration, grant consumption, Node submit and receipt/recovery assertions were not reached. No `PON_ORDINARY_PQ_PAIR` observation exists. [Full original log](native/rog/agentd-real-chain-ee57cd57.log), [receipt](native/rog/agentd-real-chain-ee57cd57.receipt.json) and [terminal](native/rog/agentd-real-chain-ee57cd57-terminal.json) are retained.

The [fixed-source boundary](TRANSPORT-BLOCKER.md) proves that this is the codec's minimum complete packet, not an avoidable transaction-size choice. The required CI step is kept as a known failing qualification gate, and the PR remains Draft. Original limits, workload, profiles, assertions and source pair are unchanged. No source or prospective-merge lane is assigned a pass on the strength of a Node build or lower-level adapter result.

[public-ci]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/.github/workflows/hepta-public-initial-v2.yml
[initial-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-infer-worker-host/src/smollm_initial_agentd_tests.rs
[initial-fixture]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-infer-worker-host/src/smollm_initial_host_tests.rs
[renewal-ci]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/.github/workflows/hepta-pq-policy-renewal.yml
[pair-ci]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/.github/workflows/hepta-pon-native-pair.yml
[chain-test]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pon_chain_tests.rs
[task-test]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pon_task_chain_tests.rs
[ordinary-test]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_chain_tests.rs
[loader-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_tests.rs
