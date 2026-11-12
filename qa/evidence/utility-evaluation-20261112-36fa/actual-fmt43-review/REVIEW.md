# Actual V5 formatting transition: independent Rust review

## Conclusion

No non-format semantic change was identified in the **43 actual Rust postimages**. The review accepts these bytes as formatting changes for subsequent integration. It does **not** establish a test PASS or final exact-source qualification.

This review used the retained native `fmt.after` packet, not predicted formatter output. Every one of its 43 before/after pairs was decoded and independently checked against its recorded byte length, SHA-256 and Git blob identity. The preimage also matches the unchanged source index entry; permissions and index mode remain unchanged. The packet contains only regular Rust files under `codex-rs/hepta-agentd/src/`.

## Exact input and scope

- Unchanged source HEAD: `9c4a11f61d30e9cc352bf44d56c98909d202a55d`; its commit tree remains `ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7`.
- Raw actual transition packet: 1,236,802 bytes; SHA-256 `d14a414ea9853357e5260eadf523a9e09117e1ce19f674ff5a96baafe6a36082`; computed Git identity `600932e6e7c974005a31272eb0c3343ef2e731fc`.
- The raw JSON was not separately uploaded under that computed identity. Its durable gzip object is `9d59f7236fa59884d5cb669afcdff6b205e90327`; lossless base64 companion is `d214d07a5ae9ddc569360f8ba33a83b992b18f56`. Decode the companion and gunzip to recover the exact raw input.
- Before inventory SHA-256: `c006da7852740c7c24961a4748744eb1270f25c8d8fe95c2fc873d4dc279d79d`.
- After inventory SHA-256: `3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f`.
- Root/native report the resulting physical tree as `65b898bad23cd58c7f6fd53fafe618f9cf9562dc`, with 15,188 files. Full-tree reconstruction and original execution-status verification are separate retained audits; this review independently checks the complete 43-file delta.

## What changed

Four files have exactly the same code-token stream, with only whitespace changes. After separately comparing complete top-level import bindings and module declarations, ten files have no body-token changes at all. All 43 preserve import visibility, attributes, aliases, glob imports and imported paths. Grouped imports were split into separate equivalent imports where needed. Nested imports were left in the body comparison.

Two files reorder complete module declarations: `cell_q24_candidate_stage_retained.rs` orders `execution` and `readback`, and `circuit_evaluated_selection_receipt.rs` orders `command_owner_adapter` and `remote`. Each original `#[path]` remains attached to the same module name; these moved declarations have no `#[macro_use]` attribute. The corresponding two literal-sequence differences are solely this declaration reordering. No executable string, byte string, character or numeric literal changed.

The remaining punctuation changes are:

- 133 trailing commas added to parameter, argument, existing multi-element tuple, or tuple-variant lists; 8 to struct fields; 8 to generic argument lists.
- 2 optional trailing call-argument commas removed and 9 optional commas removed after existing block-bodied match arms.
- 15 single-tail-expression blocks added: 10 match-arm bodies and 5 closure bodies. Each encloses the same complete original expression and adds no statement, binding, semicolon, branch, early return or await. The full expressions are retained in `SEMANTIC_REVIEW.json` for review. They comprise original context constructors, error mappings, an authentication call, legacy readiness validation, purpose/domain literals, an evaluator borrow, and the original current-read call.
- One nested generic return type in `circuit_retained_version_state.rs::build_original_selection_reader` is split across lines, with the same `Result<Option<Arc<OriginalCircuitLearningReadOwnerV1<...>>>, Error>` type and optional trailing generic commas. The original `>>` is two closing type brackets, not a shifted expression.

After these explicit declaration and punctuation classifications, there are no unclassified body-token changes. This is a bounded lexical/declaration comparison plus individual source review, not a Rust AST or compiler proof.

## Authority, freshness and failure boundaries

The comparison preserves every executable identifier, literal, operator and statement in its original order. In particular:

| Area | Preserved source boundary |
| --- | --- |
| Candidate and resident Root | Stage/profile refusal, `require_evaluated_retained_stage`, actual root-gate checks before and after work, finite loop bounds, original material/current checks, and existing errors. |
| Original T/E and Selector/C | Same pre-held connections and opaque receipts; current readback and complete-signature comparisons; consuming calls, `.take()`, `.await`, `?`, readback-only and execution-requested branches remain unchanged. |
| Readiness | Separate legacy/evaluated purpose and context bindings, real C observation and original channel handling remain unchanged. |
| Version publication and recovery | Prepared ownership, same original T/E custody, late reader admission, actual Published/freshness gates, and Uncertain/refusal branches remain in their original order. |
| Root-visible evidence | Original complete evidence and final-use bindings are unchanged; formatting supplies no owner, authorization or new signature. |
| Tests and fixtures | All macro calls and all **122 assertion invocations** across the 43 files have the same token bodies and order. All comments and doc comments are equal. No test is removed, ignored, relabelled or weakened by this transition. |

The explicit `recovered_peer` test-only re-export that fixed the earlier E0425 is not among these 43 changes. It remains part of the 9c4 preimage. This formatting review neither reclassifies that earlier failed attempt nor counts it as a new test execution.

## Handoff and limits

No H operation, Cargo invocation, formatter, Rust test, source gate, source mutation or ref update was performed by this audit. The original V5 fix/fmt success must continue to be cited through its actual native records. Source-sensitive CALLERS/protected-row/QA strings must now be derived from these exact formatted bytes by the designated non-Rust writer. After that integration, the agreed separately recorded original format step and final exact-source qualification remain required.

The helper scripts only read the retained packet and write independent review artifacts. They do not import or run repository code. The compressed analysis companion retains the complete first-pass and structural comparison records, the analysis helpers, and a reconstructed unified diff. That reconstructed diff is labelled separately from the original native 189,258-byte patch.

## Exact before/after Rust objects

Every row below refers to `codex-rs/hepta-agentd/src/`.

| File | Exact before Git blob | Actual formatted Git blob |
| --- | --- | --- |
| `authority_host_learning_resident_stages.rs` | `9128be835dbb0ca724591499ab0a7a34c9a9f3f2` | `f171d6eda0b8673f3c39566368025ad18dbaf19c` |
| `cell_q24_candidate_stage_inputs.rs` | `dd33ee5fae36cac16f6543d4becb80b695b04da5` | `4d48a46967db39d0258d00c9ff0876a3dca53de2` |
| `cell_q24_candidate_stage_retained.rs` | `6cb5e7fc0f274cbdbae9fe57140b48cca4983677` | `923a3d5b8e0ecfba7bd686a01566e59ea6985d69` |
| `cell_q24_candidate_stage_retained_execute.rs` | `0e24b809a531f741ccecc13b8262e184aec1dfb1` | `dda6557805b08b4615bf2a5bb1508c4656686a9e` |
| `cell_q24_candidate_stage_retained_readback.rs` | `3caae9286796ae6d40579812d6c725904e1926ab` | `ac638b392a3c4b78525affb108dbb2436622898b` |
| `cell_q24_no_update_stage_state.rs` | `cd5dbe4c394c7416c0b81ad9065af82ae08da4da` | `d38c792970cd3f8da006e6474c5726300d5e5f5b` |
| `circuit_evaluated_command_roundtrip_tests.rs` | `d0e72874ecc92302fbdf6262be1e0e2a67f148e5` | `8bf7a1d76a291e3518a27a97b4c647af9bf7887c` |
| `circuit_evaluated_completion_readiness_support_tests.rs` | `152419a1b3d99d5a9f9ac1f7b97f3895dd3a22e8` | `03a40cad03821f7eb80552af29c0d720c6b44446` |
| `circuit_evaluated_next_use_command.rs` | `6dac672a00b5116148f9c931b7f7c9fbb81d293f` | `c685d27d598c9e966c0e4497a8307436c66cbb5f` |
| `circuit_evaluated_next_use_command_service.rs` | `d44ab21c8e2d8cf46225214f6a16e116e2dc7939` | `2893d2cc97faef0f3352406b89f7ec190b8e629d` |
| `circuit_evaluated_next_use_receipt.rs` | `fdf5e0b5e93c16ed312aa09e8d249e13b0b22520` | `8c034c0c4ca948983fb4471e485fa7bf55fe4172` |
| `circuit_evaluated_next_use_remote.rs` | `4c5c98eca6126fe808ba6f01365525deeb14d816` | `fed5077853544aad6a725f2967ba782715555a1f` |
| `circuit_evaluated_next_use_remote_tests.rs` | `53bf5fd6d5952390aa447bf28471869a2fe277c0` | `3312383c8b0fcc6053758eabc7ab04c6bab4c4c5` |
| `circuit_evaluated_selection_command.rs` | `c64626eb19dae7b01dd6c77e8d931abe36272e41` | `1898e4b702bcc36e8eac04eebb5e53313b36c7f1` |
| `circuit_evaluated_selection_command_owner_adapter.rs` | `37275599142dce61221b02f1ecbd69139f32a21b` | `c2e4d61d3b676c1d01d4f4efff39dbd45cff09f1` |
| `circuit_evaluated_selection_command_service.rs` | `473ff552c0aece25492f3fe5a0c20c346bd873c3` | `95e6dc6fb97dadbafdcc9e13897221da6ddccb36` |
| `circuit_evaluated_selection_receipt.rs` | `185310b62f39e6fe2b789566145057f634a2bd6a` | `fbc73f0dc7140625e56b6e5b409e9e5469a247ea` |
| `circuit_evaluated_version_final_use_tests.rs` | `df615ba69e4ed6f46eedb47b68ed0ad8c81188b1` | `dff1d4f81b87a258218c83de075de9bce884364d` |
| `circuit_evaluated_version_readiness_support_tests.rs` | `4b358a041e93e541cbe5f31999e0e02023734174` | `662f86dbde5364b95985595f09a7826efb8613de` |
| `circuit_evaluated_version_recovery_support_tests.rs` | `254f838f8030b2560047f26a3961dfacda80386a` | `639f3d799c69a54c4583ee24ce87956ec149a07f` |
| `circuit_evaluated_version_recovery_tests.rs` | `cc7ac948679ab4081c726dc5cc3998f18158ab88` | `c889bb7b6eecedf6c09c97e0cd5f738f2016c23a` |
| `circuit_learning_completion_readiness.rs` | `7bc9d61e1d069b8801d86a4bea0fcbcc2e478beb` | `858941ba17c031bc321b5dce504672491c7e57e7` |
| `circuit_learning_completion_readiness_service.rs` | `aebe684c36cab0a89c13e4f702e18e1b37a27f10` | `3224ca4aa80e8841fc902979c4042d177f647f69` |
| `circuit_learning_read_service.rs` | `74be1cee263699d8e5ab793387290417f9444ad7` | `a2b190518040968eba90448016908974e69d6e40` |
| `circuit_next_use_command.rs` | `516dbb946cc04d920f1671bb2df336e8b49d3b32` | `bc809c51ed025a2908274af83f05c8e752f24074` |
| `circuit_next_use_command_service.rs` | `2f4867ac61d636c323cb8cfd36b0363e5c490b38` | `322ceb9355e6d75d98e4f2219eeef8146dfc2b0e` |
| `circuit_next_use_command_stage_binding.rs` | `9c0dd4ce4576120fd4835ed785c566cdc0dffa69` | `82c1cc4a96e2460ab727562dddea70ea107b46e4` |
| `circuit_next_use_command_wire.rs` | `6aefc9c12e05fe7b052346bcff14f0c05fae664d` | `76502f7c77cdb9c95a3f9e2fa24c5faf4d8e43c9` |
| `circuit_retained_version.rs` | `ae1efbd3b0ffecbd925d67e98b85fee801d4766a` | `e6f841ab40dbfe35f5763b726f391830a76c9b44` |
| `circuit_retained_version_client.rs` | `1f28eee14dc754e17445ddaa11cc092913a804a6` | `5d468f9f38389173749917c11c50b9e3ca75c0fe` |
| `circuit_retained_version_context.rs` | `8e2157b1c5f4ac24fd601e2a7221cdb239ca324c` | `518aaa1a22b3320215813ae0aa2eaf9a7b15cb12` |
| `circuit_retained_version_effect.rs` | `ebc02be6cff65a205b1fa1fc171307a0e8a4c05c` | `915cf4bebe127e2f58b1be21c32b86f13263517d` |
| `circuit_retained_version_host.rs` | `6ac9d7f3ac8412391804d9fdb9a9626663132d33` | `d84937fc81f0a7b41c997c97b29cd06ff9cf03e4` |
| `circuit_retained_version_prepared.rs` | `b62728f79eeda3e17f4067bcaa3227c96da40e42` | `b177e6b4a7a9f63844306d051a80b465be59e355` |
| `circuit_retained_version_service.rs` | `34dc709c958cca632bb21189c78be2bb19c08fb7` | `28a97fd7da6a322e530585d04088f7962617c0c1` |
| `circuit_retained_version_state.rs` | `d5c9cac9bb551376adce36d04b167f6fa978791d` | `a0f3c847a49c3d5a2ae4df704ed1f751b9e287f9` |
| `circuit_selection_command.rs` | `d4f5618ba50678f6dea3d5af731492d8679f9f03` | `14334773c7db9d4d911da4ed7643271c8f6b1d70` |
| `circuit_selection_command_readback.rs` | `3ab1c8a5e7ac5192300c231b1b42d1ac67446871` | `7c1d6207a6ac276b5ec3f9be14850eb354afb461` |
| `circuit_selection_command_service.rs` | `e71678cfe13ed276dd7c5ec7692959e6a448c12f` | `46ea741fc91046f9e6c7407949e630d45ca2ca3b` |
| `circuit_selection_command_stage_binding.rs` | `2cc7863be53975b17f661bc19b3d098c2e43a352` | `65b86566aeb1da774aba5ae8a436482feded5491` |
| `circuit_selection_command_wire.rs` | `70b9f0751f3a66ec3ece56e052ff297ab2ce2708` | `39a8a422113f41de5cd3f4fa15aa384c1570c72a` |
| `lib.rs` | `9f8ebe25c68ce396305ad0b6d3eb8bcc74770000` | `b46baf3d8280114c937799f0430942ec3863afa8` |
| `neuron_cell_evaluation_initial_connection_support_tests.rs` | `cbd907cf662ba797c5f7fd1c963462c1dbf81ab3` | `fed5a4c3c2a7eeb6abe0cf68fbb57c687c214df3` |
