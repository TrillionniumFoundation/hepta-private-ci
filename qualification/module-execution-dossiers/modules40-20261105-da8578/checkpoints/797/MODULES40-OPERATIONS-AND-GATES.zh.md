# 40 模块全部操作映射与原文 gate 附录

固定源码：`797116d61cf422c26274ffef31297dce84a53a80`；tree：`67ce024db1679aa6cd301856ba3a694ea18bc4b6`。本附录完整列出 40 个模块的 371 条操作映射，以及 Map 中保留的 108 条 repositoryControlledGaps 和 140 条 externalEvidenceGates。所有模块的 productionImplementation 仍为 false。

各节先提供操作导航表，再完整保留该模块 operations、repositoryControlledGaps 和 externalEvidenceGates 的原始 JSON 字段与值。当前 Map 用 operation 和 designOperation 标识操作，没有 operationId 字段；这里不另造 ID。模块 owner 直接来自 Map；仅在原操作记录实际具备 ownerEntrypoint、ownerBoundary 或委托 owner 字段时才保留对应记录。

MODULES40-SOURCE-FACTS.json 与固定 Map 原文是完整事实的权威。表内 tests、sourceSemantics 和 sourceBlob 均是源码声明，不是本附录新生成的执行或验收回执。原始 gate 文本保持不变；各候选的执行结果、平台 CI 与合并资格由独立执行总览分别记录，不通过改写历史 gate 或 source pins 转移身份。

## 模块索引与条目数

| 模块 | operations | repositoryControlledGaps | externalEvidenceGates |
| --- | ---: | ---: | ---: |
| [platform.types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/platform.types/IMPLEMENTATION_MAP.json) | 11 | 2 | 3 |
| [platform.wire](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/platform.wire/IMPLEMENTATION_MAP.json) | 5 | 3 | 3 |
| [kernel.authority](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.authority/IMPLEMENTATION_MAP.json) | 9 | 5 | 6 |
| [kernel.operations](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.operations/IMPLEMENTATION_MAP.json) | 10 | 4 | 3 |
| [kernel.evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json) | 6 | 1 | 3 |
| [runtime.supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json) | 12 | 2 | 4 |
| [runtime.fleet](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json) | 3 | 1 | 3 |
| [runtime.agentd](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json) | 10 | 3 | 3 |
| [runtime.codex](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.codex/IMPLEMENTATION_MAP.json) | 4 | 1 | 6 |
| [auth.authbus](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/auth.authbus/IMPLEMENTATION_MAP.json) | 3 | 2 | 3 |
| [secrets.heptabao](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json) | 4 | 3 | 3 |
| [inference.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/inference.control/IMPLEMENTATION_MAP.json) | 4 | 3 | 3 |
| [inference.worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/inference.worker/IMPLEMENTATION_MAP.json) | 3 | 2 | 3 |
| [objective.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/objective.compiler/IMPLEMENTATION_MAP.json) | 10 | 2 | 3 |
| [utility.ndu](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/utility.ndu/IMPLEMENTATION_MAP.json) | 12 | 5 | 5 |
| [neuron.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json) | 9 | 4 | 3 |
| [intuition.policy](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/intuition.policy/IMPLEMENTATION_MAP.json) | 2 | 2 | 3 |
| [prompt.registry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/prompt.registry/IMPLEMENTATION_MAP.json) | 3 | 2 | 3 |
| [prompt.optimizer](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/prompt.optimizer/IMPLEMENTATION_MAP.json) | 2 | 2 | 3 |
| [context.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/context.compiler/IMPLEMENTATION_MAP.json) | 12 | 4 | 3 |
| [intelligence.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/intelligence.control/IMPLEMENTATION_MAP.json) | 35 | 5 | 3 |
| [cognitive.types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.types/IMPLEMENTATION_MAP.json) | 15 | 3 | 3 |
| [cognitive.store](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.store/IMPLEMENTATION_MAP.json) | 12 | 5 | 3 |
| [cognitive.read](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.read/IMPLEMENTATION_MAP.json) | 6 | 11 | 3 |
| [memory.retrieval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json) | 9 | 4 | 5 |
| [memory.federation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/memory.federation/IMPLEMENTATION_MAP.json) | 2 | 2 | 4 |
| [knowledge.graph](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json) | 5 | 3 | 3 |
| [compact.engine](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/compact.engine/IMPLEMENTATION_MAP.json) | 3 | 2 | 3 |
| [learning.ledger](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.ledger/IMPLEMENTATION_MAP.json) | 18 | 6 | 6 |
| [learning.operator](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.operator/IMPLEMENTATION_MAP.json) | 20 | 3 | 3 |
| [learning.eval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.eval/IMPLEMENTATION_MAP.json) | 12 | 1 | 4 |
| [learning.artifacts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json) | 25 | 1 | 4 |
| [learning.plasticity](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json) | 27 | 3 | 5 |
| [automation.taskflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json) | 4 | 0 | 4 |
| [channel.matrix](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/channel.matrix/IMPLEMENTATION_MAP.json) | 3 | 1 | 3 |
| [browser.servo](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/browser.servo/IMPLEMENTATION_MAP.json) | 3 | 0 | 3 |
| [ui.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/ui.control/IMPLEMENTATION_MAP.json) | 3 | 0 | 3 |
| [ui.native](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/ui.native/IMPLEMENTATION_MAP.json) | 4 | 0 | 3 |
| [control.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/control.runtime/IMPLEMENTATION_MAP.json) | 6 | 2 | 3 |
| [control.engineering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/control.engineering/IMPLEMENTATION_MAP.json) | 25 | 3 | 3 |

合计：371 条操作映射；108 条仓库内 gate；140 条外部证据 gate。

## 1. platform.types

固定来源：[platform.types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/platform.types/IMPLEMENTATION_MAP.json)。Map Git blob：`d6f93d6c37caf0fbd8e25841d6ce7c4dd7828eef`。

owner：` kernel-contracts `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（11 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` bounded_values ` | ` bounded_values ` | ` BoundedText ` | ` codex-rs/hepta-types/src/bounded.rs ` | ` owner_native ` |
| ` validate_id ` | ` validate_id ` | ` validate_id ` | ` codex-rs/hepta-types/src/identity.rs ` | ` owner_native ` |
| ` raw_authority_ingress ` | ` raw_authority_ingress ` | ` AuthorityPosture::try_from_wire_bytes ` | ` codex-rs/hepta-types/src/identity.rs ` | ` owner_native ` |
| ` canonical_digest_v1 ` | ` canonical_digest_v1 ` | ` canonical_digest_v1 ` | ` codex-rs/hepta-types/src/canonical_digest.rs ` | ` owner_native ` |
| ` canonical_validate_v1 ` | ` canonical_validate_v1 ` | ` canonical_validate_v1 ` | ` codex-rs/hepta-types/src/canonical_digest.rs ` | ` owner_native ` |
| ` fixed_q32 ` | ` fixed_q32 ` | ` FixedQ32 ` | ` codex-rs/hepta-types/src/fixed.rs ` | ` owner_native ` |
| ` contract_registry_v1 ` | ` contract_registry_v1 ` | ` ContractRegistryV1 ` | ` codex-rs/hepta-types/src/registry.rs ` | ` owner_native ` |
| ` numeric_profile_definition_v1 ` | ` numeric_profile_definition_v1 ` | ` NumericProfileDefinitionV1 ` | ` codex-rs/hepta-types/src/numeric_profile.rs ` | ` owner_native ` |
| ` rescale_signal ` | ` rescale_signal ` | ` rescale_signal ` | ` codex-rs/hepta-types/src/numeric_conversion.rs ` | ` owner_native ` |
| ` rescale_signal_registered ` | ` rescale_signal_registered ` | ` rescale_signal_registered ` | ` codex-rs/hepta-types/src/numeric_conversion.rs ` | ` owner_native ` |
| ` generated_bindings_v1 ` | ` generated_bindings_v1 ` | ` generate_bindings.py ` | ` codex-rs/hepta-types/bindings/generate_bindings.py ` | ` owner_native ` |

### operations 原文（11 项）

```json
[
  {
    "operation": "bounded_values",
    "nativeSymbol": "BoundedText",
    "sourcePath": "codex-rs/hepta-types/src/bounded.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/bounded_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "bounded_values",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "BoundedText",
      "BoundedBytes"
    ],
    "sourceBlob": "5b8afd7be362d5383283d03b785b57b6128fa28d"
  },
  {
    "operation": "validate_id",
    "nativeSymbol": "validate_id",
    "sourcePath": "codex-rs/hepta-types/src/identity.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/identity_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "validate_id",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "StableId",
      "IdProfileV1",
      "IdNamespaceV1",
      "validate_id"
    ],
    "sourceBlob": "d57e5c9d0ebe8dced59c096a3586830d52e3df4f"
  },
  {
    "operation": "raw_authority_ingress",
    "nativeSymbol": "AuthorityPosture::try_from_wire_bytes",
    "sourcePath": "codex-rs/hepta-types/src/identity.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/identity_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "raw_authority_ingress",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "AuthorityFlagsV1",
      "AuthorityPosture",
      "NonAuthorizingPosture"
    ],
    "sourceBlob": "d57e5c9d0ebe8dced59c096a3586830d52e3df4f"
  },
  {
    "operation": "canonical_digest_v1",
    "nativeSymbol": "canonical_digest_v1",
    "sourcePath": "codex-rs/hepta-types/src/canonical_digest.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/canonical_digest_tests.rs",
      "codex-rs/hepta-types/conformance/verify_vectors.py",
      "codex-rs/hepta-types/conformance/verify_vectors.ts"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_digest_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "canonical_encode_v1",
      "canonical_digest_v1"
    ],
    "sourceBlob": "331d16b144b559d170c5e2919b6c042b45289f61"
  },
  {
    "operation": "canonical_validate_v1",
    "nativeSymbol": "canonical_validate_v1",
    "sourcePath": "codex-rs/hepta-types/src/canonical_digest.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/canonical_digest_tests.rs",
      "codex-rs/hepta-types/conformance/verify_rejections.py",
      "codex-rs/hepta-types/conformance/verify_rejections.mjs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_validate_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "canonical_validate_v1"
    ],
    "sourceBlob": "331d16b144b559d170c5e2919b6c042b45289f61"
  },
  {
    "operation": "fixed_q32",
    "nativeSymbol": "FixedQ32",
    "sourcePath": "codex-rs/hepta-types/src/fixed.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/fixed_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "fixed_q32",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "FixedQ32",
      "ProbabilityQ32",
      "FIXED_Q32_ARITHMETIC_PROFILE_V1"
    ],
    "sourceBlob": "3c2674dce405fd20f254f5f1816654aae99d7c13"
  },
  {
    "operation": "contract_registry_v1",
    "nativeSymbol": "ContractRegistryV1",
    "sourcePath": "codex-rs/hepta-types/src/registry.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/registry_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "contract_registry_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "ContractRegistryV1",
      "RegistryDefinitionV1",
      "RegistryKindV1"
    ],
    "sourceBlob": "b9af7af31f2eb6dda29f78701ccc608563920f87"
  },
  {
    "operation": "numeric_profile_definition_v1",
    "nativeSymbol": "NumericProfileDefinitionV1",
    "sourcePath": "codex-rs/hepta-types/src/numeric_profile.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/numeric_profile_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "numeric_profile_definition_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "NumericProfileV1",
      "NumericProfileDefinitionV1"
    ],
    "sourceBlob": "383ef3eb7a62873b74faa50f097f7aa11130b18a"
  },
  {
    "operation": "rescale_signal",
    "nativeSymbol": "rescale_signal",
    "sourcePath": "codex-rs/hepta-types/src/numeric_conversion.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/numeric_conversion_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "rescale_signal",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "NumericSignalV1",
      "NumericConversionReceiptV1",
      "rescale_signal"
    ],
    "sourceBlob": "03f4df15838b6c71fc0017fdb75cb179fb1b70a7"
  },
  {
    "operation": "rescale_signal_registered",
    "nativeSymbol": "rescale_signal_registered",
    "sourcePath": "codex-rs/hepta-types/src/numeric_conversion.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/src/numeric_conversion_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "rescale_signal_registered",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "rescale_signal_registered"
    ],
    "sourceBlob": "03f4df15838b6c71fc0017fdb75cb179fb1b70a7"
  },
  {
    "operation": "generated_bindings_v1",
    "nativeSymbol": "generate_bindings.py",
    "sourcePath": "codex-rs/hepta-types/bindings/generate_bindings.py",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-types/bindings/verify_generated.py",
      "codex-rs/hepta-types/bindings/verify_generated.mjs"
    ],
    "sourcePathExists": true,
    "designOperation": "generated_bindings_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "publicSymbols": [
      "generated/python/hepta_platform_types_v1.py",
      "generated/javascript/hepta_platform_types_v1.mjs",
      "generated/typescript/hepta_platform_types_v1.d.ts"
    ],
    "sourceBlob": "f8f2d0ceb0d84d79cbf0121a727259b140f7b2f2"
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Run exact-head and deterministic synthetic-merge Lane A qualification for this exact candidate.",
  "Implement native source for RandomStreamManifestV1, ExternalSystemManifestV1 and SensorCalibrationManifestV1 before claiming full owned-target-protocol source completion."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "named authenticated product composition and full consumer compile matrix",
  "independent semantic review and target-host/product qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 2. platform.wire

固定来源：[platform.wire](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/platform.wire/IMPLEMENTATION_MAP.json)。Map Git blob：`344bfc407d6d23065b51f00fa557280d9d604f74`。

owner：` kernel-contracts `；productCallerState：` source_composed_read_only_and_registered_port_adapters `；productionWriterState：` not_established `。

### 操作导航（5 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` wire_v1 ` | ` wire_v1 ` | ` WireEnvelope ` | ` codex-rs/hepta-wire/src/envelope.rs ` | ` owner_native ` |
| ` wire_v2 ` | ` wire_v2 ` | ` WireEnvelopeV2 ` | ` codex-rs/hepta-wire/src/envelope_v2.rs ` | ` owner_native ` |
| ` negotiate ` | ` negotiate ` | ` negotiate ` | ` codex-rs/hepta-wire/src/version.rs ` | ` owner_native ` |
| ` schema_admission ` | ` schema_admission ` | ` SchemaRegistry ` | ` codex-rs/hepta-wire/src/schema.rs ` | ` owner_native ` |
| ` stream_decode ` | ` stream_decode ` | ` StreamingDecoder ` | ` codex-rs/hepta-wire/src/stream.rs ` | ` owner_native ` |

### operations 原文（5 项）

```json
[
  {
    "operation": "wire_v1",
    "nativeSymbol": "WireEnvelope",
    "sourcePath": "codex-rs/hepta-wire/src/envelope.rs",
    "state": "source_implemented_backward_compatible",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-wire/src/envelope_tests.rs",
      "codex-rs/hepta-wire/src/boundary_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "wire_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "00e767ccc12e1703296f8f73ef1f53da6996922a"
  },
  {
    "operation": "wire_v2",
    "nativeSymbol": "WireEnvelopeV2",
    "sourcePath": "codex-rs/hepta-wire/src/envelope_v2.rs",
    "state": "source_implemented_source_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-wire/src/envelope_v2_tests.rs",
      "codex-rs/hepta-native-gateway/src/lib.rs",
      "codex-rs/hepta-context-compiler/src/wire_tests.rs",
      "codex-rs/hepta-codex-adapter/src/wire_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "wire_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      "codex-rs/hepta-runtime/src/lib.rs",
      "codex-rs/hepta-native-gateway/src/lib.rs",
      "codex-rs/hepta-context-compiler/src/wire.rs",
      "codex-rs/hepta-codex-adapter/src/wire.rs"
    ],
    "sourceBlob": "0195d24fca437fd458fb880e80176e4d566baced"
  },
  {
    "operation": "negotiate",
    "nativeSymbol": "negotiate",
    "sourcePath": "codex-rs/hepta-wire/src/version.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-wire/src/version_tests.rs",
      "codex-rs/hepta-shadow-qualification/tests/cross_runtime_wire_session.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "negotiate",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d4e9388500f674e0e9b33cf37161549379223dda"
  },
  {
    "operation": "schema_admission",
    "nativeSymbol": "SchemaRegistry",
    "sourcePath": "codex-rs/hepta-wire/src/schema.rs",
    "state": "source_implemented_framework",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-wire/src/schema_tests.rs",
      "codex-rs/hepta-shadow-qualification/tests/cross_runtime_wire_session.rs",
      "codex-rs/hepta-context-compiler/src/wire_tests.rs",
      "codex-rs/hepta-codex-adapter/src/wire_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "schema_admission",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "dc06ad7a692d87404ee8d3d2bcb76e9dea984717"
  },
  {
    "operation": "stream_decode",
    "nativeSymbol": "StreamingDecoder",
    "sourcePath": "codex-rs/hepta-wire/src/stream.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-wire/src/stream_tests.rs",
      "codex-rs/hepta-wire/src/property_tests.rs",
      "codex-rs/hepta-wire/fuzz/fuzz_targets/decode_frames.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "stream_decode",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "6e83762934b13bf6b6e2c8d1458633d0512fa543"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Run exact-head and deterministic synthetic-merge tests for the versioned implementation and registered product source callers.",
  "Bind HPTN negotiation and encoded HPTA frames to the selected authenticated production transport/session.",
  "Register and qualify each additional product-domain schema codec before admitting it."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic and security review",
  "target-host product execution and authenticated transport qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 3. kernel.authority

固定来源：[kernel.authority](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.authority/IMPLEMENTATION_MAP.json)。Map Git blob：`ae0dd8cdc9ed61b2e2ce58957b6a6122e8bdb1b1`。

owner：` security-authority `；productCallerState：` source_composed_runtime_fleet_registered_bao_host_and_agentd_browser_not_product_activated `；productionWriterState：` authority_owner_source_implemented_not_activated `。

### 操作导航（9 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` finaluseauthority ` | ` claim_deliver_dispatch_external_trust_and_epoch_issuer_rotation ` | ` FinalUseAuthority ` | ` codex-rs/hepta-contracts/src/final_use.rs ` | ` owner_native ` |
| ` store ` | ` store ` | ` Store ` | ` codex-rs/hepta-contracts/src/final_use_store.rs ` | ` owner_native ` |
| ` authority_lease_registry ` | ` put_verify_revoke_prune_with_retired_revision_lineage_epoch_authority_lease ` | ` AuthorityLeaseRegistry / AuthorityLeaseVerifier ` | ` codex-rs/hepta-contracts/src/authority_lease.rs ` | ` owner_native ` |
| ` final_use_approval_verifier ` | ` independent_final_use_approval_with_epoch_key_rotation ` | ` FinalUseApprovalVerifier ` | ` codex-rs/hepta-contracts/src/final_use_control.rs ` | ` owner_native ` |
| ` final_use_revocation_feed_verifier ` | ` authenticated_fresh_revocation_ingestion_with_epoch_key_rotation ` | ` FinalUseRevocationFeedVerifier ` | ` codex-rs/hepta-contracts/src/final_use_control.rs ` | ` owner_native ` |
| ` authority_external_trust ` | ` trusted_time_and_external_anti_rollback_frontier ` | ` AuthorityClock / AuthorityFrontierStore ` | ` codex-rs/hepta-contracts/src/authority_trust.rs ` | ` owner_native_interface ` |
| ` final_use_revocation_convergence ` | ` verify_enrolled_node_revocation_convergence ` | ` FinalUseRevocationConvergenceVerifier ` | ` codex-rs/hepta-contracts/src/final_use_control.rs ` | ` owner_native_verifier ` |
| ` verified_use_witness_v1 ` | ` serialize_consumer_entry_or_dispatch_linearization_evidence ` | ` VerifiedUseTokenWitnessV1 ` | ` codex-rs/hepta-contracts/src/verified_use_witness.rs ` | ` owner_native_evidence ` |
| ` verified_use_token_witness_v1 ` | ` decision_and_audit_projection ` | ` VerifiedUseTokenWitnessV1 ` | ` codex-rs/hepta-contracts/src/verified_use_witness.rs ` | ` owner_native ` |

### operations 原文（9 项）

```json
[
  {
    "operation": "finaluseauthority",
    "nativeSymbol": "FinalUseAuthority",
    "sourcePath": "codex-rs/hepta-contracts/src/final_use.rs",
    "state": "source_implemented_registered_host_not_product_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_tests.rs",
      "codex-rs/hepta-contracts/tests/final_use_linearization.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "claim_deliver_dispatch_external_trust_and_epoch_issuer_rotation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "e6e40ac106c6d1c07f8bfc17da1a0c5c763224cd"
  },
  {
    "operation": "store",
    "nativeSymbol": "Store",
    "sourcePath": "codex-rs/hepta-contracts/src/final_use_store.rs",
    "state": "source_implemented_not_product_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "store",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d014fce0c1396b094d4497c58ef905c53e80669f"
  },
  {
    "operation": "authority_lease_registry",
    "nativeSymbol": "AuthorityLeaseRegistry / AuthorityLeaseVerifier",
    "sourcePath": "codex-rs/hepta-contracts/src/authority_lease.rs",
    "state": "source_implemented_least_authority_handles_retired_revision_lineage_not_product_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/authority_lease.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "put_verify_revoke_prune_with_retired_revision_lineage_epoch_authority_lease",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "924e4552472038934f665f6acf7a95438294893f"
  },
  {
    "operation": "final_use_approval_verifier",
    "nativeSymbol": "FinalUseApprovalVerifier",
    "sourcePath": "codex-rs/hepta-contracts/src/final_use_control.rs",
    "state": "source_implemented_registered_host_not_product_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_control.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "independent_final_use_approval_with_epoch_key_rotation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "41b1d83586fdab55b143471dab85679c3efebbe8"
  },
  {
    "operation": "final_use_revocation_feed_verifier",
    "nativeSymbol": "FinalUseRevocationFeedVerifier",
    "sourcePath": "codex-rs/hepta-contracts/src/final_use_control.rs",
    "state": "source_implemented_registered_host_not_product_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_control.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "authenticated_fresh_revocation_ingestion_with_epoch_key_rotation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "41b1d83586fdab55b143471dab85679c3efebbe8"
  },
  {
    "operation": "authority_external_trust",
    "nativeSymbol": "AuthorityClock / AuthorityFrontierStore",
    "sourcePath": "codex-rs/hepta-contracts/src/authority_trust.rs",
    "state": "source_interface_implemented_external_backend_not_selected",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/authority_lease.rs",
      "codex-rs/hepta-contracts/src/final_use_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "trusted_time_and_external_anti_rollback_frontier",
    "mappingClass": "owner_native_interface",
    "delegatedCallees": [],
    "sourceBlob": "043ffd75a20c42935959a98d37f40e3d7229c407"
  },
  {
    "operation": "final_use_revocation_convergence",
    "nativeSymbol": "FinalUseRevocationConvergenceVerifier",
    "sourcePath": "codex-rs/hepta-contracts/src/final_use_control.rs",
    "state": "source_implemented_transport_external",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_control.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "verify_enrolled_node_revocation_convergence",
    "mappingClass": "owner_native_verifier",
    "delegatedCallees": [],
    "sourceBlob": "41b1d83586fdab55b143471dab85679c3efebbe8"
  },
  {
    "operation": "verified_use_witness_v1",
    "nativeSymbol": "VerifiedUseTokenWitnessV1",
    "sourcePath": "codex-rs/hepta-contracts/src/verified_use_witness.rs",
    "state": "source_implemented_non_authorizing_evidence_not_product_consumed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/final_use_tests.rs",
      "codex-rs/hepta-contracts/src/authority_lease.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "serialize_consumer_entry_or_dispatch_linearization_evidence",
    "mappingClass": "owner_native_evidence",
    "delegatedCallees": [],
    "sourceBlob": "bb5847d7f1beabab6e179f0beba349e3278efbf3"
  },
  {
    "operation": "verified_use_token_witness_v1",
    "nativeSymbol": "VerifiedUseTokenWitnessV1",
    "sourcePath": "codex-rs/hepta-contracts/src/verified_use_witness.rs",
    "state": "source_implemented_evidence_projection_not_authorization",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-contracts/src/verified_use_witness.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "decision_and_audit_projection",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "bb5847d7f1beabab6e179f0beba349e3278efbf3"
  }
]
```

### repositoryControlledGaps 原文（5 项）

```json
[
  "Select and qualify a named product-process caller for the registered Bao final-use host before activation.",
  "Retain current exact-head and deterministic synthetic-merge execution receipts after the hardened authority changes.",
  "Compose remaining target-only ModulePorts only when their real owner exposes one canonical authority reference/revision; do not create ad-hoc double-authority wrappers.",
  "Obtain exact-head and deterministic synthetic-merge execution receipts for the current-main closure candidate.",
  "Compose each remaining target kernel.authority ModulePort only at its real owner boundary; runtime.fleet is now source-composed, while the remaining target-only ports are enumerated in TRACEABILITY.md."
]
```

### externalEvidenceGates 原文（6 项）

```json
[
  "deployed fleet revocation wire fanout and measured convergence/freshness latency qualification; repository admission/convergence semantics are implemented in runtime.fleet",
  "protected production AuthorityFrontierStore backend qualification",
  "attested or otherwise independently protected AuthorityClock qualification",
  "HSM/KMS key custody, staged rotation and compromise-response ceremony",
  "independent semantic review",
  "operator acceptance, canary, promotion and release"
]
```

## 4. kernel.operations

固定来源：[kernel.operations](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.operations/IMPLEMENTATION_MAP.json)。Map Git blob：`10b956cadc270ec9acfe4a98ffa6aa0de2fda2e6`。

owner：` durability-kernel `；productCallerState：` agentd_runtime_lifecycle_source_composed_external_authority_activation_pending `；productionWriterState：` durable_cognitive_store_owner_implemented_not_activated `。

### 操作导航（10 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` operation_intent_v1 ` | ` prepare_intent ` | ` OperationIntentV1 ` | ` codex-rs/hepta-operations/src/model.rs ` | ` owner_native ` |
| ` prepare_operation ` | ` prepare_intent ` | ` ProductionDurableWriter::prepare_operation ` | ` codex-rs/hepta-memory/src/production_writer.rs ` | ` delegated_owner_native ` |
| ` claim_outbox ` | ` claim_outbox ` | ` operation_claims::claim ` | ` codex-rs/hepta-memory/src/operation_claims.rs ` | ` delegated_owner_native ` |
| ` authorized_dispatch ` | ` authorized_dispatch ` | ` ProductionFinalUseOutboxDispatcher::dispatch ` | ` codex-rs/hepta-memory/src/production_writer.rs ` | ` delegated_owner_native ` |
| ` observe_cognitive_terminal ` | ` observe_terminal ` | ` CognitiveSourceOutboxTarget::observe_terminal ` | ` codex-rs/hepta-memory/src/production_cognitive_source_target.rs ` | ` delegated_owner_native ` |
| ` agentd_final_use_host ` | ` product_composition ` | ` AgentdProductionWriterHost ` | ` codex-rs/hepta-agentd/src/production_writer_host.rs ` | ` delegated_owner_native ` |
| ` agentd_runtime_composition ` | ` product_composition ` | ` runtime::run ` | ` codex-rs/hepta-agentd/src/runtime.rs ` | ` delegated_owner_native ` |
| ` automation_operation_consumer ` | ` destination_apply ` | ` AutomationStore::dispatch_authorized_effect ` | ` codex-rs/hepta-automation/src/authorized_effect.rs ` | ` delegated_owner_native ` |
| ` reference_operationledger ` | ` reference_operationledger ` | ` OperationLedger ` | ` codex-rs/hepta-operations/src/ledger.rs ` | ` owner_native ` |
| ` reference_outbox ` | ` reference_outbox ` | ` Outbox ` | ` codex-rs/hepta-operations/src/outbox.rs ` | ` owner_native ` |

### operations 原文（10 项）

```json
[
  {
    "operation": "operation_intent_v1",
    "nativeSymbol": "OperationIntentV1",
    "sourcePath": "codex-rs/hepta-operations/src/model.rs",
    "state": "canonical_contract_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-operations/src/model.rs",
      "codex-rs/hepta-operations/src/ledger_tests.rs",
      "codex-rs/hepta-operations/src/outbox_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "prepare_intent",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d952060c81eca0d64d7091ebca928c8740c00ed7"
  },
  {
    "operation": "prepare_operation",
    "nativeSymbol": "ProductionDurableWriter::prepare_operation",
    "sourcePath": "codex-rs/hepta-memory/src/production_writer.rs",
    "state": "durable_source_implemented_execution_pending",
    "authority": "durability-kernel",
    "tests": [
      "codex-rs/hepta-memory/src/local_lease_outbox_tests.rs",
      "codex-rs/hepta-memory/src/production_writer.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "prepare_intent",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-cognitive-store",
        "module": "cognitive.store",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "ba5e42081ea35c0d43c5e1d77be43f2f6a1d3966"
  },
  {
    "operation": "claim_outbox",
    "nativeSymbol": "operation_claims::claim",
    "sourcePath": "codex-rs/hepta-memory/src/operation_claims.rs",
    "state": "durable_claim_lease_implemented_execution_pending",
    "authority": "generation_fence_attempt_lease_bound",
    "tests": [
      "codex-rs/hepta-memory/src/production_writer.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "claim_outbox",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-cognitive-store",
        "module": "cognitive.store",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "fd7a70f27849fdbc15a8cd6c1e7fc481657bd8cb"
  },
  {
    "operation": "authorized_dispatch",
    "nativeSymbol": "ProductionFinalUseOutboxDispatcher::dispatch",
    "sourcePath": "codex-rs/hepta-memory/src/production_writer.rs",
    "state": "final_use_boundary_source_implemented_execution_pending",
    "authority": "kernel.authority_final_use_consumed",
    "tests": [
      "codex-rs/hepta-memory/src/production_writer.rs",
      "codex-rs/hepta-memory/src/production_cognitive_source_target_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "authorized_dispatch",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-contracts",
        "module": "kernel.authority",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-cognitive-store",
        "module": "cognitive.store",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "ba5e42081ea35c0d43c5e1d77be43f2f6a1d3966"
  },
  {
    "operation": "observe_cognitive_terminal",
    "nativeSymbol": "CognitiveSourceOutboxTarget::observe_terminal",
    "sourcePath": "codex-rs/hepta-memory/src/production_cognitive_source_target.rs",
    "state": "destination_cas_and_observer_source_implemented_execution_pending",
    "authority": "destination_owned_terminal_evidence",
    "tests": [
      "codex-rs/hepta-memory/src/production_cognitive_source_target_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "observe_terminal",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-cognitive-store",
        "module": "cognitive.store",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "7df8ed4ccd4137672690adc17cc52027644afe2d"
  },
  {
    "operation": "agentd_final_use_host",
    "nativeSymbol": "AgentdProductionWriterHost",
    "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "state": "named_final_use_host_source_implemented_activation_pending",
    "authority": "externally_supplied_authority_and_grant_provider",
    "tests": [
      "codex-rs/hepta-agentd/examples/h4_persistent_writer.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "product_composition",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-agentd",
        "module": "runtime.agentd",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "39d127250b8e825292c25f8c34ec360d5d94ff60"
  },
  {
    "operation": "agentd_runtime_composition",
    "nativeSymbol": "runtime::run",
    "sourcePath": "codex-rs/hepta-agentd/src/runtime.rs",
    "state": "explicit_daemon_lifecycle_source_implemented_activation_pending",
    "authority": "externally_supplied_authority_and_grant_provider",
    "tests": [
      "codex-rs/hepta-agentd/src/runtime_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "product_composition",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-agentd",
        "module": "runtime.agentd",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "ca57d28162bd5788ef6ad6a5234e671a930175a9"
  },
  {
    "operation": "automation_operation_consumer",
    "nativeSymbol": "AutomationStore::dispatch_authorized_effect",
    "sourcePath": "codex-rs/hepta-automation/src/authorized_effect.rs",
    "state": "second_operation_intent_consumer_source_implemented",
    "authority": "kernel.authority_final_use_consumed",
    "tests": [
      "codex-rs/hepta-automation/tests/authorized_effect.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "destination_apply",
    "mappingClass": "delegated_owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-automation",
        "module": "automation.taskflow",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "21db22ee30ffd50463b1721ef3fd8046ef5b3950"
  },
  {
    "operation": "reference_operationledger",
    "nativeSymbol": "OperationLedger",
    "sourcePath": "codex-rs/hepta-operations/src/ledger.rs",
    "state": "reference_oracle_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-operations/src/ledger_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "reference_operationledger",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "e6ed053a86608f30e63c703a6ed6e3cdb049abfd"
  },
  {
    "operation": "reference_outbox",
    "nativeSymbol": "Outbox",
    "sourcePath": "codex-rs/hepta-operations/src/outbox.rs",
    "state": "reference_oracle_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-operations/src/outbox_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "reference_outbox",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1f172748e56e2fdffa403b485ec0145af66a99f8"
  }
]
```

### repositoryControlledGaps 原文（4 项）

```json
[
  "Run current exact-head and deterministic synthetic-merge qualification for this current-main convergence candidate and close every resulting finding.",
  "Add destination-owned dedupe/apply/terminal observation before activating each remaining registered effect destination.",
  "Design and qualify bounded segment/checkpoint compaction for append-only lease/event/outbox history before long-lived capacity qualification.",
  "Named source and product adapters remain present; current candidate requalification is required because mapped source/build inputs changed after the retained historical observation. Historical production proof is not rebound by navigation migration."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "enrolled production authority/grant source and target-host crash/power-loss/storage qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 5. kernel.evidence

固定来源：[kernel.evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json)。Map Git blob：`b114bd30a0a8f2906604b089dcd802028dcdf55a`。

owner：` qualification-plane `；productCallerState：` agentd_composed_config_gated `；productionWriterState：` agentd_authenticated_writer_established_config_gated `。

### 操作导航（6 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` append_receipt ` | ` append_receipt ` | ` QualificationEvidenceStore::append_receipt ` | ` codex-rs/hepta-evidence/src/qualification.rs ` | ` owner_native ` |
| ` query_claim ` | ` query_claim ` | ` QualificationEvidenceStore::query_claim ` | ` codex-rs/hepta-evidence/src/qualification.rs ` | ` owner_native ` |
| ` verify_chain ` | ` verify_chain ` | ` QualificationEvidenceStore::verify_chain ` | ` codex-rs/hepta-evidence/src/qualification.rs ` | ` owner_native ` |
| ` recovery_snapshot ` | ` recovery_snapshot ` | ` HeptaEvidenceStore::recovery_snapshot ` | ` codex-rs/hepta-evidence/src/recovery_frontier.rs ` | ` owner_native ` |
| ` append_provider_effect_intent ` | ` append_provider_effect_intent ` | ` append_provider_effect_intent ` | ` codex-rs/hepta-evidence/src/provider_effect_store.rs ` | ` owner_native ` |
| ` reconcile_provider_effect_lookup ` | ` reconcile_provider_effect_lookup ` | ` reconcile_provider_effect_lookup ` | ` codex-rs/hepta-evidence/src/provider_effect_store.rs ` | ` owner_native ` |

### operations 原文（6 项）

```json
[
  {
    "operation": "append_receipt",
    "nativeSymbol": "QualificationEvidenceStore::append_receipt",
    "sourcePath": "codex-rs/hepta-evidence/src/qualification.rs",
    "state": "source_implemented_product_composed",
    "authority": "authenticated_evidence_append_only",
    "tests": [
      "codex-rs/hepta-evidence/src/qualification_tests.rs",
      "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_receipt",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "4266cd8e4b3639108f1dfe592eb47c05494c3c46"
  },
  {
    "operation": "query_claim",
    "nativeSymbol": "QualificationEvidenceStore::query_claim",
    "sourcePath": "codex-rs/hepta-evidence/src/qualification.rs",
    "state": "source_implemented_product_composed",
    "authority": "read_only",
    "tests": [
      "codex-rs/hepta-evidence/src/qualification_tests.rs",
      "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "query_claim",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "4266cd8e4b3639108f1dfe592eb47c05494c3c46"
  },
  {
    "operation": "verify_chain",
    "nativeSymbol": "QualificationEvidenceStore::verify_chain",
    "sourcePath": "codex-rs/hepta-evidence/src/qualification.rs",
    "state": "source_implemented_product_composed",
    "authority": "read_only_verification",
    "tests": [
      "codex-rs/hepta-evidence/src/qualification_tests.rs",
      "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "verify_chain",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "4266cd8e4b3639108f1dfe592eb47c05494c3c46"
  },
  {
    "operation": "recovery_snapshot",
    "nativeSymbol": "HeptaEvidenceStore::recovery_snapshot",
    "sourcePath": "codex-rs/hepta-evidence/src/recovery_frontier.rs",
    "state": "source_implemented_product_consumed",
    "authority": "read_only_recovery_snapshot",
    "tests": [
      "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "recovery_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "sourcePath": "codex-rs/hepta-agentd/src/evidence_frontier.rs",
        "nativeSymbol": "verify_evidence_recovery_frontier",
        "role": "product_restore_verifier",
        "path": "codex-rs/hepta-agentd/src/evidence_frontier.rs"
      }
    ],
    "sourceBlob": "aff8cdd21913699d6081949b4fa912e4d8aae86e"
  },
  {
    "operation": "append_provider_effect_intent",
    "nativeSymbol": "append_provider_effect_intent",
    "sourcePath": "codex-rs/hepta-evidence/src/provider_effect_store.rs",
    "state": "source_implemented_qualification_only",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-evidence/src/provider_effect_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_provider_effect_intent",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "45b1794ee80a8e4b1067b7b8fd86cb2f2d08c241"
  },
  {
    "operation": "reconcile_provider_effect_lookup",
    "nativeSymbol": "reconcile_provider_effect_lookup",
    "sourcePath": "codex-rs/hepta-evidence/src/provider_effect_store.rs",
    "state": "source_implemented_qualification_only",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-evidence/src/provider_effect_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "reconcile_provider_effect_lookup",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "45b1794ee80a8e4b1067b7b8fd86cb2f2d08c241"
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "Named source and product adapters remain present; current candidate requalification is required because mapped source/build inputs changed after the retained historical observation. Historical production proof is not rebound by navigation migration."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent exact-candidate acceptance",
  "external monotonic CAS/latest-frontier backend and backup publication ceremony",
  "operator acceptance, canary, promotion and release"
]
```

## 6. runtime.supervisor

固定来源：[runtime.supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json)。Map Git blob：`ad668f903ff47c897cf2fc32de7bf93c075c60a6`。

owner：` runtime-control `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（12 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` start_instance ` | ` start_instance ` | ` pub fn start( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` observe_health ` | ` observe_health ` | ` pub fn tick( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` drain ` | ` drain ` | ` pub fn drain( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` stop_instance ` | ` stop_instance ` | ` pub fn stop( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` kill_instance ` | ` kill_instance ` | ` pub fn kill( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` restart_instance ` | ` restart_instance ` | ` pub fn restart( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` load_next ` | ` load_next ` | ` pub fn upgrade( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` rollback_release ` | ` rollback_release ` | ` pub fn rollback( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` signed_upgrade ` | ` signed_upgrade ` | ` pub fn apply_production_grant( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` signed_rollback ` | ` signed_rollback ` | ` pub fn apply_production_grant( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` reconcile_signed_intent ` | ` reconcile_signed_intent ` | ` pub fn resolve_production_recovery( ` | ` codex-rs/hepta-supervisor/src/supervisor.rs ` | ` owner_native ` |
| ` recover_writer_handoff ` | ` recover_writer_handoff ` | ` DurableWriterHandoffJournalV1::recover_at_least ` | ` codex-rs/hepta-supervisor/src/writer_handoff.rs ` | ` owner_native ` |

### operations 原文（12 项）

```json
[
  {
    "designOperation": "start_instance",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn start(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "native_unit_and_launch_faults",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/unix_tests.rs",
        "kind": "native_process_identity",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Creates a generation-fenced managed process from a registered release, retains failed lease-publication children under hard-kill quarantine, and recovers exact process identity without PID-only trust.",
    "operation": "start_instance",
    "nativeSymbol": "pub fn start(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "observe_health",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn tick(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "fault_lifecycle_and_restart_budget",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/unix_tests.rs",
        "kind": "readiness_and_generation_fences",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Consumes exact Agentd/process observations under the active generation, requires critical-store/revocation-baseline/required-port/admission readiness before Running, fences stale processes, and advances bounded durable restart/recovery state without inferring task success.",
    "operation": "observe_health",
    "nativeSymbol": "pub fn tick(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "drain",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn drain(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "drain_stop_and_restart",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/unix_tests.rs",
        "kind": "agentd_drain_ack_generation_fence",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Transitions the lifecycle fence to Draining and requires an exact typed Agentd Drain acknowledgement for the current spawn/draining generation. Agentd first closes App Server admission and waits for already-admitted RPC handlers, then requires zero running assistant turns and zero unclassified durable Automation/TaskFlow blockers. Durable uncertain/indeterminate effects remain unknown for reconciliation rather than being relabelled complete. A crash after durable Draining replays the idempotent Drain RPC; unavailable drain evidence fails closed into bounded stop escalation, never a drain==SIGTERM shortcut.",
    "operation": "drain",
    "nativeSymbol": "pub fn drain(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "stop_instance",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn stop(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "graceful_stop",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Escalates an already fenced lifecycle through graceful process stop without treating process termination as user-task success.",
    "operation": "stop_instance",
    "nativeSymbol": "pub fn stop(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "kill_instance",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn kill(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "hard_kill_and_fencing",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Issues a hard kill only to the exact managed process identity after generation fencing; it is an emergency lifecycle action, not release success.",
    "operation": "kill_instance",
    "nativeSymbol": "pub fn kill(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "restart_instance",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn restart(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "bounded_restart_budget",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Restarts the current admitted release under generation fencing; automatic crash restarts are separately bounded by the durable restart window/backoff record.",
    "operation": "restart_instance",
    "nativeSymbol": "pub fn restart(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "load_next",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn upgrade(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "upgrade_rollback_and_recovery",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/release_transaction.rs",
        "kind": "durable_transaction_integrity",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/signed_authority.rs",
        "kind": "signed_release_and_recovery_authority",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Transitions through a fsynced unified release transaction that binds exact source/target immutable manifests/program bytes, the per-Agent allow/revoke admission frontier, the exact source/target pair identity, lifecycle/release-state generations and optional signed production authority. The pair digest is a structural binding, not independent semantic-compatibility approval; runtime compatibility is established by the typed Agentd/Matrixd readiness contract before commit. A production daemon configured with a verifier rejects unsigned Upgrade/Rollback.",
    "operation": "load_next",
    "nativeSymbol": "pub fn upgrade(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "rollback_release",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn rollback(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "rollback_readmission",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Re-resolves the recorded predecessor at the final-use boundary, rejects revoked or allowance/frontier-drifted releases, verifies its immutable bytes against the durable transaction, and starts rollback only as a fresh process generation.",
    "operation": "rollback_release",
    "nativeSymbol": "pub fn rollback(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "signed_upgrade",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn apply_production_grant(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "signed_upgrade_authority",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/signed_authority.rs",
        "kind": "signed_authority_contract",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/release_transaction.rs",
        "kind": "durable_transaction_integrity",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Admits a production upgrade only after independently signed H7 and production-grant verification binds exact source/target releases and current control/lifecycle/daemon-authority fences. The fsynced release transaction additionally binds immutable program digests plus the current per-Agent admission frontier before drain.",
    "operation": "signed_upgrade",
    "nativeSymbol": "pub fn apply_production_grant(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "signed_rollback",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn apply_production_grant(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "signed_rollback_authority",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/signed_authority.rs",
        "kind": "signed_authority_contract",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/release_transaction.rs",
        "kind": "durable_transaction_integrity",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Admits production rollback only through an independently signed grant; the predecessor is freshly re-resolved and its manifest/program digests and current allow/revoke admission frontier must exactly match the durable transaction witness.",
    "operation": "signed_rollback",
    "nativeSymbol": "pub fn apply_production_grant(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "designOperation": "reconcile_signed_intent",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-supervisor/src/supervisor.rs",
      "symbol": "pub fn resolve_production_recovery(",
      "buildTarget": "codex-hepta-supervisor"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-supervisor/src/supervisor_tests.rs",
        "kind": "signed_recovery_ceremony",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/signed_authority.rs",
        "kind": "signed_recovery_contract",
        "command": "just test -p codex-hepta-supervisor --lib"
      },
      {
        "path": "codex-rs/hepta-supervisor/src/release_transaction.rs",
        "kind": "durable_recovery_terminal_state",
        "command": "just test -p codex-hepta-supervisor --lib"
      }
    ],
    "sourceSemantics": "Quarantines ambiguous signed transitions as recovery_required while keeping owner-local status/recovery RPCs reachable. An independently signed recovery decision must bind the grant, signed-intent digest, release-transaction digest, observed immutable release bytes and current lifecycle/daemon-authority fences; the current admission frontier is revalidated again before terminal commit/rollback.",
    "operation": "reconcile_signed_intent",
    "nativeSymbol": "pub fn resolve_production_recovery(",
    "sourcePath": "codex-rs/hepta-supervisor/src/supervisor.rs",
    "sourcePathExists": true,
    "sourceBlob": "f854f1a0c40024a5fe01ea42b5139d8c77bfc778"
  },
  {
    "operation": "recover_writer_handoff",
    "nativeSymbol": "DurableWriterHandoffJournalV1::recover_at_least",
    "sourcePath": "codex-rs/hepta-supervisor/src/writer_handoff.rs",
    "state": "source_implemented_logical_lock_owner_lifetime",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-supervisor/src/writer_handoff_recovery_tests.rs",
      "codex-rs/hepta-supervisor/src/writer_handoff_lock_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "recover_writer_handoff",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-supervisor/src/writer_handoff_lock.rs",
        "symbol": "LockedHandoffFile::acquire"
      }
    ],
    "sourceBlob": "9d00b02419cb76f1647ed1741981763cb78f3970"
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Retain candidate-bound native RED/GREEN receipts for logical-owner drop and failed recovery while a passive duplicated descriptor remains open, then qualify the actual Unix fork-copy drop case and the full supervisor suite on the recorded candidate.",
  "Keep fork-child terminal observation and cleanup outcomes explicit: the donor fixture has a fixed two-second window, and deadline expiry does not prove successful cleanup or authorize a broader process-management claim."
]
```

### externalEvidenceGates 原文（4 项）

```json
[
  "exact deployed hepta-supervisord binary, host identity and externally pinned production grant/H7 verifier configuration",
  "target-host startup, watchdog, typed Agentd drain, bounded restart and signed-recovery crash/fault/latency measurements",
  "deployment and independent verification of the external release-policy/authority distribution feeding Fleet allow/revoke state and signer rotation",
  "independent operational acceptance of signed upgrade, rollback and recovery outcomes"
]
```

## 7. runtime.fleet

固定来源：[runtime.fleet](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json)。Map Git blob：`c6dfea9f118d456b81e058155b3edc80851435b5`。

owner：` fleet-runtime `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` admit_host ` | ` admit_host ` | ` pub fn admit_host( ` | ` codex-rs/hepta-fleet/src/lease_ledger.rs ` | ` owner_native ` |
| ` allocate ` | ` allocate ` | ` pub fn issue( ` | ` codex-rs/hepta-fleet/src/lease_ledger.rs ` | ` owner_native ` |
| ` renew_or_revoke ` | ` renew_or_revoke ` | ` pub fn renew_or_revoke( ` | ` codex-rs/hepta-fleet/src/lease_ledger.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "designOperation": "admit_host",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-fleet/src/lease_ledger.rs",
      "symbol": "pub fn admit_host(",
      "buildTarget": "codex-hepta-fleet::lease_ledger"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-fleet/src/lease_ledger_tests.rs",
        "kind": "native_unit",
        "command": "just test -p codex-hepta-fleet --lib"
      }
    ],
    "sourceSemantics": "Admits an explicitly enrolled host with generation, capacity, epoch, and failure-domain identity.",
    "operation": "admit_host",
    "nativeSymbol": "pub fn admit_host(",
    "sourcePath": "codex-rs/hepta-fleet/src/lease_ledger.rs",
    "sourcePathExists": true,
    "sourceBlob": "2b70c835242e817fd51ba6eba9d3f1b812483254"
  },
  {
    "designOperation": "allocate",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-fleet/src/lease_ledger.rs",
      "symbol": "pub fn issue(",
      "buildTarget": "codex-hepta-fleet::lease_ledger"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-fleet/src/lease_ledger_tests.rs",
        "kind": "conservation_and_fencing",
        "command": "just test -p codex-hepta-fleet --lib"
      }
    ],
    "sourceSemantics": "Issues bounded allocation leases only after capacity, floors, freshness, and generation checks.",
    "operation": "allocate",
    "nativeSymbol": "pub fn issue(",
    "sourcePath": "codex-rs/hepta-fleet/src/lease_ledger.rs",
    "sourcePathExists": true,
    "sourceBlob": "2b70c835242e817fd51ba6eba9d3f1b812483254"
  },
  {
    "designOperation": "renew_or_revoke",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-fleet/src/lease_ledger.rs",
      "symbol": "pub fn renew_or_revoke(",
      "buildTarget": "codex-hepta-fleet::lease_ledger"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-fleet/src/lease_ledger_tests.rs",
        "kind": "lease_recovery",
        "command": "just test -p codex-hepta-fleet --lib"
      }
    ],
    "sourceSemantics": "Renews, revokes, or quarantines a lease under current epoch and holder reconciliation.",
    "operation": "renew_or_revoke",
    "nativeSymbol": "pub fn renew_or_revoke(",
    "sourcePath": "codex-rs/hepta-fleet/src/lease_ledger.rs",
    "sourcePathExists": true,
    "sourceBlob": "2b70c835242e817fd51ba6eba9d3f1b812483254"
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "Connect the in-memory lease component to supervisor-owned durable FleetRegistry grants, fences, and a real capacity observer."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "real enrolled host capacity observation",
  "non-test local grant enforcement",
  "partition and lease-expiry target qualification"
]
```

## 8. runtime.agentd

固定来源：[runtime.agentd](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json)。Map Git blob：`4016d898070000b1b6dd579c825251380ed3bbb6`。

owner：` agent-runtime `；productCallerState：` daemon_lifecycle_and_durable_run_start_projection_composed_physical_codex_pending `；productionWriterState：` not_established `。

### 操作导航（10 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` compose_runtime ` | ` compose_runtime ` | ` pub fn compose_runtime( ` | ` codex-rs/hepta-agentd/src/lane_b_runtime.rs ` | ` owner_native ` |
| ` start_run ` | ` start_run ` | ` pub fn start_run( ` | ` codex-rs/hepta-agentd/src/lane_b_runtime.rs ` | ` owner_native ` |
| ` admit_revalidated_run_start ` | ` admit_revalidated_run_start ` | ` pub(crate) fn start_revalidated_run_start( ` | ` codex-rs/hepta-agentd/src/lane_b_runtime.rs ` | ` owner_native ` |
| ` cancel_run ` | ` cancel_run ` | ` pub fn cancel_run( ` | ` codex-rs/hepta-agentd/src/lane_b_runtime.rs ` | ` owner_native ` |
| ` attach_context ` | ` attach_context ` | ` pub fn attach_context( ` | ` codex-rs/hepta-agentd/src/lane_b_runtime.rs ` | ` owner_native ` |
| ` daemon_run_lifecycle_control ` | ` daemon_run_lifecycle_control ` | ` crate::AgentdMethod::RunStart ` | ` codex-rs/hepta-agentd/src/state_control.rs ` | ` owner_native ` |
| ` agentd_neuron_owner ` | ` agentd_neuron_owner ` | ` pub struct AgentdNeuronOwner ` | ` codex-rs/hepta-agentd/src/neuron_runtime.rs ` | ` owner_native ` |
| ` shared_terminal_cell_train ` | ` shared_terminal_cell_train ` | ` pub async fn train( ` | ` codex-rs/hepta-agentd/src/shared_terminal_cell.rs ` | ` owner_native ` |
| ` shared_terminal_cell_load ` | ` shared_terminal_cell_load ` | ` pub async fn load( ` | ` codex-rs/hepta-agentd/src/shared_terminal_cell.rs ` | ` owner_native ` |
| ` shared_terminal_cell_predict ` | ` shared_terminal_cell_predict ` | ` pub async fn predict( ` | ` codex-rs/hepta-agentd/src/shared_terminal_cell.rs ` | ` owner_native ` |

### operations 原文（10 项）

```json
[
  {
    "designOperation": "compose_runtime",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
      "symbol": "pub fn compose_runtime(",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        "kind": "native_unit",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Validates immutable supervisor/Agentd generations, configuration, and owner-port identities.",
    "operation": "compose_runtime",
    "nativeSymbol": "pub fn compose_runtime(",
    "sourcePath": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "c0fb09512f4567a6b6624eee44822ff5fd43ab26"
  },
  {
    "designOperation": "start_run",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
      "symbol": "pub fn start_run(",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        "kind": "snapshot_and_capacity",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Admits a bounded run and freezes request, objective, body, artifact, authority, and deadline identity; it does not itself dispatch a Codex turn.",
    "operation": "start_run",
    "nativeSymbol": "pub fn start_run(",
    "sourcePath": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "c0fb09512f4567a6b6624eee44822ff5fd43ab26"
  },
  {
    "designOperation": "admit_revalidated_run_start",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
      "symbol": "pub(crate) fn start_revalidated_run_start(",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-learning-ledger/src/run_start.rs",
        "symbol": "pub struct RunStartRecordV1",
        "buildTarget": "codex-hepta-learning-ledger",
        "ownerModule": "learning.ledger"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        "kind": "durable_run_start_projection",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Projects only a product-revalidated durable RunStartRecordV1 into the sole daemon coordinator. request_digest is admitted_source_digest; body/artifact/authority/generation/fence/deadline are exact durable fields. ExplicitAbstain never enters runtime admission. Authentication/currentness remains a caller precondition.",
    "operation": "admit_revalidated_run_start",
    "nativeSymbol": "pub(crate) fn start_revalidated_run_start(",
    "sourcePath": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "c0fb09512f4567a6b6624eee44822ff5fd43ab26"
  },
  {
    "designOperation": "cancel_run",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
      "symbol": "pub fn cancel_run(",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        "kind": "cancellation_race",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Transitions only Agentd-owned lifecycle state. Pre-dispatch cancellation is locally terminal; post-dispatch cancellation remains pending/indeterminate until the execution owner is invoked and observed by a separately composed caller.",
    "operation": "cancel_run",
    "nativeSymbol": "pub fn cancel_run(",
    "sourcePath": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "c0fb09512f4567a6b6624eee44822ff5fd43ab26"
  },
  {
    "designOperation": "attach_context",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
      "symbol": "pub fn attach_context(",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
        "kind": "mixed_generation_rejection",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Accepts context only when its receipt binds the complete frozen run tuple; it does not itself submit the context to Codex.",
    "operation": "attach_context",
    "nativeSymbol": "pub fn attach_context(",
    "sourcePath": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "c0fb09512f4567a6b6624eee44822ff5fd43ab26"
  },
  {
    "designOperation": "daemon_run_lifecycle_control",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/state_control.rs",
      "symbol": "crate::AgentdMethod::RunStart",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
        "symbol": "pub fn start_run(",
        "buildTarget": "codex-hepta-agentd",
        "ownerModule": "runtime.agentd"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/state_isolation_tests.rs",
        "kind": "daemon_control_lifecycle",
        "command": "just test -p codex-hepta-agentd --lib"
      },
      {
        "path": "codex-rs/hepta-agentd/src/runtime_tests.rs",
        "kind": "bounded_drain_reconciliation",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "The real Agentd control path owns one Fleet-budget-bounded run coordinator, advertises run.lifecycle/1.1, enforces complete frozen tuple/deadline/reasoned-cancellation semantics, advances a 3-second cancellation-ack deadline to Indeterminate, supports exact-revision closed-record release, and keeps terminal reconciliation available during bounded drain.",
    "operation": "daemon_run_lifecycle_control",
    "nativeSymbol": "crate::AgentdMethod::RunStart",
    "sourcePath": "codex-rs/hepta-agentd/src/state_control.rs",
    "sourcePathExists": true,
    "sourceBlob": "cd715f6b0f1977fd7454c2776ecccca4479defdf"
  },
  {
    "designOperation": "agentd_neuron_owner",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-agentd/src/neuron_runtime.rs",
      "symbol": "pub struct AgentdNeuronOwner",
      "buildTarget": "codex-hepta-agentd"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-neuron/src/runtime.rs",
        "symbol": "pub struct NeuronRuntime",
        "buildTarget": "codex-hepta-neuron",
        "ownerModule": "neuron.runtime"
      },
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-neuron/src/inference_control.rs",
        "symbol": "pub trait NeuronInferenceControlPort",
        "buildTarget": "codex-hepta-neuron",
        "ownerModule": "neuron.runtime"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/src/neuron_runtime_tests.rs",
        "kind": "compiled_owner_boundary",
        "command": "just test -p codex-hepta-agentd --lib"
      }
    ],
    "sourceSemantics": "Owns one long-lived NeuronRuntime plus its inference-control port; construction remains explicit and does not self-activate the daemon lifecycle.",
    "operation": "agentd_neuron_owner",
    "nativeSymbol": "pub struct AgentdNeuronOwner",
    "sourcePath": "codex-rs/hepta-agentd/src/neuron_runtime.rs",
    "sourcePathExists": true,
    "sourceBlob": "3e880ef975af2b7210a7466b9fb4e12f62937d9c"
  },
  {
    "operation": "shared_terminal_cell_train",
    "designOperation": "shared_terminal_cell_train",
    "nativeSymbol": "pub async fn train(",
    "sourcePath": "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
        "kind": "native_integration",
        "command": "just test --locked -p codex-hepta-agentd --test terminal_cell_owner -E test(clean_agent_recall_replay_training_load_and_source_withdrawal)"
      }
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "buildTarget": "codex-hepta-agentd",
    "sourceSemantics": "Purpose-scoped same-host candidate table consumer; revalidates exact Memory owner/revision, frozen ledger and artifact eligibility before use; no production selection authority.",
    "sourceBlob": "ada0d0f52e842d73bf2c0ee3f66e041420f6ceb3"
  },
  {
    "operation": "shared_terminal_cell_load",
    "designOperation": "shared_terminal_cell_load",
    "nativeSymbol": "pub async fn load(",
    "sourcePath": "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
        "kind": "native_integration",
        "command": "just test --locked -p codex-hepta-agentd --test terminal_cell_owner -E test(clean_agent_recall_replay_training_load_and_source_withdrawal)"
      }
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "buildTarget": "codex-hepta-agentd",
    "sourceSemantics": "Purpose-scoped same-host candidate table consumer; revalidates exact Memory owner/revision, frozen ledger and artifact eligibility before use; no production selection authority.",
    "sourceBlob": "ada0d0f52e842d73bf2c0ee3f66e041420f6ceb3"
  },
  {
    "operation": "shared_terminal_cell_predict",
    "designOperation": "shared_terminal_cell_predict",
    "nativeSymbol": "pub async fn predict(",
    "sourcePath": "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
        "kind": "native_integration",
        "command": "just test --locked -p codex-hepta-agentd --test terminal_cell_owner -E test(clean_agent_recall_replay_training_load_and_source_withdrawal)"
      }
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "buildTarget": "codex-hepta-agentd",
    "sourceSemantics": "Purpose-scoped same-host candidate table consumer; revalidates exact Memory owner/revision, frozen ledger and artifact eligibility before use; no production selection authority.",
    "sourceBlob": "ada0d0f52e842d73bf2c0ee3f66e041420f6ceb3"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Compose the canonical caller through runtime.codex so physical turn start/interrupt and terminal observations are real invocation edges rather than design-only delegated targets.",
  "Bind current AuthBus/trust revalidation to the durable RunStartRecordV1 before start_revalidated_run_start; raw journal records are not current authentication evidence. Post-dispatch recovery remains Indeterminate and non-redispatchable.",
  "Compose AgentdNeuronOwner into the daemon-owned run lifecycle once the canonical runtime.agentd coordinator line converges, with selected-artifact/current inference.control/witness dependencies constructed by the registered owner composition rather than an ambient singleton."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "deployed Agentd process and authenticated socket identity",
  "target-host drain/restart/backpressure measurements",
  "independent acceptance, promotion and release"
]
```

## 9. runtime.codex

固定来源：[runtime.codex](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/runtime.codex/IMPLEMENTATION_MAP.json)。Map Git blob：`20ad0366e259258f85c208e79cfd2c5fea6f3370`。

owner：` codex-integration `；productCallerState：` composed_candidate_exact_head_qualification_pending `；productionWriterState：` existing_app_server_owner `。

### 操作导航（4 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` open_thread ` | ` open_thread ` | ` pub(crate) async fn thread_start( ` | ` codex-rs/app-server/src/request_processors/thread_processor.rs ` | ` resolved_alias_native ` |
| ` submit_turn ` | ` submit_turn ` | ` pub(crate) async fn turn_start( ` | ` codex-rs/app-server/src/request_processors/turn_processor.rs ` | ` resolved_alias_native ` |
| ` dispatch_tool ` | ` dispatch_tool ` | ` pub(crate) async fn turn_start( ` | ` codex-rs/app-server/src/request_processors/turn_processor.rs ` | ` owner_boundary ` |
| ` observe_delivery ` | ` observe_delivery ` | ` pub(crate) async fn turn_start( ` | ` codex-rs/app-server/src/request_processors/turn_processor.rs ` | ` owner_boundary ` |

### operations 原文（4 项）

```json
[
  {
    "designOperation": "open_thread",
    "mappingClass": "resolved_alias_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/app-server/src/request_processors/thread_processor.rs",
      "symbol": "pub(crate) async fn thread_start(",
      "buildTarget": "codex-app-server"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/app-server/tests/suite/v2/thread_start.rs",
        "kind": "product_protocol_integration",
        "command": "just test -p codex-app-server --test all thread_start"
      }
    ],
    "sourceSemantics": "Creates a protocol-visible thread through the canonical App Server handler.",
    "operation": "open_thread",
    "nativeSymbol": "pub(crate) async fn thread_start(",
    "sourcePath": "codex-rs/app-server/src/request_processors/thread_processor.rs",
    "sourcePathExists": true,
    "sourceBlob": "aa0e5cbda87f6a71e9e6cd2e824a6c188ddbe0c1"
  },
  {
    "designOperation": "submit_turn",
    "mappingClass": "resolved_alias_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/app-server/src/request_processors/turn_processor.rs",
      "symbol": "pub(crate) async fn turn_start(",
      "buildTarget": "codex-app-server"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/app-server/tests/suite/v2/turn_start.rs",
        "kind": "product_protocol_integration",
        "command": "just test -p codex-app-server --test all turn_start"
      }
    ],
    "sourceSemantics": "Admits a turn through the single App Server execution path.",
    "operation": "submit_turn",
    "nativeSymbol": "pub(crate) async fn turn_start(",
    "sourcePath": "codex-rs/app-server/src/request_processors/turn_processor.rs",
    "sourcePathExists": true,
    "sourceBlob": "9fd203f3d16b03e5c7edafbdb45b63dc741badc5"
  },
  {
    "designOperation": "dispatch_tool",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/app-server/src/request_processors/turn_processor.rs",
      "symbol": "pub(crate) async fn turn_start(",
      "buildTarget": "codex-app-server"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/core/src/tools/router.rs",
        "symbol": "pub async fn dispatch_tool_call_with_code_mode_result(",
        "buildTarget": "codex-core",
        "ownerModule": "runtime.codex"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/core/src/tools/executed_tool_calls_tests.rs",
        "kind": "native_tool_state",
        "command": "just test -p codex-core executed_tool_calls"
      }
    ],
    "sourceSemantics": "Admits the turn at the App Server boundary; tool dispatch remains in its declared codex-core dependency and does not transfer core ownership.",
    "operation": "dispatch_tool",
    "nativeSymbol": "pub(crate) async fn turn_start(",
    "sourcePath": "codex-rs/app-server/src/request_processors/turn_processor.rs",
    "sourcePathExists": true,
    "sourceBlob": "9fd203f3d16b03e5c7edafbdb45b63dc741badc5"
  },
  {
    "designOperation": "observe_delivery",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/app-server/src/request_processors/turn_processor.rs",
      "symbol": "pub(crate) async fn turn_start(",
      "buildTarget": "codex-app-server"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/core/src/codex_thread.rs",
        "symbol": "pub(crate) async fn submit_turn_input_and_wait_for_exact_admission(",
        "buildTarget": "codex-core",
        "ownerModule": "runtime.codex"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/app-server/tests/suite/v2/turn_start.rs",
        "kind": "admission_and_delivery",
        "command": "just test -p codex-app-server --test all turn_start"
      }
    ],
    "sourceSemantics": "Admits the turn at the App Server boundary and delegates exact input admission observation to its declared codex-core dependency.",
    "operation": "observe_delivery",
    "nativeSymbol": "pub(crate) async fn turn_start(",
    "sourcePath": "codex-rs/app-server/src/request_processors/turn_processor.rs",
    "sourcePathExists": true,
    "sourceBlob": "9fd203f3d16b03e5c7edafbdb45b63dc741badc5"
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "current runtime.codex exact-head, deterministic synthetic-merge, focused product fault-matrix, and product E2E evidence are pending for this composed candidate"
]
```

### externalEvidenceGates 原文（6 项）

```json
[
  "independently operated final-use authority endpoint, signer-key custody, pathname plus connected-peer socket identity, trusted time/revocation distribution, and external anti-rollback recovery for replay/epoch state",
  "authenticated target-host Agentd/App Server process, generation and socket identity",
  "real model/provider terminal stream observation under the selected target deployment",
  "delegated external-tool terminal observation and acknowledgement-loss qualification",
  "independent policy/evidence for resolving or quarantining indeterminate effects when ephemeral App Server history is unavailable; no unauthenticated manual release",
  "independent acceptance, activation/canary, promotion and release"
]
```

## 10. auth.authbus

固定来源：[auth.authbus](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/auth.authbus/IMPLEMENTATION_MAP.json)。Map Git blob：`6a19185443e1bf2ecc943b425fecc1b898280c0b`。

owner：` identity-access `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` authenticate ` | ` authenticate ` | ` authenticate ` | ` codex-rs/hepta-authbus/src/signed.rs ` | ` owner_native ` |
| ` admit_authbus_message ` | ` admit_authbus_message ` | ` admit_authbus_message ` | ` codex-rs/hepta-evidence/src/authbus_store.rs ` | ` owner_native ` |
| ` enqueue_authbus_message ` | ` enqueue_authbus_message ` | ` enqueue_authbus_message ` | ` codex-rs/hepta-evidence/src/authbus_outbox.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "operation": "authenticate",
    "nativeSymbol": "authenticate",
    "sourcePath": "codex-rs/hepta-authbus/src/signed.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "authenticate",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "admit_authbus_message",
    "nativeSymbol": "admit_authbus_message",
    "sourcePath": "codex-rs/hepta-evidence/src/authbus_store.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "admit_authbus_message",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "enqueue_authbus_message",
    "nativeSymbol": "enqueue_authbus_message",
    "sourcePath": "codex-rs/hepta-evidence/src/authbus_outbox.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "enqueue_authbus_message",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 11. secrets.heptabao

固定来源：[secrets.heptabao](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json)。Map Git blob：`fd043f3b38b6f9e72968a7eec5763ba157e33932`。

owner：` secrets-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（4 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` consume_kv_v2 ` | ` consume_kv_v2 ` | ` consume_kv_v2 ` | ` codex-rs/hepta-bao-adapter/src/https_consumer.rs ` | ` owner_native ` |
| ` binding ` | ` binding ` | ` binding ` | ` codex-rs/hepta-bao-adapter/src/https_consumer.rs ` | ` owner_native ` |
| ` lease_lifecycle_prepare ` | ` request_secret_lease/renew/revoke local durable intent ` | ` DurableLeaseRegistryV1::prepare_issue/prepare_renew/prepare_revoke ` | ` codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs ` | ` owner_native ` |
| ` lease_lifecycle_reconcile ` | ` ambiguous outcome reconciliation ` | ` DurableLeaseRegistryV1::mark_unknown/reconcile/expire_at ` | ` codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs ` | ` owner_native ` |

### operations 原文（4 项）

```json
[
  {
    "operation": "consume_kv_v2",
    "nativeSymbol": "consume_kv_v2",
    "sourcePath": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "kernel.final_use",
    "tests": [
      "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "consume_kv_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2fc9ce3431897ee1a9bce4485fc5d8a230a05066"
  },
  {
    "operation": "binding",
    "nativeSymbol": "binding",
    "sourcePath": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "binding",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2fc9ce3431897ee1a9bce4485fc5d8a230a05066"
  },
  {
    "operation": "lease_lifecycle_prepare",
    "nativeSymbol": "DurableLeaseRegistryV1::prepare_issue/prepare_renew/prepare_revoke",
    "sourcePath": "codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs",
    "state": "source_implemented_provider_dispatch_blocked",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "request_secret_lease/renew/revoke local durable intent",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "858b486ee74ba22073727a1d5c94d5e4e466e99c"
  },
  {
    "operation": "lease_lifecycle_reconcile",
    "nativeSymbol": "DurableLeaseRegistryV1::mark_unknown/reconcile/expire_at",
    "sourcePath": "codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs",
    "state": "source_implemented_provider_observer_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "ambiguous outcome reconciliation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "858b486ee74ba22073727a1d5c94d5e4e466e99c"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Bind the lease lifecycle owner to an authenticated product caller and durable host composition.",
  "Add provider-native dynamic lease issue/renew/revoke dispatch only after the exact HeptaBao/OpenBao endpoint contract is qualified; current compatibility status is blocking partial.",
  "Run exact-source package tests, crash/fault injection and deterministic synthetic-merge qualification for this candidate."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 12. inference.control

固定来源：[inference.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/inference.control/IMPLEMENTATION_MAP.json)。Map Git blob：`2116d9359255f99a749dcdb92fa186310ceeb779`。

owner：` inference-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（4 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` reserve_request ` | ` reserve_request ` | ` pub fn reserve_native( ` | ` codex-rs/hepta-infer-core/src/native_control.rs ` | ` owner_native ` |
| ` schedule ` | ` schedule ` | ` pub fn dispatch_native( ` | ` codex-rs/hepta-infer-core/src/native_control.rs ` | ` owner_native ` |
| ` cancel ` | ` cancel ` | ` pub fn cancel_native( ` | ` codex-rs/hepta-infer-core/src/native_control.rs ` | ` owner_native ` |
| ` settle ` | ` settle ` | ` pub fn settle_native( ` | ` codex-rs/hepta-infer-core/src/native_control.rs ` | ` owner_native ` |

### operations 原文（4 项）

```json
[
  {
    "designOperation": "reserve_request",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-core/src/native_control.rs",
      "symbol": "pub fn reserve_native(",
      "buildTarget": "codex-hepta-infer-core::durable_control::native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-core/src/native_control_tests.rs",
        "kind": "native_journal_recovery_and_observation",
        "command": "just test -p codex-hepta-infer-core --lib"
      }
    ],
    "sourceSemantics": "Pins explicit local slot capacity and exact request identity before provider contact.",
    "operation": "reserve_request",
    "nativeSymbol": "pub fn reserve_native(",
    "sourcePath": "codex-rs/hepta-infer-core/src/native_control.rs",
    "sourcePathExists": true
  },
  {
    "designOperation": "schedule",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-core/src/native_control.rs",
      "symbol": "pub fn dispatch_native(",
      "buildTarget": "codex-hepta-infer-core::durable_control::native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-core/src/native_control_tests.rs",
        "kind": "native_journal_recovery_and_observation",
        "command": "just test -p codex-hepta-infer-core --lib"
      }
    ],
    "sourceSemantics": "Syncs exact thread/provider/context dispatch intent before the actual turn/start RPC; a duplicate cannot issue a new turn.",
    "operation": "schedule",
    "nativeSymbol": "pub fn dispatch_native(",
    "sourcePath": "codex-rs/hepta-infer-core/src/native_control.rs",
    "sourcePathExists": true
  },
  {
    "designOperation": "cancel",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-core/src/native_control.rs",
      "symbol": "pub fn cancel_native(",
      "buildTarget": "codex-hepta-infer-core::durable_control::native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-core/src/native_control_tests.rs",
        "kind": "native_journal_recovery_and_observation",
        "command": "just test -p codex-hepta-infer-core --lib"
      }
    ],
    "sourceSemantics": "Persists interrupt intent without releasing an in-flight slot; acknowledgement is not terminality.",
    "operation": "cancel",
    "nativeSymbol": "pub fn cancel_native(",
    "sourcePath": "codex-rs/hepta-infer-core/src/native_control.rs",
    "sourcePathExists": true
  },
  {
    "designOperation": "settle",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-core/src/native_control.rs",
      "symbol": "pub fn settle_native(",
      "buildTarget": "codex-hepta-infer-core::durable_control::native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-core/src/native_control_tests.rs",
        "kind": "native_journal_recovery_and_observation",
        "command": "just test -p codex-hepta-infer-core --lib"
      }
    ],
    "sourceSemantics": "Persists actual matching terminal and optional observed u64 usage; terminality releases a local slot, unknown execution remains held. Late usage can refine an observation without changing its terminal outcome.",
    "operation": "settle",
    "nativeSymbol": "pub fn settle_native(",
    "sourcePath": "codex-rs/hepta-infer-core/src/native_control.rs",
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Connect economically meaningful quota and hardware-capacity authorities; the shipped native policy reserves only local in-flight run slots.",
  "Implement authenticated recovery of actual provider terminal/usage observations after process loss; reopening a dispatched run conservatively holds capacity and never replays it.",
  "Add bounded archival/retention under the same journal owner; the current 64 MiB journal rejects further appends without truncating acknowledged history."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "real provider deployment and crash/cancellation acceptance",
  "real economic quota/capacity authority integration",
  "authenticated remote-worker transport if a separate process is introduced"
]
```

## 13. inference.worker

固定来源：[inference.worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/inference.worker/IMPLEMENTATION_MAP.json)。Map Git blob：`8ad25b2f06c9d48dab97eb89cb0ccc244e0f75d3`。

owner：` inference-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` load_model ` | ` load_model ` | ` pub fn load_model( ` | ` codex-rs/hepta-infer-worker-host/src/model_worker.rs ` | ` owner_native ` |
| ` run ` | ` run ` | ` pub async fn run( ` | ` codex-rs/hepta-infer-worker-host/src/native_run_control.rs ` | ` owner_native ` |
| ` unload ` | ` unload ` | ` pub fn unload_model( ` | ` codex-rs/hepta-infer-worker-host/src/model_worker.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "designOperation": "load_model",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-worker-host/src/model_worker.rs",
      "symbol": "pub fn load_model(",
      "buildTarget": "codex-hepta-infer-worker-host::model_worker"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs",
        "kind": "manifest_and_resource_binding",
        "command": "just test -p codex-hepta-infer-worker-host --lib"
      }
    ],
    "sourceSemantics": "Validates supplied manifest and resource-grant bindings before invoking the injected driver; physical artifact/device loading remains that driver owner's responsibility.",
    "operation": "load_model",
    "nativeSymbol": "pub fn load_model(",
    "sourcePath": "codex-rs/hepta-infer-worker-host/src/model_worker.rs",
    "sourcePathExists": true,
    "sourceBlob": "26ee6559a9de6baf5846ea367d02e5ffb01a40d6"
  },
  {
    "designOperation": "run",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
      "symbol": "pub async fn run(",
      "buildTarget": "codex-hepta-infer-worker-host::native_app_server"
    },
    "delegatedCallees": [
      {
        "role": "supporting_algorithm",
        "path": "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        "symbol": "async fn run_once(",
        "buildTarget": "codex-hepta-infer-worker-host::native_app_server",
        "ownerModule": "inference.worker"
      },
      {
        "role": "supporting_algorithm",
        "path": "codex-rs/hepta-infer-core/src/native_control.rs",
        "symbol": "pub fn settle_native(",
        "buildTarget": "codex-hepta-infer-core::durable_control::native",
        "ownerModule": "inference.control"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
        "kind": "duplicate_reopen_and_predispatch_cancellation",
        "command": "just test -p codex-hepta-infer-worker-host --lib"
      },
      {
        "path": "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
        "kind": "matching_native_events_and_usage",
        "command": "just test -p codex-hepta-infer-worker-host --lib"
      }
    ],
    "sourceSemantics": "Reserves through durable inference.control, calls the actual private Agent/App Server once, and commits matching terminal/output/optional-token observations before returning. Reopen and duplicate paths consume the journal without invoking the provider again.",
    "operation": "run",
    "nativeSymbol": "pub async fn run(",
    "sourcePath": "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
    "sourcePathExists": true,
    "sourceBlob": "4327512c3729f77172267432809b0daaafd93e14"
  },
  {
    "designOperation": "unload",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-infer-worker-host/src/model_worker.rs",
      "symbol": "pub fn unload_model(",
      "buildTarget": "codex-hepta-infer-worker-host::model_worker"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs",
        "kind": "drain_and_unload",
        "command": "just test -p codex-hepta-infer-worker-host --lib"
      }
    ],
    "sourceSemantics": "Drains and unloads only the exact admitted generation and releases acquired resources.",
    "operation": "unload",
    "nativeSymbol": "pub fn unload_model(",
    "sourcePath": "codex-rs/hepta-infer-worker-host/src/model_worker.rs",
    "sourcePathExists": true,
    "sourceBlob": "26ee6559a9de6baf5846ea367d02e5ffb01a40d6"
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Implement a local model driver that acquires and proves actual weights, device and memory grants before claiming isolated local inference.",
  "Implement trusted provider reconciliation for dispatch-unknown/reopened runs and later missing token usage; do not infer zero usage or safe replay from transport loss."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "identified real weights/tokenizer/runtime/device",
  "isolated deployed worker process and authenticated control channel",
  "OOM/device-reset/load-kill target qualification"
]
```

## 14. objective.compiler

固定来源：[objective.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/objective.compiler/IMPLEMENTATION_MAP.json)。Map Git blob：`c6f3f8bd89c0d6f6d5754da0656782cc892c35d8`。

owner：` intelligence-platform `；productCallerState：` source_composed_authenticated_agentd_not_activated `；productionWriterState：` not_applicable_stateless `。

### 操作导航（10 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` decode_source_envelope_json_v1 ` | ` decode_source_envelope_json_v1 ` | ` codex_hepta_objective::decode_source_envelope_json_v1 ` | ` codex-rs/hepta-objective/src/source_envelope_json.rs ` | ` owner_native ` |
| ` validate_structure ` | ` validate_structure ` | ` ObjectiveSourceEnvelopeV1::validate_structure ` | ` codex-rs/hepta-objective/src/source_envelope_validation.rs ` | ` owner_native ` |
| ` canonical_objective_intent_digest_v1 ` | ` canonical_objective_intent_digest_v1 ` | ` codex_hepta_objective::canonical_objective_intent_digest_v1 ` | ` codex-rs/hepta-objective/src/objective_admission.rs ` | ` owner_native ` |
| ` admit_and_compile_objective_v1 ` | ` admit_and_compile_objective_v1 ` | ` codex_hepta_objective::admit_and_compile_objective_v1 ` | ` codex-rs/hepta-objective/src/objective_admission.rs ` | ` owner_native ` |
| ` check_feasibility_v1 ` | ` check_feasibility_v1 ` | ` codex_hepta_objective::check_feasibility_v1 ` | ` codex-rs/hepta-objective/src/feasibility.rs ` | ` owner_native ` |
| ` compile ` | ` compile ` | ` crate::compiler::compile ` | ` codex-rs/hepta-objective/src/compiler.rs ` | ` owner_native ` |
| ` encode_objective_function_v1 ` | ` encode_objective_function_v1 ` | ` codex_hepta_objective::encode_objective_function_v1 ` | ` codex-rs/hepta-objective/src/objective_function_v1.rs ` | ` owner_native ` |
| ` admit_objective_v1 ` | ` admit_objective_v1 ` | ` codex_hepta_objective::admit_objective_v1 ` | ` codex-rs/hepta-objective/src/objective_admission.rs ` | ` owner_native ` |
| ` compile_admitted_objective_v1 ` | ` compile_admitted_objective_v1 ` | ` codex_hepta_objective::compile_admitted_objective_v1 ` | ` codex-rs/hepta-objective/src/objective_admission.rs ` | ` owner_native ` |
| ` decode_objective_function_v1 ` | ` decode_objective_function_v1 ` | ` codex_hepta_objective::decode_objective_function_v1 ` | ` codex-rs/hepta-objective/src/objective_function_v1.rs ` | ` owner_native ` |

### operations 原文（10 项）

```json
[
  {
    "operation": "decode_source_envelope_json_v1",
    "nativeSymbol": "codex_hepta_objective::decode_source_envelope_json_v1",
    "sourcePath": "codex-rs/hepta-objective/src/source_envelope_json.rs",
    "inputs": [
      "bounded JSON bytes"
    ],
    "outputs": [
      "ObjectiveSourceEnvelopeV1"
    ],
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
        "symbol": "decodes_all_fields_without_loss_or_semantic_admission"
      }
    ],
    "designOperation": "decode_source_envelope_json_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "d63aa3e9cd18756c13029ae2fe2ca00367a0dddf"
  },
  {
    "operation": "validate_structure",
    "nativeSymbol": "ObjectiveSourceEnvelopeV1::validate_structure",
    "sourcePath": "codex-rs/hepta-objective/src/source_envelope_validation.rs",
    "inputs": [
      "ObjectiveSourceEnvelopeV1"
    ],
    "outputs": [
      "validated owner-local structure"
    ],
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
        "symbol": "text_limits_count_utf8_bytes_for_every_source_field"
      }
    ],
    "designOperation": "validate_structure",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "5dc5676e23de3b4a661e1520a0c5ae4a1dc2020d"
  },
  {
    "operation": "canonical_objective_intent_digest_v1",
    "nativeSymbol": "codex_hepta_objective::canonical_objective_intent_digest_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_admission.rs",
    "inputs": [
      "ObjectiveSourceEnvelopeV1"
    ],
    "outputs": [
      "canonical intent digest"
    ],
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "semantic_array_reordering_preserves_intent_digest"
      }
    ],
    "designOperation": "canonical_objective_intent_digest_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "87f72baa003556720db120827442a838b391cd3f"
  },
  {
    "operation": "admit_and_compile_objective_v1",
    "nativeSymbol": "codex_hepta_objective::admit_and_compile_objective_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_admission.rs",
    "inputs": [
      "ObjectiveSourceEnvelopeV1",
      "ObjectiveAdmissionProfileV1",
      "ObjectiveAdmissionContextV1"
    ],
    "outputs": [
      "ObjectiveAdmissionReceiptV1",
      "ObjectiveCompileReceipt",
      "ObjectiveConflictReceipt"
    ],
    "state": "source_implemented_compatibility_convenience_wrapper",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "complete_profile_bound_envelope_compiles_without_dropping_fields"
      },
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "untrusted_evidence_reaches_native_authority_rejection"
      },
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "oversized_profile_mapping_set_is_rejected"
      },
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "risk_profile_ordering_is_monotone"
      }
    ],
    "designOperation": "admit_and_compile_objective_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "productRole": "compatibility_not_canonical_product_path",
    "sourceBlob": "87f72baa003556720db120827442a838b391cd3f"
  },
  {
    "operation": "check_feasibility_v1",
    "nativeSymbol": "codex_hepta_objective::check_feasibility_v1",
    "sourcePath": "codex-rs/hepta-objective/src/feasibility.rs",
    "inputs": [
      "RegisteredGrammarV1",
      "ConstraintAtomV1",
      "OracleBudgetV1"
    ],
    "outputs": [
      "FeasibilityReceiptV1"
    ],
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/feasibility_tests.rs",
        "symbol": "registered scalar, enum and action implication fixtures"
      },
      {
        "path": "codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs",
        "symbol": "bounded exhaustive feasibility fixtures"
      }
    ],
    "designOperation": "check_feasibility_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "c540d050dfdc59688d3ef5406537b1a3c32471db"
  },
  {
    "operation": "compile",
    "nativeSymbol": "crate::compiler::compile",
    "sourcePath": "codex-rs/hepta-objective/src/compiler.rs",
    "inputs": [
      "ObjectiveSourceEnvelope"
    ],
    "outputs": [
      "ObjectiveCompileReceipt",
      "ObjectiveConflictReceipt"
    ],
    "state": "source_implemented_internal_opaque_admission_only",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/compiler_tests.rs",
        "symbol": "maximum_caller_set_compiles_to_exactly_128_actions"
      },
      {
        "path": "codex-rs/hepta-objective/src/compiler_tests.rs",
        "symbol": "intrinsic_abstain_cannot_be_forbidden"
      },
      {
        "path": "codex-rs/hepta-objective/src/compiler_tests.rs",
        "symbol": "contradictory_hard_bounds_return_inclusion_minimal_pair"
      }
    ],
    "designOperation": "compile",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "publicCompatibilityEntrypoint": "compile_prevalidated_legacy_objective_v1",
    "publicCompatibilityFeature": "qualification-legacy-compile",
    "sourceBlob": "74d3da0017f74320ac47839e46988f8cd051c587"
  },
  {
    "operation": "encode_objective_function_v1",
    "nativeSymbol": "codex_hepta_objective::encode_objective_function_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_function_v1.rs",
    "inputs": [
      "ObjectiveCompileReceipt",
      "ObjectiveSourceEnvelopeV1",
      "ObjectiveAdmissionProfileV1",
      "ObjectiveAdmissionReceiptV1"
    ],
    "outputs": [
      "canonical ObjectiveFunctionV1 bytes",
      "ObjectiveFunctionV1 protocol digest",
      "native semantic digest binding"
    ],
    "state": "source_implemented_product_publication_bound",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-intelligence/src/objective_run_tests.rs",
        "symbol": "authenticated_objective_is_durable_before_product_receipt_returns"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/run_start_tests.rs",
        "symbol": "objective_protocol_digest_mismatch_rejects_before_io"
      }
    ],
    "designOperation": "encode_objective_function_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-objective/src/objective_function_v1.rs",
        "symbol": "decode_objective_function_v1",
        "role": "source_declaration"
      }
    ],
    "sourcePathExists": true,
    "sourceBlob": "9a04b17f4b18ed352bdb285f0334b00755e6866e"
  },
  {
    "operation": "admit_objective_v1",
    "nativeSymbol": "codex_hepta_objective::admit_objective_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_admission.rs",
    "inputs": [
      "ObjectiveSourceEnvelopeV1",
      "ObjectiveAdmissionProfileV1",
      "ObjectiveAdmissionContextV1"
    ],
    "outputs": [
      "opaque AdmittedObjectiveV1"
    ],
    "state": "source_implemented_canonical_product_admission",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "two_phase_admission_matches_convenience_wrapper"
      }
    ],
    "designOperation": "admit_objective_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "87f72baa003556720db120827442a838b391cd3f"
  },
  {
    "operation": "compile_admitted_objective_v1",
    "nativeSymbol": "codex_hepta_objective::compile_admitted_objective_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_admission.rs",
    "inputs": [
      "opaque AdmittedObjectiveV1"
    ],
    "outputs": [
      "ObjectiveAdmissionOutcomeV1"
    ],
    "state": "source_implemented_canonical_product_compile",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
        "symbol": "two_phase_admission_matches_convenience_wrapper"
      }
    ],
    "designOperation": "compile_admitted_objective_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-objective/src/compiler.rs",
        "symbol": "crate::compiler::compile",
        "role": "source_declaration"
      }
    ],
    "sourcePathExists": true,
    "sourceBlob": "87f72baa003556720db120827442a838b391cd3f"
  },
  {
    "operation": "decode_objective_function_v1",
    "nativeSymbol": "codex_hepta_objective::decode_objective_function_v1",
    "sourcePath": "codex-rs/hepta-objective/src/objective_function_v1.rs",
    "inputs": [
      "bounded canonical ObjectiveFunctionV1 JSON bytes"
    ],
    "outputs": [
      "DecodedObjectiveFunctionV1",
      "ObjectiveFunctionV1 protocol digest"
    ],
    "state": "source_implemented_canonical_protocol_validation",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-intelligence/src/objective_run_tests.rs",
        "symbol": "authenticated_objective_is_durable_before_product_receipt_returns"
      }
    ],
    "designOperation": "decode_objective_function_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "9a04b17f4b18ed352bdb285f0334b00755e6866e"
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Obtain successful exact-head and deterministic synthetic-merge workflow receipts for one final canonical candidate checkout.",
  "Run the named target-host objective measurement harness and qualify Agentd crash/restart/backpressure behavior on the selected deployment host."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 15. utility.ndu

固定来源：[utility.ndu](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/utility.ndu/IMPLEMENTATION_MAP.json)。Map Git blob：`b5ebc37366f011aff003d24253a8c44f1ed55a90`。

owner：` intelligence-platform `；productCallerState：` request_local_read_only_established_authenticated_owner_source_candidate_not_product_composed `；productionWriterState：` durable_writer_source_candidate_not_selected_or_activated `。

### 操作导航（12 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` evaluate_candidates ` | ` evaluate_candidates ` | ` codex_hepta_ndu::evaluate_candidates ` | ` codex-rs/hepta-ndu/src/evaluator.rs ` | ` owner_native ` |
| ` evaluate_candidates_with_policy ` | ` evaluate_candidates_with_policy ` | ` codex_hepta_ndu::evaluate_candidates_with_policy ` | ` codex-rs/hepta-ndu/src/evaluator.rs ` | ` owner_native ` |
| ` canonical_evaluation_policy_digest ` | ` canonical_evaluation_policy_digest ` | ` codex_hepta_ndu::canonical_evaluation_policy_digest ` | ` codex-rs/hepta-ndu/src/evaluator.rs ` | ` owner_native ` |
| ` solve_preference_target ` | ` solve_preference_target ` | ` codex_hepta_ndu::solve_preference_target ` | ` codex-rs/hepta-ndu/src/preference.rs ` | ` owner_native ` |
| ` bind_solver_iteration_receipt_v1 ` | ` bind_solver_iteration_receipt_v1 ` | ` codex_hepta_ndu::bind_solver_iteration_receipt_v1 ` | ` codex-rs/hepta-ndu/src/protocol.rs ` | ` owner_native ` |
| ` solve_backward_regression ` | ` solve_backward_regression ` | ` codex_hepta_ndu::solve_backward_regression ` | ` codex-rs/hepta-ndu/src/covariance.rs ` | ` owner_native ` |
| ` convert_z_to_original_q24 ` | ` convert_z_to_original_q24 ` | ` codex_hepta_ndu::convert_z_to_original_q24 ` | ` codex-rs/hepta-ndu/src/z_conversion.rs ` | ` owner_native ` |
| ` NduProjectionJournalV1 ` | ` NduProjectionJournalV1 ` | ` codex_hepta_ndu::NduProjectionJournalV1 ` | ` codex-rs/hepta-ndu/src/projection_journal.rs ` | ` owner_native ` |
| ` NduProjectionStoreV1 ` | ` NduProjectionStoreV1 ` | ` codex_hepta_ndu::NduProjectionStoreV1 ` | ` codex-rs/hepta-ndu/src/projection_store.rs ` | ` owner_native ` |
| ` admit_ndu_coefficient_profile ` | ` admit_ndu_coefficient_profile ` | ` codex_hepta_ndu::admit_ndu_coefficient_profile ` | ` codex-rs/hepta-ndu/src/coefficient_profile.rs ` | ` owner_native ` |
| ` project_z_estimate_to_coefficient_q24 ` | ` project_z_estimate_to_coefficient_q24 ` | ` codex_hepta_ndu::project_z_estimate_to_coefficient_q24 ` | ` codex-rs/hepta-ndu/src/coefficient_profile.rs ` | ` owner_native ` |
| ` NduAuthenticatedOwnerV1 ` | ` NduAuthenticatedOwnerV1 ` | ` codex_hepta_ndu::NduAuthenticatedOwnerV1 ` | ` codex-rs/hepta-ndu/src/owner.rs ` | ` owner_native ` |

### operations 原文（12 项）

```json
[
  {
    "operation": "evaluate_candidates",
    "nativeSymbol": "codex_hepta_ndu::evaluate_candidates",
    "sourcePath": "codex-rs/hepta-ndu/src/evaluator.rs",
    "inputs": [
      "ContributionSet",
      "UtilityProfile",
      "optional ScalarizationProfile"
    ],
    "outputs": [
      "NduEvaluationReceipt"
    ],
    "state": "source_implemented_compatibility_entry",
    "authority": "none",
    "semanticProfile": "legacy-sum-max-zero-tolerance-v1",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "hard_violation_is_filtered_before_utility"
      },
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "non_dominated_candidates_without_scalarization_require_slow_path"
      }
    ],
    "designOperation": "evaluate_candidates",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "072b84f7abd0cd4276092b0afd24af22a49f4032"
  },
  {
    "operation": "evaluate_candidates_with_policy",
    "nativeSymbol": "codex_hepta_ndu::evaluate_candidates_with_policy",
    "sourcePath": "codex-rs/hepta-ndu/src/evaluator.rs",
    "inputs": [
      "ContributionSet",
      "UtilityProfile",
      "optional ScalarizationProfile",
      "EvaluationPolicyV1"
    ],
    "outputs": [
      "NduEvaluationReceiptV2"
    ],
    "state": "source_implemented_owner_local_v2",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "policy_selects_axis_specific_aggregation_instead_of_implicit_sum"
      },
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "require_equal_aggregation_rejects_conflicting_owners"
      },
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "pareto_tolerance_is_digest_bound_and_changes_dominance"
      },
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "missing_uncertainty_axis_is_unavailable"
      },
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "candidate_support_digest_binds_organ_and_contribution_semantics"
      }
    ],
    "designOperation": "evaluate_candidates_with_policy",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "072b84f7abd0cd4276092b0afd24af22a49f4032"
  },
  {
    "operation": "canonical_evaluation_policy_digest",
    "nativeSymbol": "codex_hepta_ndu::canonical_evaluation_policy_digest",
    "sourcePath": "codex-rs/hepta-ndu/src/evaluator.rs",
    "inputs": [
      "UtilityProfile",
      "EvaluationPolicyV1"
    ],
    "outputs": [
      "evaluation policy digest"
    ],
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/evaluator_tests.rs",
        "symbol": "policy_digest_is_permutation_invariant"
      }
    ],
    "designOperation": "canonical_evaluation_policy_digest",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "072b84f7abd0cd4276092b0afd24af22a49f4032"
  },
  {
    "operation": "solve_preference_target",
    "nativeSymbol": "codex_hepta_ndu::solve_preference_target",
    "sourcePath": "codex-rs/hepta-ndu/src/preference.rs",
    "inputs": [
      "PreferenceState",
      "target AxisValue set",
      "eta"
    ],
    "outputs": [
      "PreferenceState",
      "NduSolverTerminationReceipt",
      "NduSolverIterationReceipt list"
    ],
    "state": "source_implemented_local_solver",
    "authority": "none",
    "nonClaim": "local termination is not NduConvergenceCertificateV1; iteration exhaustion is unavailable",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "damped_preference_update_emits_local_solver_receipts"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "already_converged_solve_is_revision_stable_no_op"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "preference_dimension_and_value_bounds_fail_at_boundary"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "iteration_exhaustion_is_unavailable"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "parent_and_child_updates_cannot_share_generation"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "unrelated_hierarchy_updates_can_share_generation"
      }
    ],
    "designOperation": "solve_preference_target",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "e26a97ba4b9063bc85e5daa491a917b7fcc608b2"
  },
  {
    "operation": "bind_solver_iteration_receipt_v1",
    "nativeSymbol": "codex_hepta_ndu::bind_solver_iteration_receipt_v1",
    "sourcePath": "codex-rs/hepta-ndu/src/protocol.rs",
    "inputs": [
      "NduIterationContextV1",
      "NduSolverIterationReceipt"
    ],
    "outputs": [
      "owner-local NduIterationReceiptV1"
    ],
    "state": "source_implemented_protocol_adapter",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/protocol_tests.rs",
        "symbol": "local_step_requires_complete_context_before_protocol_publication"
      },
      {
        "path": "codex-rs/hepta-ndu/src/protocol_tests.rs",
        "symbol": "zero_context_digest_rejects_before_protocol_publication"
      },
      {
        "path": "codex-rs/hepta-ndu/src/preference_tests.rs",
        "symbol": "impossible_local_receipt_invariants_are_rejected"
      }
    ],
    "designOperation": "bind_solver_iteration_receipt_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "6740841eebb1c4a540971989cf1e6dcf0db3deb6"
  },
  {
    "operation": "solve_backward_regression",
    "nativeSymbol": "codex_hepta_ndu::solve_backward_regression",
    "sourcePath": "codex-rs/hepta-ndu/src/covariance.rs",
    "inputs": [
      "conditional moments",
      "admitted covariance profile"
    ],
    "outputs": [
      "ZEstimateV1"
    ],
    "state": "source_implemented_shadow_numeric_kernel",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/covariance_tests.rs",
        "symbol": "scaled, correlated, singular and covariance analytic fixtures"
      }
    ],
    "designOperation": "solve_backward_regression",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "985df3333fc8b7664ac867c53a9f7111e6dd999f"
  },
  {
    "operation": "convert_z_to_original_q24",
    "nativeSymbol": "codex_hepta_ndu::convert_z_to_original_q24",
    "sourcePath": "codex-rs/hepta-ndu/src/z_conversion.rs",
    "inputs": [
      "Z head values",
      "source digest",
      "admitted coordinate/Q24 profile"
    ],
    "outputs": [
      "ZQ24ConversionReceiptV1"
    ],
    "state": "source_implemented_shadow_conversion_admission",
    "authority": "deny_all",
    "nonClaim": "coordinate and Q24 conversion evidence is not coefficient provenance, conditional identification, learned FBSDE qualification or production selection",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion_tests.rs",
        "symbol": "original_coordinates_quantize_q24_with_nearest_ties_even"
      },
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion_tests.rs",
        "symbol": "whitened_head_is_converted_back_to_original_increment_coordinates"
      },
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion_tests.rs",
        "symbol": "profile_admission_rejects_ambiguous_or_singular_coordinate_conventions"
      },
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion_tests.rs",
        "symbol": "conversion_rejects_wrong_shape_nonfinite_bound_and_missing_source_identity"
      },
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion_tests.rs",
        "symbol": "coordinate_profile_digest_binds_transform_and_convention"
      }
    ],
    "designOperation": "convert_z_to_original_q24",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "91e51909b9231686e8218e1f5564c3025859418b"
  },
  {
    "operation": "NduProjectionJournalV1",
    "nativeSymbol": "codex_hepta_ndu::NduProjectionJournalV1",
    "sourcePath": "codex-rs/hepta-ndu/src/projection_journal.rs",
    "inputs": [
      "immutable projection, selection and revocation records"
    ],
    "outputs": [
      "bounded hash-chain journal bytes",
      "selected projection view"
    ],
    "state": "source_implemented_owner_local_durability_reference",
    "authority": "none",
    "nonClaim": "semantic journal is not by itself an activated production writer",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "projection_journal_round_trips_and_restores_selection"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "revocation_prevents_projection_resurrection"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "revocation_is_scoped_to_objective_and_subject"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "live_selection_and_revocation_require_a_recorded_projection"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "reopen_rejects_well_hashed_selection_without_projection"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "reopen_rejects_well_hashed_revocation_without_projection"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_journal_tests.rs",
        "symbol": "truncation_and_tampering_fail_closed"
      }
    ],
    "designOperation": "NduProjectionJournalV1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "3cc7db74bac5014b1ed5a8c50c4e8da7f98bc75f"
  },
  {
    "operation": "NduProjectionStoreV1",
    "nativeSymbol": "codex_hepta_ndu::NduProjectionStoreV1",
    "sourcePath": "codex-rs/hepta-ndu/src/projection_store.rs",
    "inputs": [
      "host-authorized private local directory",
      "projection mutations",
      "validated backup image"
    ],
    "outputs": [
      "synchronized projection journal image",
      "selected projection view",
      "validated backup image"
    ],
    "state": "source_implemented_durable_writer_candidate",
    "authority": "none",
    "nonClaim": "durable writer source candidate with injectable write/file-sync/rename/directory-sync crash cuts; not selected or production-activated",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "durable_writer_round_trips_selected_and_revoked_state"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "backup_restore_is_validated_before_replacing_live_state"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "older_valid_backup_cannot_remove_a_later_revocation"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "stale_uncommitted_temp_image_is_discarded_before_recovery"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "concurrent_writer_is_rejected_while_owner_lock_is_live"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store_tests.rs",
        "symbol": "persistence_failpoints_reconcile_at_real_durability_boundaries"
      }
    ],
    "designOperation": "NduProjectionStoreV1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "4fb64e91b45e3653b77a59f6f5ed3e2650929b0e"
  },
  {
    "operation": "admit_ndu_coefficient_profile",
    "nativeSymbol": "codex_hepta_ndu::admit_ndu_coefficient_profile",
    "sourcePath": "codex-rs/hepta-ndu/src/coefficient_profile.rs",
    "inputs": [
      "NduCoefficientProfileV1",
      "AdmittedCovarianceProfileV1",
      "AdmittedZConversionProfileV1"
    ],
    "outputs": [
      "AdmittedNduCoefficientProfileV1"
    ],
    "state": "source_implemented_stochastic_provenance_profile",
    "authority": "deny_all",
    "nonClaim": "artifact manifest binding and numeric compatibility are source admission, not artifact selection, currentness, efficacy or activation",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/coefficient_profile_tests.rs",
        "symbol": "coefficient_profile_binds_covariance_conversion_units_and_dimensions"
      }
    ],
    "designOperation": "admit_ndu_coefficient_profile",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true,
    "sourceBlob": "6643f52aee0c689142323d967f976b76395c7c8b"
  },
  {
    "operation": "project_z_estimate_to_coefficient_q24",
    "nativeSymbol": "codex_hepta_ndu::project_z_estimate_to_coefficient_q24",
    "sourcePath": "codex-rs/hepta-ndu/src/coefficient_profile.rs",
    "inputs": [
      "ZEstimateV1",
      "AdmittedNduCoefficientProfileV1",
      "AdmittedZConversionProfileV1",
      "now_unix_ms"
    ],
    "outputs": [
      "NduCoefficientProjectionV1"
    ],
    "state": "source_implemented_stochastic_projection_chain",
    "authority": "deny_all",
    "nonClaim": "requires exact covariance provenance and admitted conversion profile; does not establish current artifact eligibility or independent convergence",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/coefficient_profile_tests.rs",
        "symbol": "q24_projection_requires_exact_covariance_provenance"
      },
      {
        "path": "codex-rs/hepta-ndu/src/coefficient_profile_tests.rs",
        "symbol": "expired_coefficient_profile_rejects_projection"
      }
    ],
    "designOperation": "project_z_estimate_to_coefficient_q24",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-ndu/src/z_conversion.rs",
        "symbol": "convert_z_to_original_q24",
        "role": "source_declaration"
      }
    ],
    "sourcePathExists": true,
    "sourceBlob": "6643f52aee0c689142323d967f976b76395c7c8b"
  },
  {
    "operation": "NduAuthenticatedOwnerV1",
    "nativeSymbol": "codex_hepta_ndu::NduAuthenticatedOwnerV1",
    "sourcePath": "codex-rs/hepta-ndu/src/owner.rs",
    "inputs": [
      "FinalUseAuthority",
      "NduOwnerContextV1 principal/owner/host generation/fence/revocation frontier",
      "frozen NduProductionPolicyV1",
      "NduProjectionStoreV1"
    ],
    "outputs": [
      "authenticated owner-local evaluation",
      "final-use-bound durable projection mutations"
    ],
    "state": "source_implemented_authenticated_owner_candidate_not_product_activated",
    "authority": "consumes_external_final_use_only",
    "nonClaim": "utility.ndu never mints authority; named product bootstrap, selected writer enrollment and target-host activation remain external",
    "tests": [
      {
        "path": "codex-rs/hepta-ndu/src/owner_tests.rs",
        "symbol": "owner_freezes_policy_and_evaluates_without_caller_supplied_relaxations"
      },
      {
        "path": "codex-rs/hepta-ndu/src/owner_tests.rs",
        "symbol": "exact_signed_binding_is_required_for_durable_mutation"
      },
      {
        "path": "codex-rs/hepta-ndu/src/owner_tests.rs",
        "symbol": "live_revocation_frontier_blocks_previously_signed_write"
      }
    ],
    "designOperation": "NduAuthenticatedOwnerV1",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-contracts/src/final_use.rs",
        "symbol": "FinalUseAuthority::claim",
        "role": "source_declaration"
      },
      {
        "path": "codex-rs/hepta-contracts/src/final_use.rs",
        "symbol": "FinalUseAuthority::with_verified_use",
        "role": "source_declaration"
      },
      {
        "path": "codex-rs/hepta-ndu/src/projection_store.rs",
        "symbol": "NduProjectionStoreV1",
        "role": "source_declaration"
      }
    ],
    "sourcePathExists": true,
    "sourceBlob": "b178fa45920c465d038d57569c4f6556a2dabc84"
  }
]
```

### repositoryControlledGaps 原文（5 项）

```json
[
  "Run the exact-current-head and deterministic synthetic-merge NDU workflow after the final documentation/source commit; workflow definitions and earlier heads are not receipts.",
  "Compose NduAuthenticatedOwnerV1 in a named authenticated product bootstrap with a selected NduProjectionStoreV1 and host-managed current fence/revocation feed before changing authenticated production product execution or writer activation claims.",
  "Execute the learning.eval signed convergence and well-posedness paths with real independently controlled producer/evaluator trust and retained evidence; source tests do not establish real independent acceptance.",
  "Select a production stochastic coefficient artifact and exercise the intelligence stochastic admission path against real current artifact and withdrawal frontiers; source composition is not artifact selection or activation.",
  "Retain passing named-host source-head and synthetic-merge receipts for durability/reopen/capacity/p50/p95/p99/CPU/RSS/filesystem; a GitHub-hosted runner is only the selected target host if separately designated."
]
```

### externalEvidenceGates 原文（5 项）

```json
[
  "independent semantic/security review",
  "named product composition and selected writer enrollment",
  "real independent convergence/well-posedness evidence",
  "conditional identification and longitudinal efficacy",
  "operator acceptance, canary, promotion and release"
]
```

## 16. neuron.runtime

固定来源：[neuron.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/neuron.runtime/IMPLEMENTATION_MAP.json)。Map Git blob：`cdbd8fbf04c20713b1a856ad03c0f295c491a21d`。

owner：` learning-platform `；productCallerState：` agentd_owner_source_compiled_not_daemon_lifecycle_composed `；productionWriterState：` durable_v1_owner_external_witness_source_implemented_not_activated `。

### 操作导航（9 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` neuron_runtime_tick ` | ` neuron_runtime_tick ` | ` NeuronRuntime::tick ` | ` codex-rs/hepta-neuron/src/runtime.rs ` | ` owner_native ` |
| ` inference_control_model_port ` | ` inference_control_model_port ` | ` InferenceControlModelPort ` | ` codex-rs/hepta-neuron/src/inference_control.rs ` | ` owner_native ` |
| ` sparse_journal ` | ` sparse_journal ` | ` SparseJournal ` | ` codex-rs/hepta-neuron/src/journal.rs ` | ` owner_native ` |
| ` anchor_witness_store ` | ` anchor_witness_store ` | ` FileAnchorWitnessStore ` | ` codex-rs/hepta-neuron/src/witness.rs ` | ` owner_native ` |
| ` plasticity_statistics ` | ` plasticity_statistics ` | ` accumulate_plasticity ` | ` codex-rs/hepta-neuron/src/plasticity.rs ` | ` owner_native ` |
| ` deletion_rebuild_admission ` | ` deletion_rebuild_admission ` | ` validate_deletion_rebuild ` | ` codex-rs/hepta-neuron/src/deletion.rs ` | ` owner_native ` |
| ` qualification_surfaces ` | ` qualification_surfaces ` | ` summarize_resource_samples ` | ` codex-rs/hepta-neuron/src/qualification.rs ` | ` owner_native ` |
| ` canonical_neuron_protocols ` | ` canonical_neuron_protocols ` | ` canonical_runtime_config_v1 / canonical_tick_receipt_v1 / canonical_checkpoint_v1 ` | ` codex-rs/hepta-neuron/src/protocol.rs ` | ` owner_native ` |
| ` population_sparse_v2 ` | ` population_sparse_v2 ` | ` population_sparse_tick_v2 ` | ` codex-rs/hepta-neuron/src/population_v2.rs ` | ` owner_native ` |

### operations 原文（9 项）

```json
[
  {
    "operation": "neuron_runtime_tick",
    "nativeSymbol": "NeuronRuntime::tick",
    "sourcePath": "codex-rs/hepta-neuron/src/runtime.rs",
    "state": "source_implemented_owner_not_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/runtime_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "neuron_runtime_tick",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-neuron/src/inference_control.rs",
        "symbol": "InferenceControlModelPort",
        "role": "source_declaration"
      },
      {
        "path": "codex-rs/hepta-neuron/src/journal.rs",
        "symbol": "SparseJournal",
        "role": "source_declaration"
      },
      {
        "path": "codex-rs/hepta-neuron/src/runtime_types.rs",
        "symbol": "AnchorWitnessStore",
        "role": "source_declaration"
      }
    ]
  },
  {
    "operation": "inference_control_model_port",
    "nativeSymbol": "InferenceControlModelPort",
    "sourcePath": "codex-rs/hepta-neuron/src/inference_control.rs",
    "state": "source_implemented_authenticated_owner_adapter",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/inference_control_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "inference_control_model_port",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-infer-core/src/neuron_feature.rs",
        "symbol": "inference.control::NeuronFeatureReceiptV1",
        "role": "source_declaration"
      }
    ]
  },
  {
    "operation": "sparse_journal",
    "nativeSymbol": "SparseJournal",
    "sourcePath": "codex-rs/hepta-neuron/src/journal.rs",
    "state": "source_implemented_durable_owner_primitive",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/journal_anchor_tests.rs",
      "codex-rs/hepta-neuron/src/journal_segment_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "sparse_journal",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "anchor_witness_store",
    "nativeSymbol": "FileAnchorWitnessStore",
    "sourcePath": "codex-rs/hepta-neuron/src/witness.rs",
    "state": "source_implemented_durable_external_witness",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/witness_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "anchor_witness_store",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "plasticity_statistics",
    "nativeSymbol": "accumulate_plasticity",
    "sourcePath": "codex-rs/hepta-neuron/src/plasticity.rs",
    "state": "source_implemented_next_snapshot_statistics_only",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/plasticity_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "plasticity_statistics",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "deletion_rebuild_admission",
    "nativeSymbol": "validate_deletion_rebuild",
    "sourcePath": "codex-rs/hepta-neuron/src/deletion.rs",
    "state": "source_implemented_fail_closed_rebuild_admission",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/deletion_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "deletion_rebuild_admission",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "qualification_surfaces",
    "nativeSymbol": "summarize_resource_samples",
    "sourcePath": "codex-rs/hepta-neuron/src/qualification.rs",
    "state": "source_implemented_evidence_binding_not_empirical_acceptance",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/qualification_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "qualification_surfaces",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "canonical_neuron_protocols",
    "nativeSymbol": "canonical_runtime_config_v1 / canonical_tick_receipt_v1 / canonical_checkpoint_v1",
    "sourcePath": "codex-rs/hepta-neuron/src/protocol.rs",
    "state": "source_implemented_registered_json_projection_not_activation",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/protocol_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_neuron_protocols",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "population_sparse_v2",
    "nativeSymbol": "population_sparse_tick_v2",
    "sourcePath": "codex-rs/hepta-neuron/src/population_v2.rs",
    "state": "source_implemented_pure_versioned_mechanism_not_durable_activated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-neuron/src/population_v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "population_sparse_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（4 项）

```json
[
  "Stack/rebase the compiled AgentdNeuronOwner onto the daemon-owned runtime.agentd run lifecycle and bind a concrete current inference.control feature port plus selected-artifact/witness lifecycle; a compiled owner boundary is not daemon activation.",
  "If PopulationSparseConfigV2 is promoted beyond qualification, implement a separately versioned durable journal/owner migration and recovery path; never reinterpret V1 journal bytes as V2 state.",
  "Run current exact-head, deterministic synthetic-merge and product-host qualification before changing productionImplementation or productExecutionProved.",
  "Execute unified-candidate rollover/anchor, learned feature host and lost-witness-ack reconciliation tests."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "target-host product execution with authenticated selected model/runtime/device evidence",
  "measured calibration/OOD/resource acceptance plus future-window ablation, retention and deletion non-resurrection evidence",
  "independent semantic/operator acceptance, canary, promotion and release"
]
```

## 17. intuition.policy

固定来源：[intuition.policy](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/intuition.policy/IMPLEMENTATION_MAP.json)。Map Git blob：`12a89204b51165f6db3e3f6f34f42c20b048ae46`。

owner：` intelligence-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（2 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` decide_calibrated ` | ` decide_calibrated ` | ` decide_calibrated ` | ` codex-rs/hepta-intuition/src/calibrated.rs ` | ` owner_native ` |
| ` decide_calibrated_v2 ` | ` decide_calibrated_v2 ` | ` decide_calibrated_v2 ` | ` codex-rs/hepta-intuition/src/calibrated_binding.rs ` | ` owner_native ` |

### operations 原文（2 项）

```json
[
  {
    "operation": "decide_calibrated",
    "nativeSymbol": "decide_calibrated",
    "sourcePath": "codex-rs/hepta-intuition/src/calibrated.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "decide_calibrated",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "decide_calibrated_v2",
    "nativeSymbol": "decide_calibrated_v2",
    "sourcePath": "codex-rs/hepta-intuition/src/calibrated_binding.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "decide_calibrated_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 18. prompt.registry

固定来源：[prompt.registry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/prompt.registry/IMPLEMENTATION_MAP.json)。Map Git blob：`00c9926a7532e19a82c867ff821b5077da256d2c`。

owner：` intelligence-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` promptregistry ` | ` promptregistry ` | ` PromptRegistry ` | ` codex-rs/hepta-prompt-registry/src/lib.rs ` | ` owner_native ` |
| ` register_realization_v2 ` | ` register_realization_v2 ` | ` register_realization_v2 ` | ` codex-rs/hepta-prompt-registry/src/v2.rs ` | ` owner_native ` |
| ` read_compatible_v2 ` | ` read_compatible_v2 ` | ` read_compatible_v2 ` | ` codex-rs/hepta-prompt-registry/src/v2.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "operation": "promptregistry",
    "nativeSymbol": "PromptRegistry",
    "sourcePath": "codex-rs/hepta-prompt-registry/src/lib.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "promptregistry",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "register_realization_v2",
    "nativeSymbol": "register_realization_v2",
    "sourcePath": "codex-rs/hepta-prompt-registry/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "register_realization_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "read_compatible_v2",
    "nativeSymbol": "read_compatible_v2",
    "sourcePath": "codex-rs/hepta-prompt-registry/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "read_compatible_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 19. prompt.optimizer

固定来源：[prompt.optimizer](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/prompt.optimizer/IMPLEMENTATION_MAP.json)。Map Git blob：`9c6221752bb7dbfd727db16bf2dd4dc9e21f5e1a`。

owner：` intelligence-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（2 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` optimize ` | ` optimize ` | ` optimize ` | ` codex-rs/hepta-prompt-optimizer/src/lib.rs ` | ` owner_native ` |
| ` calculate_local_shadow ` | ` calculate_local_shadow ` | ` calculate_local_shadow ` | ` codex-rs/hepta-prompt-optimizer/src/local_shadow.rs ` | ` owner_native ` |

### operations 原文（2 项）

```json
[
  {
    "operation": "optimize",
    "nativeSymbol": "optimize",
    "sourcePath": "codex-rs/hepta-prompt-optimizer/src/lib.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "optimize",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "calculate_local_shadow",
    "nativeSymbol": "calculate_local_shadow",
    "sourcePath": "codex-rs/hepta-prompt-optimizer/src/local_shadow.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "calculate_local_shadow",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 20. context.compiler

固定来源：[context.compiler](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/context.compiler/IMPLEMENTATION_MAP.json)。Map Git blob：`4d06be9230e0b9b966739bce6769a55d4b992133`。

owner：` intelligence-platform `；productCallerState：` legacy_v1_read_only_source_composed_verified_v2_not_composed `；productionWriterState：` not_established `。

### 操作导航（12 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` compile ` | ` compile ` | ` compile ` | ` codex-rs/hepta-context-compiler/src/lib.rs ` | ` owner_native ` |
| ` compile_with_requirements ` | ` compile_with_requirements ` | ` compile_with_requirements ` | ` codex-rs/hepta-context-compiler/src/requirements.rs ` | ` owner_native ` |
| ` compile_candidate_bound ` | ` compile_candidate_bound ` | ` compile_candidate_bound ` | ` codex-rs/hepta-context-compiler/src/candidate_bound.rs ` | ` owner_native ` |
| ` verify_admission_snapshot_v2 ` | ` revalidate_attachment ` | ` verify_admission_snapshot_v2 ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` verify_admission_snapshot_successor_v2 ` | ` revalidate_attachment ` | ` verify_admission_snapshot_successor_v2 ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` verify_admission_v2 ` | ` compile_context ` | ` verify_admission_v2 ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` compile_v2 ` | ` compile_context ` | ` compile_v2 ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` record_serialization ` | ` compile_context ` | ` record_serialization ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` build_attachment ` | ` revalidate_attachment ` | ` build_attachment ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` prepare_delivery_v2 ` | ` revalidate_attachment ` | ` prepare_delivery_v2 ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` observe_delivery ` | ` compile_context ` | ` observe_delivery ` | ` codex-rs/hepta-context-compiler/src/v2.rs ` | ` owner_native ` |
| ` wire_v2_compatibility_receipt ` | ` compile_context ` | ` encode_compilation_receipt_wire_v2 ` | ` codex-rs/hepta-context-compiler/src/wire.rs ` | ` owner_native ` |

### operations 原文（12 项）

```json
[
  {
    "operation": "compile",
    "nativeSymbol": "compile",
    "sourcePath": "codex-rs/hepta-context-compiler/src/lib.rs",
    "state": "legacy_compatibility_source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/lib_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "da1711e6575e0921ec4d2ae7b305fe8013f2e775"
  },
  {
    "operation": "compile_with_requirements",
    "nativeSymbol": "compile_with_requirements",
    "sourcePath": "codex-rs/hepta-context-compiler/src/requirements.rs",
    "state": "legacy_compatibility_source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/requirements_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_with_requirements",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "33f723317f83feec2b6e8be8c45d058f58288a7e"
  },
  {
    "operation": "compile_candidate_bound",
    "nativeSymbol": "compile_candidate_bound",
    "sourcePath": "codex-rs/hepta-context-compiler/src/candidate_bound.rs",
    "state": "legacy_compatibility_source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_candidate_bound",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "52efe73b0da51c5cbb054e8cdcfe3e59e4b08ba6"
  },
  {
    "operation": "verify_admission_snapshot_v2",
    "nativeSymbol": "verify_admission_snapshot_v2",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "revalidate_attachment",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "verify_admission_snapshot_successor_v2",
    "nativeSymbol": "verify_admission_snapshot_successor_v2",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "revalidate_attachment",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "verify_admission_v2",
    "nativeSymbol": "verify_admission_v2",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_context",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "compile_v2",
    "nativeSymbol": "compile_v2",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_context",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "record_serialization",
    "nativeSymbol": "record_serialization",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_context",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "build_attachment",
    "nativeSymbol": "build_attachment",
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "revalidate_attachment",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "operation": "prepare_delivery_v2",
    "nativeSymbol": "prepare_delivery_v2",
    "designOperation": "revalidate_attachment",
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "sourcePath": "codex-rs/hepta-context-compiler/src/v2.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "operation": "observe_delivery",
    "nativeSymbol": "observe_delivery",
    "designOperation": "compile_context",
    "sourceBlob": "d6be3d4b86ef261157af101c6629bcee8ecf1311"
  },
  {
    "operation": "wire_v2_compatibility_receipt",
    "nativeSymbol": "encode_compilation_receipt_wire_v2",
    "sourcePath": "codex-rs/hepta-context-compiler/src/wire.rs",
    "state": "legacy_v1_semantics_transport_boundary_canonical_producer_enforced",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-context-compiler/src/wire_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_context",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "6e0583a81b064eec7ceb0b785bc9a48bd801a2f1"
  }
]
```

### repositoryControlledGaps 原文（4 项）

```json
[
  "Compose the verified V2 operations into one authenticated named product caller with the authoritative admission verifier, exact tokenizer/serializer/template/tool-schema profile, and runtime provider owner.",
  "At the real provider boundary consume current final-use authority in the same effect-bound ceremony that binds ContextDeliveryPreparationV2 to the exact serialized payload and canonical ProviderRequestBinding before physical send.",
  "Persist and independently resolve provider attempt/terminal evidence, then exercise revoke race, adapter death, provider indeterminate, process death and retry reconciliation without converting uncertainty into success.",
  "Run exact-head, deterministic synthetic-merge, capacity and target-host qualification before changing productExecutionProved, activation or release."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 21. intelligence.control

固定来源：[intelligence.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/intelligence.control/IMPLEMENTATION_MAP.json)。Map Git blob：`721fc5d5e037981f388ae98c47e551769a32d88e`。

owner：` intelligence-platform `；productCallerState：` named_agentd_runner_present_daemon_route_not_composed `；productionWriterState：` none_by_design_composition_facade `。

### 操作导航（35 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` build_legal_candidates ` | ` build_legal_candidates ` | ` build_legal_candidates ` | ` codex-rs/hepta-intelligence/src/canonical.rs ` | ` owner_native ` |
| ` prepare_intelligence_run ` | ` prepare_intelligence_run ` | ` prepare_intelligence_run ` | ` codex-rs/hepta-intelligence/src/canonical.rs ` | ` owner_native ` |
| ` decide_boundary ` | ` decide_boundary ` | ` decide_boundary ` | ` codex-rs/hepta-intelligence/src/canonical.rs ` | ` owner_native ` |
| ` assemble_context ` | ` assemble_context ` | ` assemble_context ` | ` codex-rs/hepta-intelligence/src/canonical.rs ` | ` owner_native ` |
| ` validate_current_snapshot ` | ` validate_current_snapshot ` | ` validate_current_snapshot ` | ` codex-rs/hepta-intelligence/src/canonical.rs ` | ` owner_native ` |
| ` compose ` | ` compose ` | ` compose ` | ` codex-rs/hepta-intelligence/src/lib.rs ` | ` owner_native ` |
| ` run_read_only_vertical ` | ` run_read_only_vertical ` | ` run_read_only_vertical ` | ` codex-rs/hepta-intelligence/src/vertical.rs ` | ` owner_native ` |
| ` evaluated_candidate_signing_payload_v1 ` | ` evaluated_candidate_signing_payload_v1 ` | ` evaluated_candidate_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/evaluated_shadow.rs ` | ` owner_native ` |
| ` run_evaluated_shadow_v1 ` | ` run_evaluated_shadow_v1 ` | ` run_evaluated_shadow_v1 ` | ` codex-rs/hepta-intelligence/src/evaluated_shadow.rs ` | ` owner_native ` |
| ` run_shadow_pipeline ` | ` run_shadow_pipeline ` | ` run_shadow_pipeline ` | ` codex-rs/hepta-intelligence/src/pipeline.rs ` | ` owner_native ` |
| ` run_shadow_pipeline_v2 ` | ` run_shadow_pipeline_v2 ` | ` run_shadow_pipeline_v2 ` | ` codex-rs/hepta-intelligence/src/pipeline_v2.rs ` | ` owner_native ` |
| ` admit_ndu_stochastic_candidate_v1 ` | ` admit_ndu_stochastic_candidate_v1 ` | ` admit_ndu_stochastic_candidate_v1 ` | ` codex-rs/hepta-intelligence/src/ndu_stochastic_admission.rs ` | ` owner_native ` |
| ` append_observed_outcome_v2 ` | ` append_observed_outcome_v2 ` | ` append_observed_outcome_v2 ` | ` codex-rs/hepta-intelligence/src/outcome_credit_v2.rs ` | ` owner_native ` |
| ` append_outcome_credit_v2 ` | ` append_outcome_credit_v2 ` | ` append_outcome_credit_v2 ` | ` codex-rs/hepta-intelligence/src/outcome_credit_v2.rs ` | ` owner_native ` |
| ` canonical_ndu_stochastic_solver_digest_v1 ` | ` canonical_ndu_stochastic_solver_digest_v1 ` | ` canonical_ndu_stochastic_solver_digest_v1 ` | ` codex-rs/hepta-intelligence/src/ndu_stochastic_admission.rs ` | ` owner_native ` |
| ` compile_and_publish_objective_run_v1 ` | ` compile_and_publish_objective_run_v1 ` | ` compile_and_publish_objective_run_v1 ` | ` codex-rs/hepta-intelligence/src/objective_run.rs ` | ` owner_native ` |
| ` compile_exercised_prompt_context_v1 ` | ` compile_exercised_prompt_context_v1 ` | ` compile_exercised_prompt_context_v1 ` | ` codex-rs/hepta-intelligence/src/prompt_pipeline.rs ` | ` owner_native ` |
| ` compile_prompt_registry_v2 ` | ` compile_prompt_registry_v2 ` | ` compile_prompt_registry_v2 ` | ` codex-rs/hepta-intelligence/src/prompt_delivery.rs ` | ` owner_native ` |
| ` decide_authenticated_intuition_v1 ` | ` decide_authenticated_intuition_v1 ` | ` decide_authenticated_intuition_v1 ` | ` codex-rs/hepta-intelligence/src/intuition_qualification.rs ` | ` owner_native ` |
| ` decide_authenticated_intuition_v2 ` | ` decide_authenticated_intuition_v2 ` | ` decide_authenticated_intuition_v2 ` | ` codex-rs/hepta-intelligence/src/intuition_qualification.rs ` | ` owner_native ` |
| ` evaluated_candidate_signing_payload_v2 ` | ` evaluated_candidate_signing_payload_v2 ` | ` evaluated_candidate_signing_payload_v2 ` | ` codex-rs/hepta-intelligence/src/evaluated_shadow.rs ` | ` owner_native ` |
| ` evaluated_shadow_production_decision_v2 ` | ` evaluated_shadow_production_decision_v2 ` | ` evaluated_shadow_production_decision_v2 ` | ` codex-rs/hepta-intelligence/src/evaluated_shadow.rs ` | ` owner_native ` |
| ` no_change_disposition_signing_payload_v1 ` | ` no_change_disposition_signing_payload_v1 ` | ` no_change_disposition_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/plasticity_product.rs ` | ` owner_native ` |
| ` observe_authenticated_structural_canary_v1 ` | ` observe_authenticated_structural_canary_v1 ` | ` observe_authenticated_structural_canary_v1 ` | ` codex-rs/hepta-intelligence/src/topology_canary_product.rs ` | ` owner_native ` |
| ` observe_prompt_delivery_v1 ` | ` observe_prompt_delivery_v1 ` | ` observe_prompt_delivery_v1 ` | ` codex-rs/hepta-intelligence/src/prompt_pipeline.rs ` | ` owner_native ` |
| ` plasticity_admission_signing_payload_v1 ` | ` plasticity_admission_signing_payload_v1 ` | ` plasticity_admission_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/plasticity_product.rs ` | ` owner_native ` |
| ` prepare_prompt_delivery_v1 ` | ` prepare_prompt_delivery_v1 ` | ` prepare_prompt_delivery_v1 ` | ` codex-rs/hepta-intelligence/src/prompt_pipeline.rs ` | ` owner_native ` |
| ` propose_authenticated_parameter_plasticity_v1 ` | ` propose_authenticated_parameter_plasticity_v1 ` | ` propose_authenticated_parameter_plasticity_v1 ` | ` codex-rs/hepta-intelligence/src/plasticity_product.rs ` | ` owner_native ` |
| ` propose_authenticated_topology_plasticity_v1 ` | ` propose_authenticated_topology_plasticity_v1 ` | ` propose_authenticated_topology_plasticity_v1 ` | ` codex-rs/hepta-intelligence/src/topology_product.rs ` | ` owner_native ` |
| ` run_neuron_tick_v1 ` | ` run_neuron_tick_v1 ` | ` run_neuron_tick_v1 ` | ` codex-rs/hepta-intelligence/src/neuron_runtime.rs ` | ` owner_native ` |
| ` run_qualified_evaluated_shadow_v2 ` | ` run_qualified_evaluated_shadow_v2 ` | ` run_qualified_evaluated_shadow_v2 ` | ` codex-rs/hepta-intelligence/src/intuition_qualification.rs ` | ` owner_native ` |
| ` structural_canary_observation_signing_payload_v1 ` | ` structural_canary_observation_signing_payload_v1 ` | ` structural_canary_observation_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/topology_canary_product.rs ` | ` owner_native ` |
| ` topology_admission_signing_payload_v1 ` | ` topology_admission_signing_payload_v1 ` | ` topology_admission_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/topology_product.rs ` | ` owner_native ` |
| ` topology_evaluation_signing_payload_v1 ` | ` topology_evaluation_signing_payload_v1 ` | ` topology_evaluation_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/topology_product.rs ` | ` owner_native ` |
| ` topology_generation_signing_payload_v1 ` | ` topology_generation_signing_payload_v1 ` | ` topology_generation_signing_payload_v1 ` | ` codex-rs/hepta-intelligence/src/topology_product.rs ` | ` owner_native ` |

### operations 原文（35 项）

```json
[
  {
    "operation": "build_legal_candidates",
    "designOperation": "build_legal_candidates",
    "nativeSymbol": "build_legal_candidates",
    "sourcePath": "codex-rs/hepta-intelligence/src/canonical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_named_runner_not_daemon_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/canonical_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "c610f073b47939acf15e7e76aad59883ac13fad4"
  },
  {
    "operation": "prepare_intelligence_run",
    "designOperation": "prepare_intelligence_run",
    "nativeSymbol": "prepare_intelligence_run",
    "sourcePath": "codex-rs/hepta-intelligence/src/canonical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-objective",
        "module": "objective.compiler",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-ndu",
        "module": "utility.ndu",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-neuron",
        "module": "neuron.runtime",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-prompt-optimizer",
        "module": "prompt.optimizer",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intuition",
        "module": "intuition.policy",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-context-compiler",
        "module": "context.compiler",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "state": "source_implemented_named_runner_not_daemon_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/canonical_tests.rs",
      "codex-rs/hepta-agentd/src/intelligence_product_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "c610f073b47939acf15e7e76aad59883ac13fad4"
  },
  {
    "operation": "decide_boundary",
    "designOperation": "decide_boundary",
    "nativeSymbol": "decide_boundary",
    "sourcePath": "codex-rs/hepta-intelligence/src/canonical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_named_runner_not_daemon_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/canonical_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "c610f073b47939acf15e7e76aad59883ac13fad4"
  },
  {
    "operation": "assemble_context",
    "designOperation": "assemble_context",
    "nativeSymbol": "assemble_context",
    "sourcePath": "codex-rs/hepta-intelligence/src/canonical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_named_runner_not_daemon_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/canonical_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "c610f073b47939acf15e7e76aad59883ac13fad4"
  },
  {
    "operation": "validate_current_snapshot",
    "designOperation": "validate_current_snapshot",
    "nativeSymbol": "validate_current_snapshot",
    "sourcePath": "codex-rs/hepta-intelligence/src/canonical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_named_runner_not_daemon_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/canonical_tests.rs",
      "codex-rs/hepta-agentd/src/intelligence_product_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "c610f073b47939acf15e7e76aad59883ac13fad4"
  },
  {
    "operation": "compose",
    "designOperation": "compose",
    "nativeSymbol": "compose",
    "sourcePath": "codex-rs/hepta-intelligence/src/lib.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/lib_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "ac161c19df7b828fbca02d39ebfdb6661982e6d4"
  },
  {
    "operation": "run_read_only_vertical",
    "designOperation": "run_read_only_vertical",
    "nativeSymbol": "run_read_only_vertical",
    "sourcePath": "codex-rs/hepta-intelligence/src/vertical.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/vertical_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "eb89f2f5324d861b7bab680c4c99b03a370402e6"
  },
  {
    "operation": "evaluated_candidate_signing_payload_v1",
    "designOperation": "evaluated_candidate_signing_payload_v1",
    "nativeSymbol": "evaluated_candidate_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "51f32b736c9aa0bc067776b3b4ca9c80a3cb42aa"
  },
  {
    "operation": "run_evaluated_shadow_v1",
    "designOperation": "run_evaluated_shadow_v1",
    "nativeSymbol": "run_evaluated_shadow_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "51f32b736c9aa0bc067776b3b4ca9c80a3cb42aa"
  },
  {
    "operation": "run_shadow_pipeline",
    "designOperation": "run_shadow_pipeline",
    "nativeSymbol": "run_shadow_pipeline",
    "sourcePath": "codex-rs/hepta-intelligence/src/pipeline.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/pipeline_tests.rs",
      "codex-rs/hepta-intelligence/tests/lane_f_shadow_vertical.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "1230d9b7c5ce8882451eb4c04065534e987863c5"
  },
  {
    "operation": "run_shadow_pipeline_v2",
    "designOperation": "run_shadow_pipeline_v2",
    "nativeSymbol": "run_shadow_pipeline_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/pipeline_v2.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "state": "source_implemented_compatibility_not_product_routed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/pipeline_v2_tests.rs"
    ],
    "sourcePathExists": true,
    "sourceBlob": "0dbc20e5eb0dbee8775d8cc2a74577db13bf05b4"
  },
  {
    "operation": "admit_ndu_stochastic_candidate_v1",
    "designOperation": "admit_ndu_stochastic_candidate_v1",
    "nativeSymbol": "admit_ndu_stochastic_candidate_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/ndu_stochastic_admission.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "64ce0c612f4212fa0465177a74036b1cf3667e22"
  },
  {
    "operation": "append_observed_outcome_v2",
    "designOperation": "append_observed_outcome_v2",
    "nativeSymbol": "append_observed_outcome_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/outcome_credit_v2.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "3d21ce3fe1729dc32ac1b7579e72a5056b674788"
  },
  {
    "operation": "append_outcome_credit_v2",
    "designOperation": "append_outcome_credit_v2",
    "nativeSymbol": "append_outcome_credit_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/outcome_credit_v2.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "3d21ce3fe1729dc32ac1b7579e72a5056b674788"
  },
  {
    "operation": "canonical_ndu_stochastic_solver_digest_v1",
    "designOperation": "canonical_ndu_stochastic_solver_digest_v1",
    "nativeSymbol": "canonical_ndu_stochastic_solver_digest_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/ndu_stochastic_admission.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "64ce0c612f4212fa0465177a74036b1cf3667e22"
  },
  {
    "operation": "compile_and_publish_objective_run_v1",
    "designOperation": "compile_and_publish_objective_run_v1",
    "nativeSymbol": "compile_and_publish_objective_run_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/objective_run.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "a2f361edbf1e0f8fd1024d085edcd71b4f2396f0"
  },
  {
    "operation": "compile_exercised_prompt_context_v1",
    "designOperation": "compile_exercised_prompt_context_v1",
    "nativeSymbol": "compile_exercised_prompt_context_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "1e247f40bb8156357cf6d6274891d09e8b88570e"
  },
  {
    "operation": "compile_prompt_registry_v2",
    "designOperation": "compile_prompt_registry_v2",
    "nativeSymbol": "compile_prompt_registry_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "803989e30f19c8f6cce78cde09434925f4f0a522"
  },
  {
    "operation": "decide_authenticated_intuition_v1",
    "designOperation": "decide_authenticated_intuition_v1",
    "nativeSymbol": "decide_authenticated_intuition_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/intuition_qualification.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "8ea881cf551be8e8e0ca7b34d94f6162bead8b47"
  },
  {
    "operation": "decide_authenticated_intuition_v2",
    "designOperation": "decide_authenticated_intuition_v2",
    "nativeSymbol": "decide_authenticated_intuition_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/intuition_qualification.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "8ea881cf551be8e8e0ca7b34d94f6162bead8b47"
  },
  {
    "operation": "evaluated_candidate_signing_payload_v2",
    "designOperation": "evaluated_candidate_signing_payload_v2",
    "nativeSymbol": "evaluated_candidate_signing_payload_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "51f32b736c9aa0bc067776b3b4ca9c80a3cb42aa"
  },
  {
    "operation": "evaluated_shadow_production_decision_v2",
    "designOperation": "evaluated_shadow_production_decision_v2",
    "nativeSymbol": "evaluated_shadow_production_decision_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "51f32b736c9aa0bc067776b3b4ca9c80a3cb42aa"
  },
  {
    "operation": "no_change_disposition_signing_payload_v1",
    "designOperation": "no_change_disposition_signing_payload_v1",
    "nativeSymbol": "no_change_disposition_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "7004ae2981587a63f9941376196af9435dbbdc6d"
  },
  {
    "operation": "observe_authenticated_structural_canary_v1",
    "designOperation": "observe_authenticated_structural_canary_v1",
    "nativeSymbol": "observe_authenticated_structural_canary_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_canary_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "52148b2b9968759782e76963eb16acc0b2e7c34d"
  },
  {
    "operation": "observe_prompt_delivery_v1",
    "designOperation": "observe_prompt_delivery_v1",
    "nativeSymbol": "observe_prompt_delivery_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "1e247f40bb8156357cf6d6274891d09e8b88570e"
  },
  {
    "operation": "plasticity_admission_signing_payload_v1",
    "designOperation": "plasticity_admission_signing_payload_v1",
    "nativeSymbol": "plasticity_admission_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "7004ae2981587a63f9941376196af9435dbbdc6d"
  },
  {
    "operation": "prepare_prompt_delivery_v1",
    "designOperation": "prepare_prompt_delivery_v1",
    "nativeSymbol": "prepare_prompt_delivery_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "1e247f40bb8156357cf6d6274891d09e8b88570e"
  },
  {
    "operation": "propose_authenticated_parameter_plasticity_v1",
    "designOperation": "propose_authenticated_parameter_plasticity_v1",
    "nativeSymbol": "propose_authenticated_parameter_plasticity_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "7004ae2981587a63f9941376196af9435dbbdc6d"
  },
  {
    "operation": "propose_authenticated_topology_plasticity_v1",
    "designOperation": "propose_authenticated_topology_plasticity_v1",
    "nativeSymbol": "propose_authenticated_topology_plasticity_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "e4d71ed863344823e5dcf4522375ad4cf1f1dd38"
  },
  {
    "operation": "run_neuron_tick_v1",
    "designOperation": "run_neuron_tick_v1",
    "nativeSymbol": "run_neuron_tick_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/neuron_runtime.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "1405c0ced8fa858a776ef980e5b76f4fe970a4b3"
  },
  {
    "operation": "run_qualified_evaluated_shadow_v2",
    "designOperation": "run_qualified_evaluated_shadow_v2",
    "nativeSymbol": "run_qualified_evaluated_shadow_v2",
    "sourcePath": "codex-rs/hepta-intelligence/src/intuition_qualification.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "8ea881cf551be8e8e0ca7b34d94f6162bead8b47"
  },
  {
    "operation": "structural_canary_observation_signing_payload_v1",
    "designOperation": "structural_canary_observation_signing_payload_v1",
    "nativeSymbol": "structural_canary_observation_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_canary_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "52148b2b9968759782e76963eb16acc0b2e7c34d"
  },
  {
    "operation": "topology_admission_signing_payload_v1",
    "designOperation": "topology_admission_signing_payload_v1",
    "nativeSymbol": "topology_admission_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "e4d71ed863344823e5dcf4522375ad4cf1f1dd38"
  },
  {
    "operation": "topology_evaluation_signing_payload_v1",
    "designOperation": "topology_evaluation_signing_payload_v1",
    "nativeSymbol": "topology_evaluation_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "e4d71ed863344823e5dcf4522375ad4cf1f1dd38"
  },
  {
    "operation": "topology_generation_signing_payload_v1",
    "designOperation": "topology_generation_signing_payload_v1",
    "nativeSymbol": "topology_generation_signing_payload_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_product.rs",
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "state": "source_navigation_only_product_binding_not_proved",
    "delegatedCallees": [],
    "tests": [],
    "authority": "none",
    "sourceBlob": "e4d71ed863344823e5dcf4522375ad4cf1f1dd38"
  }
]
```

### repositoryControlledGaps 原文（5 项）

```json
[
  "Complete durable product Decision/Outcome append and process-loss reconciliation, then exercise the daemon-prepared binding through the physical App Server caller; the authenticated ObjectiveStart-to-canonical-run route is now source-wired.",
  "Make ambiguous Decision/Outcome append recovery survive Agentd process loss; PendingIntelligenceLedgerAppendV1 is currently only an in-memory replay object.",
  "Obtain current exact-head and deterministic synthetic-merge green receipts for this candidate; prior candidate receipts are provenance only.",
  "Run the real Agentd/App Server intelligence-bound product E2E, including turn/start lost-ack, dependency outage, restart and revocation races.",
  "Qualify target-host hard resource termination; the pure in-process cognition worker discards late results but spawn_blocking cannot terminate a running blocking stage."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic and security review",
  "real-provider and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 22. cognitive.types

固定来源：[cognitive.types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.types/IMPLEMENTATION_MAP.json)。Map Git blob：`a58d2d826998d3fc4a445774529a8f1a9770cc18`。

owner：` cognitive-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（15 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` build_snapshot ` | ` build_snapshot ` | ` build_snapshot ` | ` codex-rs/hepta-cognitive-types/src/lib.rs ` | ` owner_native ` |
| ` cognitivesnapshotkeyv1 ` | ` cognitivesnapshotkeyv1 ` | ` CognitiveSnapshotKeyV1 ` | ` codex-rs/hepta-cognitive-types/src/lane_c.rs ` | ` owner_native ` |
| ` modalityspanrefv1 ` | ` modalityspanrefv1 ` | ` ModalitySpanRefV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf.rs ` | ` owner_native ` |
| ` memoryeventv1 ` | ` memoryeventv1 ` | ` MemoryEventV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf.rs ` | ` owner_native ` |
| ` crossmodalbindingv1 ` | ` crossmodalbindingv1 ` | ` CrossModalBindingV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf.rs ` | ` owner_native ` |
| ` engramnodev1 ` | ` engramnodev1 ` | ` EngramNodeV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` synapsev1 ` | ` synapsev1 ` | ` SynapseV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` memorycuev1 ` | ` memorycuev1 ` | ` MemoryCueV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` recallpacketv1 ` | ` recallpacketv1 ` | ` RecallPacketV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` outcomesignalv1 ` | ` outcomesignalv1 ` | ` OutcomeSignalV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` replayselectionreceiptv1 ` | ` replayselectionreceiptv1 ` | ` ReplaySelectionReceiptV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` plasticitybatchv1 ` | ` plasticitybatchv1 ` | ` PlasticityBatchV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` topologyproposalv1 ` | ` topologyproposalv1 ` | ` TopologyProposalV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` forgetpropagationreceiptv1 ` | ` forgetpropagationreceiptv1 ` | ` ForgetPropagationReceiptV1 ` | ` codex-rs/hepta-cognitive-types/src/hnmf_learning.rs ` | ` owner_native ` |
| ` canonical_wire_v1 ` | ` canonical_wire_v1 ` | ` CognitiveContractV1 ` | ` codex-rs/hepta-cognitive-types/src/wire.rs ` | ` owner_native ` |

### operations 原文（15 项）

```json
[
  {
    "operation": "build_snapshot",
    "nativeSymbol": "build_snapshot",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/lib.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/lib_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "build_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "cognitivesnapshotkeyv1",
    "nativeSymbol": "CognitiveSnapshotKeyV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/lane_c.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/lane_c_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "cognitivesnapshotkeyv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "modalityspanrefv1",
    "nativeSymbol": "ModalitySpanRefV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "modalityspanrefv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "memoryeventv1",
    "nativeSymbol": "MemoryEventV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "memoryeventv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "crossmodalbindingv1",
    "nativeSymbol": "CrossModalBindingV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "crossmodalbindingv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "engramnodev1",
    "nativeSymbol": "EngramNodeV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "engramnodev1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "synapsev1",
    "nativeSymbol": "SynapseV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "synapsev1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "memorycuev1",
    "nativeSymbol": "MemoryCueV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "memorycuev1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "recallpacketv1",
    "nativeSymbol": "RecallPacketV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "recallpacketv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "outcomesignalv1",
    "nativeSymbol": "OutcomeSignalV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "outcomesignalv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "replayselectionreceiptv1",
    "nativeSymbol": "ReplaySelectionReceiptV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "replayselectionreceiptv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "plasticitybatchv1",
    "nativeSymbol": "PlasticityBatchV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "plasticitybatchv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "topologyproposalv1",
    "nativeSymbol": "TopologyProposalV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "topologyproposalv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "forgetpropagationreceiptv1",
    "nativeSymbol": "ForgetPropagationReceiptV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "forgetpropagationreceiptv1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "canonical_wire_v1",
    "nativeSymbol": "CognitiveContractV1",
    "sourcePath": "codex-rs/hepta-cognitive-types/src/wire.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-types/src/contract_tests.rs",
      "codex-rs/hepta-cognitive-types/fuzz/fuzz_targets/decode_contracts.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_wire_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Run exact-head package/all-target/strict-clippy and deterministic synthetic-merge qualification for this exact candidate.",
  "Migrate registered consumers through explicit canonical V1 adapters; registry projection alone is not native consumer convergence.",
  "Bind authenticated production consumers to the exact registered V1 wire schemas before changing product-composition claims."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 23. cognitive.store

固定来源：[cognitive.store](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.store/IMPLEMENTATION_MAP.json)。Map Git blob：`4a4aecb8115a709c31a6483ff8c08a61585ec3f5`。

owner：` cognitive-platform `；productCallerState：` normal_agentd_runtime_capability_composed_external_bootstrap_pending `；productionWriterState：` sealed_same_transaction_provenance_writer_source_bound_qualification_pending `。

### 操作导航（12 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` semantic_revision_ledger ` | ` append_event_append_correction_forget_open_snapshot ` | ` AdmittedCognitiveStoreV2 ` | ` codex-rs/hepta-cognitive-store/src/v2.rs ` | ` owner_native ` |
| ` durable_owner ` | ` authoritative_memory_and_memory_revision_bound_fact_set_storage ` | ` DurableCognitiveStore ` | ` codex-rs/hepta-cognitive-store/src/durable.rs ` | ` canonical_facade ` |
| ` lane_c_snapshot ` | ` open_snapshot ` | ` lane_c_snapshot_page ` | ` codex-rs/hepta-memory/src/lane_c_snapshot.rs ` | ` owner_native ` |
| ` writable_recovery ` | ` open_with_recovery ` | ` open_with_recovery ` | ` codex-rs/hepta-memory/src/cognitive_store_recovery.rs ` | ` owner_native ` |
| ` product_writer_host ` | ` production_writer_host ` | ` AgentdProductionWriterHost ` | ` codex-rs/hepta-agentd/src/production_writer_host.rs ` | ` product_caller ` |
| ` production_mutation_capability ` | ` remember_correct_forget_with_atomic_authority_and_operation_provenance ` | ` ProductionCognitiveMutationCapability ` | ` codex-rs/hepta-memory/src/production_writer.rs ` | ` canonical_capability ` |
| ` canonical_memory_event_shadow ` | ` canonical_memory_event_shadow_write ` | ` AdmittedCognitiveStoreV2::append_admitted_with_canonical_shadow ` | ` codex-rs/hepta-cognitive-store/src/v2.rs ` | ` owner_native ` |
| ` canonical_durable_memory_event_binding ` | ` bind_memory_event_to_authoritative_source_revision_and_production_receipt ` | ` bind_canonical_event_to_durable_receipt ` | ` codex-rs/hepta-cognitive-store/src/v2.rs ` | ` canonical_bridge ` |
| ` grant_shared_experience ` | ` grant_shared_experience ` | ` pub async fn grant_shared_experience( ` | ` codex-rs/hepta-memory/src/shared_experience.rs ` | ` owner_native ` |
| ` read_shared_experience ` | ` read_shared_experience ` | ` pub async fn read_shared_experience( ` | ` codex-rs/hepta-memory/src/shared_experience.rs ` | ` owner_native ` |
| ` revalidate_shared_experience ` | ` revalidate_shared_experience ` | ` pub async fn revalidate_shared_experience( ` | ` codex-rs/hepta-memory/src/shared_experience.rs ` | ` owner_native ` |
| ` revoke_shared_experience ` | ` revoke_shared_experience ` | ` pub async fn revoke_shared_experience( ` | ` codex-rs/hepta-memory/src/shared_experience.rs ` | ` owner_native ` |

### operations 原文（12 项）

```json
[
  {
    "operation": "semantic_revision_ledger",
    "nativeSymbol": "AdmittedCognitiveStoreV2",
    "sourcePath": "codex-rs/hepta-cognitive-store/src/v2.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-store/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_event_append_correction_forget_open_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "e9ec79e983aa4a125536f688e480293c8b7d3131"
  },
  {
    "operation": "durable_owner",
    "nativeSymbol": "DurableCognitiveStore",
    "sourcePath": "codex-rs/hepta-cognitive-store/src/durable.rs",
    "state": "canonical_durable_owner_source_implemented_qualification_pending",
    "authority": "externally_verified",
    "tests": [
      "codex-rs/hepta-memory/src/cognitive_store_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "authoritative_memory_and_memory_revision_bound_fact_set_storage",
    "mappingClass": "canonical_facade",
    "delegatedCallees": [
      {
        "symbol": "hepta-memory::CognitiveStore",
        "path": "codex-rs/hepta-memory/src/cognitive_store.rs"
      }
    ],
    "sourceBlob": "6ace80385bed98c5306a00b63898214887e435bb"
  },
  {
    "operation": "lane_c_snapshot",
    "nativeSymbol": "lane_c_snapshot_page",
    "sourcePath": "codex-rs/hepta-memory/src/lane_c_snapshot.rs",
    "state": "durable_snapshot_source_implemented",
    "authority": "deny_all_read",
    "tests": [
      "codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "open_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "af66a5195f8a65635abe6c2abaf7b8e265bb6e9d"
  },
  {
    "operation": "writable_recovery",
    "nativeSymbol": "open_with_recovery",
    "sourcePath": "codex-rs/hepta-memory/src/cognitive_store_recovery.rs",
    "state": "descriptor_bound_recovery_source_implemented",
    "authority": "externally_verified",
    "tests": [
      "codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs",
      "codex-rs/state/src/sqlite_recovery_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "open_with_recovery",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "31ff28513c61f22f752e8118814521cc8017b0e5"
  },
  {
    "operation": "product_writer_host",
    "nativeSymbol": "AgentdProductionWriterHost",
    "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
    "state": "normal_runtime_composition_source_bound_external_bootstrap_pending",
    "authority": "externally_verified",
    "tests": [
      "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "production_writer_host",
    "mappingClass": "product_caller",
    "delegatedCallees": [
      {
        "symbol": "cognitive.store::DurableCognitiveStore",
        "path": "codex-rs/hepta-cognitive-store/src/durable.rs"
      },
      {
        "symbol": "cognitive.store::ProductionDurableWriter",
        "path": "codex-rs/hepta-memory/src/production_writer.rs"
      },
      {
        "symbol": "cognitive.store::ProductionCognitiveMutationCapability",
        "path": "codex-rs/hepta-memory/src/production_writer.rs"
      }
    ],
    "sourceBlob": "39d127250b8e825292c25f8c34ec360d5d94ff60"
  },
  {
    "operation": "production_mutation_capability",
    "nativeSymbol": "ProductionCognitiveMutationCapability",
    "sourcePath": "codex-rs/hepta-memory/src/production_writer.rs",
    "state": "sealed_live_verified_same_transaction_provenance_source_implemented_qualification_pending",
    "authority": "externally_verified_final_use",
    "tests": [
      "codex-rs/hepta-memory/src/production_writer.rs",
      "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
      "codex-rs/ext/hepta-memory/src/cognitive/tools_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "remember_correct_forget_with_atomic_authority_and_operation_provenance",
    "mappingClass": "canonical_capability",
    "delegatedCallees": [
      {
        "symbol": "hepta-memory::CognitiveStore",
        "path": "codex-rs/hepta-memory/src/cognitive_store.rs"
      }
    ],
    "sourceBlob": "ba5e42081ea35c0d43c5e1d77be43f2f6a1d3966"
  },
  {
    "operation": "canonical_memory_event_shadow",
    "nativeSymbol": "AdmittedCognitiveStoreV2::append_admitted_with_canonical_shadow",
    "sourcePath": "codex-rs/hepta-cognitive-store/src/v2.rs",
    "state": "source_implemented_shadow_only_not_product_composed",
    "authority": "existing_store_authority_only_no_new_authority",
    "tests": [
      "codex-rs/hepta-cognitive-store/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_memory_event_shadow_write",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "symbol": "AdmittedCognitiveStoreV2::append_admitted",
        "path": "codex-rs/hepta-cognitive-store/src/v2.rs"
      }
    ],
    "sourceBlob": "e9ec79e983aa4a125536f688e480293c8b7d3131"
  },
  {
    "operation": "canonical_durable_memory_event_binding",
    "nativeSymbol": "bind_canonical_event_to_durable_receipt",
    "sourcePath": "codex-rs/hepta-cognitive-store/src/v2.rs",
    "state": "source_implemented_product_receipt_bound_qualification_pending",
    "authority": "deny_all_binding_receipt",
    "tests": [
      "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "bind_memory_event_to_authoritative_source_revision_and_production_receipt",
    "mappingClass": "canonical_bridge",
    "delegatedCallees": [
      {
        "symbol": "ProductionCognitiveMutationReceiptV1",
        "path": "codex-rs/hepta-memory/src/production_writer.rs"
      }
    ],
    "sourceBlob": "e9ec79e983aa4a125536f688e480293c8b7d3131"
  },
  {
    "operation": "grant_shared_experience",
    "designOperation": "grant_shared_experience",
    "nativeSymbol": "pub async fn grant_shared_experience(",
    "sourcePath": "codex-rs/hepta-memory/src/shared_experience.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-memory/src/shared_experience_tests.rs::last_active_revision_can_be_revoked_and_stays_revoked_after_restart"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "d49b121b9c5e64249e1dd7285139ccf6e46d49bb"
  },
  {
    "operation": "read_shared_experience",
    "designOperation": "read_shared_experience",
    "nativeSymbol": "pub async fn read_shared_experience(",
    "sourcePath": "codex-rs/hepta-memory/src/shared_experience.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-memory/src/shared_experience_tests.rs::last_active_revision_can_be_revoked_and_stays_revoked_after_restart"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "d49b121b9c5e64249e1dd7285139ccf6e46d49bb"
  },
  {
    "operation": "revalidate_shared_experience",
    "designOperation": "revalidate_shared_experience",
    "nativeSymbol": "pub async fn revalidate_shared_experience(",
    "sourcePath": "codex-rs/hepta-memory/src/shared_experience.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-memory/src/shared_experience_tests.rs::last_active_revision_can_be_revoked_and_stays_revoked_after_restart"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "d49b121b9c5e64249e1dd7285139ccf6e46d49bb"
  },
  {
    "operation": "revoke_shared_experience",
    "designOperation": "revoke_shared_experience",
    "nativeSymbol": "pub async fn revoke_shared_experience(",
    "sourcePath": "codex-rs/hepta-memory/src/shared_experience.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-memory/src/shared_experience_tests.rs::last_active_revision_can_be_revoked_and_stays_revoked_after_restart"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "d49b121b9c5e64249e1dd7285139ccf6e46d49bb"
  }
]
```

### repositoryControlledGaps 原文（5 项）

```json
[
  "Obtain terminal-success exact-head and deterministic synthetic-merge receipts for this source baseline, including child-process crash/reopen and 256/16384 PERF-DURABLE artifacts.",
  "Obtain terminal-success exact-candidate execution evidence for the same-transaction semantic-validation failure, response-loss/restart duplicate rejection, and live-authority revocation cases already present in source tests.",
  "Define and qualify long-term ancestry-safe retention/pruning beyond bounded paging; logical tombstones must not be reported as physical erasure, backup deletion, derived-artifact revocation or model unlearning.",
  "Keep productionImplementation false until the normal-runtime sealed capability path compiles/tests on the exact candidate and product execution evidence is current.",
  "Standalone deployment must receive an independently authenticated current-cut witness and externally verified live production authority from its host; Agentd must not self-mint either."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "trusted host bootstrap and target-host product qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 24. cognitive.read

固定来源：[cognitive.read](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/cognitive.read/IMPLEMENTATION_MAP.json)。Map Git blob：`6afdd69cbb3a14337ef68d6dded995229351e966`。

owner：` cognitive-platform `；productCallerState：` composed_local_host `；productionWriterState：` not_applicable_read_only `。

### 操作导航（6 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` read_ids_v1 ` | ` read_ids ` | ` read_ids_v1 ` | ` codex-rs/hepta-cognitive-read/src/ids.rs ` | ` owner_native ` |
| ` read_v2 ` | ` bounded_compatibility_projection ` | ` read_v2 ` | ` codex-rs/hepta-cognitive-read/src/v2.rs ` | ` owner_native ` |
| ` read_authoritative_compatibility ` | ` compatibility_authoritative_provider ` | ` read_authoritative ` | ` codex-rs/hepta-cognitive-read/src/authoritative.rs ` | ` owner_native ` |
| ` durable_cognitive_snapshot ` | ` acquire_snapshot ` | ` DurableCognitiveSnapshot ` | ` codex-rs/hepta-memory/src/lane_c_snapshot.rs ` | ` existing_owner_adapter ` |
| ` final_use_revalidate ` | ` revalidate ` | ` revalidate_with_retrieval_context ` | ` codex-rs/hepta-agentd/src/cognitive_context.rs ` | ` consumer_integration ` |
| ` adapt_authoritative_read_to_canonical_shadow_v1 ` | ` canonical_authoritative_read_shadow ` | ` adapt_authoritative_read_to_canonical_shadow_v1 ` | ` codex-rs/hepta-cognitive-read/src/authoritative.rs ` | ` owner_native ` |

### operations 原文（6 项）

```json
[
  {
    "operation": "read_ids_v1",
    "nativeSymbol": "read_ids_v1",
    "sourcePath": "codex-rs/hepta-cognitive-read/src/ids.rs",
    "state": "source_implemented_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-read/src/ids_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "read_ids",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      "codex-rs/hepta-memory/src/lane_c_snapshot.rs",
      "codex-rs/hepta-agentd/src/cognitive_context.rs"
    ],
    "sourceBlob": "e56b2ef34038c35a0d7c179375ce21ad463f0347"
  },
  {
    "operation": "read_v2",
    "nativeSymbol": "read_v2",
    "sourcePath": "codex-rs/hepta-cognitive-read/src/v2.rs",
    "state": "source_implemented_compatibility_library",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-read/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "bounded_compatibility_projection",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "67135f3f56c4779fbd27568ee69c389a38522e5c"
  },
  {
    "operation": "read_authoritative_compatibility",
    "nativeSymbol": "read_authoritative",
    "sourcePath": "codex-rs/hepta-cognitive-read/src/authoritative.rs",
    "state": "source_implemented_compatibility_library",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-read/src/authoritative_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compatibility_authoritative_provider",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "7b84d401b71d24f547a8c2de0e4d5c4117253ecb"
  },
  {
    "operation": "durable_cognitive_snapshot",
    "nativeSymbol": "DurableCognitiveSnapshot",
    "sourcePath": "codex-rs/hepta-memory/src/lane_c_snapshot.rs",
    "state": "source_implemented_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "acquire_snapshot",
    "mappingClass": "existing_owner_adapter",
    "delegatedCallees": [],
    "sourceBlob": "af66a5195f8a65635abe6c2abaf7b8e265bb6e9d"
  },
  {
    "operation": "final_use_revalidate",
    "nativeSymbol": "revalidate_with_retrieval_context",
    "sourcePath": "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "state": "source_implemented_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-agentd/src/cognitive_context_tests.rs",
      "codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs",
      "codex-rs/hepta-infer-core/src/native_control_tests.rs",
      "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
      "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
      "codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs",
      "codex-rs/hepta-agentd/src/state_isolation_tests.rs",
      "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs::final_use_revalidation_rejects_tombstone_during_provider_callback",
      "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs::final_use_revalidation_rejects_source_drift_during_provider_callback",
      "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs::final_use_revalidation_rejects_changed_hnmf_context"
    ],
    "sourcePathExists": true,
    "designOperation": "revalidate",
    "mappingClass": "consumer_integration",
    "delegatedCallees": [
      "codex-rs/hepta-agent-protocol/src/lib.rs",
      "codex-rs/hepta-agentd/src/client.rs",
      "codex-rs/hepta-infer-core/src/native_control.rs",
      "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
      "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
      {
        "path": "codex-rs/hepta-memory/src/lane_c_snapshot.rs",
        "symbol": "CognitiveStore::revalidate_lane_c_snapshot"
      }
    ],
    "sourceBlob": "ec5a1fbcb297876d76fcd51569a26ba3f65b82d8"
  },
  {
    "operation": "adapt_authoritative_read_to_canonical_shadow_v1",
    "nativeSymbol": "adapt_authoritative_read_to_canonical_shadow_v1",
    "sourcePath": "codex-rs/hepta-cognitive-read/src/authoritative.rs",
    "state": "source_implemented_shadow_only_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-cognitive-read/src/authoritative_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_authoritative_read_shadow",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "symbol": "AuthoritativeReadResultV1::validate",
        "path": "codex-rs/hepta-cognitive-read/src/authoritative.rs"
      }
    ],
    "sourceBlob": "7b84d401b71d24f547a8c2de0e4d5c4117253ecb"
  }
]
```

### repositoryControlledGaps 原文（11 项）

```json
[
  "Obtain exact-head and deterministic synthetic-merge execution receipts for the candidate.",
  "Obtain exact-candidate execution receipts for the implemented real Agentd/native-worker fresh-context acceptance plus concurrent tombstone/correction rejection, owner-cut validity-expiry/rollback detection, and stale host-generation rejection; source presence is not a pass receipt.",
  "Keep the current durable SQLite kind capability Fact-only until an explicit owner schema migration qualifies additional memory kinds.",
  "Add target-host p50/p95/p99 CPU, RSS and SQLite measurements before performance qualification.",
  "Qualify adapt_authoritative_read_to_canonical_shadow_v1 on exact source-head and deterministic synthetic merge.",
  "Supply authoritative source-revision bindings before claiming full canonical provenance equivalence; legacy MemoryRecord citations do not carry source revisions.",
  "Migrate named downstream callers from legacy ReadResultV2 only after exact record-to-event bridge ownership is established.",
  "Revalidate the canonical shadow against the current final-use snapshot before physical model-request attachment; a historical read receipt grants no future-use authority.",
  "Named source and product adapters remain present; current candidate requalification is required because mapped source/build inputs changed after the retained historical observation. Historical production proof is not rebound by navigation migration.",
  "Retain candidate-bound native RED/GREEN receipts for the final SQLite owner-cut reread after retrieval and ranker callbacks: committed tombstones and source-frontier-only drift during the retrieval callback must reject final use, while unchanged context still succeeds.",
  "Keep the added owner-currentness guard separate from real retrieval-provider activation, physical model-request attachment, process-restart qualification and any claim of atomic authority across different owners."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 25. memory.retrieval

固定来源：[memory.retrieval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json)。Map Git blob：`2fc791a06de07e559f2cf110d51ec1e32da67308`。

owner：` cognitive-platform `；productCallerState：` source_composed_explicit_profile_not_product_qualified `；productionWriterState：` not_established `。

### 操作导航（9 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` retrieve_v2 ` | ` retrieve_v2 ` | ` retrieve_v2 ` | ` codex-rs/hepta-memory-retrieval/src/v2.rs ` | ` owner_native ` |
| ` compile_cue ` | ` compile_cue ` | ` compile_cue ` | ` codex-rs/hepta-memory-retrieval/src/generator.rs ` | ` owner_native ` |
| ` build_candidate_union_from_generated ` | ` retrieve ` | ` build_candidate_union_from_generated ` | ` codex-rs/hepta-memory-retrieval/src/generator.rs ` | ` owner_native ` |
| ` settle_engram ` | ` engram_settle ` | ` settle_engram ` | ` codex-rs/hepta-memory-retrieval/src/engram.rs ` | ` owner_native ` |
| ` recall_generated_with_engram ` | ` recall ` | ` recall_generated_with_engram ` | ` codex-rs/hepta-memory-retrieval/src/generator.rs ` | ` owner_native ` |
| ` observe_retrieval_assignment ` | ` assignment_observation ` | ` observe_retrieval_assignment ` | ` codex-rs/hepta-memory-retrieval/src/decision.rs ` | ` owner_native ` |
| ` build_candidate_union ` | ` build_candidate_union ` | ` build_candidate_union ` | ` codex-rs/hepta-memory-retrieval/src/generation_bound.rs ` | ` owner_native ` |
| ` recall ` | ` recall ` | ` recall ` | ` codex-rs/hepta-memory-retrieval/src/generation_bound.rs ` | ` owner_native ` |
| ` adapt_generation_bound_recall_to_canonical_shadow_v1 ` | ` canonical_recall_shadow_adapter ` | ` adapt_generation_bound_recall_to_canonical_shadow_v1 ` | ` codex-rs/hepta-memory-retrieval/src/generation_bound.rs ` | ` owner_native ` |

### operations 原文（9 项）

```json
[
  {
    "operation": "retrieve_v2",
    "nativeSymbol": "retrieve_v2",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/v2.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "retrieve_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "69e7c773f9ebaa777783a4965749a0051edf37eb"
  },
  {
    "operation": "compile_cue",
    "nativeSymbol": "compile_cue",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generator.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/generator_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "compile_cue",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "dc5ccaee3ffa5fae36a62594627c293e9d7fbfec"
  },
  {
    "operation": "build_candidate_union_from_generated",
    "nativeSymbol": "build_candidate_union_from_generated",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generator.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/generator_tests.rs",
      "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "retrieve",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "dc5ccaee3ffa5fae36a62594627c293e9d7fbfec"
  },
  {
    "operation": "settle_engram",
    "nativeSymbol": "settle_engram",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/engram.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/engram_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "engram_settle",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2d2df3efb3cfcfe0c785c4e1369a68a8712258b0"
  },
  {
    "operation": "recall_generated_with_engram",
    "nativeSymbol": "recall_generated_with_engram",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generator.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/generator_tests.rs",
      "codex-rs/hepta-memory-retrieval/src/engram_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "recall",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "dc5ccaee3ffa5fae36a62594627c293e9d7fbfec"
  },
  {
    "operation": "observe_retrieval_assignment",
    "nativeSymbol": "observe_retrieval_assignment",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/decision.rs",
    "state": "source_implemented_not_product_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/decision_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "assignment_observation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "7d701b3a4db8820a962cd9174ffd6ce9e41f12e1"
  },
  {
    "operation": "build_candidate_union",
    "nativeSymbol": "build_candidate_union",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "build_candidate_union",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "79402db4a16e3b1255f7b926a879de34b28e42e4"
  },
  {
    "operation": "recall",
    "nativeSymbol": "recall",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "recall",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "79402db4a16e3b1255f7b926a879de34b28e42e4"
  },
  {
    "operation": "adapt_generation_bound_recall_to_canonical_shadow_v1",
    "nativeSymbol": "adapt_generation_bound_recall_to_canonical_shadow_v1",
    "sourcePath": "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
    "state": "source_implemented_shadow_only_not_product_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_recall_shadow_adapter",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "79402db4a16e3b1255f7b926a879de34b28e42e4"
  }
]
```

### repositoryControlledGaps 原文（4 项）

```json
[
  "Obtain green exact-head and ordered-parent synthetic-merge receipts for the exact observed source snapshot, including package tests, all-target Clippy, formatting and clean source.",
  "Compose and independently qualify an authenticated CurrentMemoryRetrievalContext provider for the real Agentd hnmf-required process profile; the binary now selects the profile explicitly and fails startup when the provider is absent.",
  "Retain a green exact-head qualification-host receipt and repeat the same checked-in SQLite/revalidation plus 512-candidate/4096-node/32768-synapse/four-step probes on an approved named target host before target-host performance claims.",
  "Bind and qualify a real current encoder/vector-index owner before enabling the Vector policy channel; no lexical, generic-graph or learned-ranker score may be relabelled as vector evidence."
]
```

### externalEvidenceGates 原文（5 项）

```json
[
  "independent semantic review and acceptance",
  "approved named target-host p50/p95/p99 latency, throughput, CPU, RSS/peak-memory, allocation and SQLite/revalidation measurements",
  "actual encoder/vector-index owner qualification before the Vector policy channel is enabled",
  "independently observed learned-ranker propensity/outcome evidence for causal utility claims",
  "operator acceptance, canary, promotion and release"
]
```

## 26. memory.federation

固定来源：[memory.federation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/memory.federation/IMPLEMENTATION_MAP.json)。Map Git blob：`2d7922dd6920cdfc70c5d7c6c62134be53d27c8f`。

owner：` cognitive-platform `；productCallerState：` composed_candidate_pending_execution `；productionWriterState：` not_applicable_read_only `。

### 操作导航（2 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` execute_once ` | ` execute_once ` | ` execute_once ` | ` codex-rs/hepta-memory-federation/src/v2.rs ` | ` owner_native ` |
| ` observe_cancellation ` | ` observe_cancellation ` | ` observe_cancellation ` | ` codex-rs/hepta-memory-federation/src/v2.rs ` | ` owner_native ` |

### operations 原文（2 项）

```json
[
  {
    "operation": "execute_once",
    "nativeSymbol": "execute_once",
    "sourcePath": "codex-rs/hepta-memory-federation/src/v2.rs",
    "state": "source_hardened_candidate_pending_execution",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-federation/src/v2_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_runtime_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "execute_once",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      "codex-rs/hepta-memory/src/cognitive_runtime.rs",
      "codex-rs/hepta-agentd/src/runtime.rs",
      "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
    ],
    "sourceBlob": "760d972ef2adec706a2cbeada5727a1c379f2e4d"
  },
  {
    "operation": "observe_cancellation",
    "nativeSymbol": "observe_cancellation",
    "sourcePath": "codex-rs/hepta-memory-federation/src/v2.rs",
    "state": "source_hardened_candidate_pending_execution",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-memory-federation/src/v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "observe_cancellation",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "760d972ef2adec706a2cbeada5727a1c379f2e4d"
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Run exact-current-head focused/package/product-composition/all-target/strict-lint checks and deterministic merge-candidate checks; fix any defect before changing productExecutionProved.",
  "Product turn cancellation is currently enforced by host future-drop propagation; add explicit product cancellation attribution/receipt wiring if canonical cancellation observability is required."
]
```

### externalEvidenceGates 原文（4 项）

```json
[
  "independent semantic and security review",
  "multi-host authenticated transport qualification when federation crosses a process or host boundary",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 27. knowledge.graph

固定来源：[knowledge.graph](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json)。Map Git blob：`21ce05004fffd7af67ee849d9180010c8870697c`。

owner：` knowledge-graph `；productCallerState：` composed_cognitive_read_default_agentd_write_and_prompt_optimizer_pending_exact_head `；productionWriterState：` candidate_agentd_default_fail_closed_pending_exact_head `。

### 操作导航（5 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` build_complete_generation ` | ` build_complete_generation ` | ` build_complete_generation ` | ` codex-rs/hepta-kg/src/generation.rs ` | ` owner_native_with_cognitive_owner_adapter ` |
| ` apply_incremental_delta ` | ` apply_incremental_delta ` | ` apply_incremental_delta ` | ` codex-rs/hepta-kg/src/generation.rs ` | ` owner_native ` |
| ` publish_generation ` | ` publish_generation ` | ` publish_generation ` | ` codex-rs/hepta-kg/src/generation.rs ` | ` owner_native_with_cognitive_owner_adapter ` |
| ` query_relations ` | ` query_relations ` | ` query_relations ` | ` codex-rs/hepta-kg/src/generation.rs ` | ` owner_native_with_cognitive_read_adapter ` |
| ` build_prompt_factor_projection_v1 ` | ` build_prompt_factor_projection ` | ` build_prompt_factor_projection_v1 ` | ` codex-rs/hepta-kg/src/prompt_factor.rs ` | ` owner_native_with_prompt_registry_source_and_optimizer_consumer ` |

### operations 原文（5 项）

```json
[
  {
    "operation": "build_complete_generation",
    "nativeSymbol": "build_complete_generation",
    "sourcePath": "codex-rs/hepta-kg/src/generation.rs",
    "state": "product_composed_via_cognitive_sqlite_owner",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-kg/src/generation_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs",
      "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "build_complete_generation",
    "mappingClass": "owner_native_with_cognitive_owner_adapter",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-memory/src/cognitive_kg_store.rs",
        "symbol": "canonical_generation_from_projection"
      }
    ],
    "sourceBlob": "ee013b4cf115c3efd75ce3d67a6d042bbdb36142"
  },
  {
    "operation": "apply_incremental_delta",
    "nativeSymbol": "apply_incremental_delta",
    "sourcePath": "codex-rs/hepta-kg/src/generation.rs",
    "state": "source_implemented_oracle_composed_not_runtime_selected",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-kg/src/generation_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "apply_incremental_delta",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "ee013b4cf115c3efd75ce3d67a6d042bbdb36142"
  },
  {
    "operation": "publish_generation",
    "nativeSymbol": "publish_generation",
    "sourcePath": "codex-rs/hepta-kg/src/generation.rs",
    "state": "product_composed_same_sqlite_transaction",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-kg/src/generation_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_store_tests.rs",
      {
        "path": "codex-rs/hepta-memory/src/cognitive_store_tests.rs",
        "symbol": "qualification_kg_projection_crash_windows_restore_exact_predecessor"
      },
      {
        "path": "codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs",
        "symbol": "qualification_knowledge_graph_capacity_receipt"
      }
    ],
    "sourcePathExists": true,
    "designOperation": "publish_generation",
    "mappingClass": "owner_native_with_cognitive_owner_adapter",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-memory/src/cognitive_kg_store.rs",
        "symbol": "refresh_scope_projection_tx"
      }
    ],
    "sourceBlob": "ee013b4cf115c3efd75ce3d67a6d042bbdb36142"
  },
  {
    "operation": "query_relations",
    "nativeSymbol": "query_relations",
    "sourcePath": "codex-rs/hepta-kg/src/generation.rs",
    "state": "product_composed_cognitive_graph_one_hop",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-kg/src/generation_tests.rs",
      "codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs",
      "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
      {
        "path": "codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs",
        "symbol": "qualification_knowledge_graph_capacity_receipt"
      },
      "codex-rs/hepta-kg/src/prompt_factor_tests.rs",
      "codex-rs/hepta-prompt-optimizer/src/graph_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "query_relations",
    "mappingClass": "owner_native_with_cognitive_read_adapter",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-memory/src/cognitive_retrieval.rs",
        "symbol": "graph_channel_tx"
      },
      {
        "path": "codex-rs/hepta-prompt-optimizer/src/graph.rs",
        "symbol": "optimize_with_factor_graph"
      }
    ],
    "sourceBlob": "ee013b4cf115c3efd75ce3d67a6d042bbdb36142"
  },
  {
    "operation": "build_prompt_factor_projection_v1",
    "nativeSymbol": "build_prompt_factor_projection_v1",
    "sourcePath": "codex-rs/hepta-kg/src/prompt_factor.rs",
    "state": "source_composed_prompt_registry_owner_to_prompt_optimizer_consumer_pending_exact_head",
    "authority": "none",
    "tests": [
      {
        "path": "codex-rs/hepta-prompt-registry/src/lib_tests.rs",
        "symbol": "governed_factor_relations_are_owner_bound_and_rebuildable"
      },
      "codex-rs/hepta-kg/src/prompt_factor_tests.rs",
      "codex-rs/hepta-prompt-optimizer/src/graph_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "build_prompt_factor_projection",
    "mappingClass": "owner_native_with_prompt_registry_source_and_optimizer_consumer",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-prompt-registry/src/lib.rs",
        "symbol": "PromptRegistry::factor_graph_source_v1"
      },
      {
        "path": "codex-rs/hepta-prompt-optimizer/src/graph.rs",
        "symbol": "optimize_with_factor_graph"
      }
    ],
    "sourceBlob": "7b2b4468dc1095a257d2d910569d12c9d282d420"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Current exact-head and deterministic synthetic-merge knowledge.graph qualification receipts must both be green before productionImplementation or productExecutionProved can change.",
  "The durable cognitive writer currently selects complete bounded generation rebuild per logical mutation. PERF-LIBRARY and target-host results decide whether the already-qualified incremental algorithm should become the runtime writer; no host-independent latency threshold is claimed.",
  "The prompt-factor source/projection/optimizer chain is source-composed and owner-sealed here, but prompt.registry durability/activation remains that module's separate gate and is not self-certified by knowledge.graph."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 28. compact.engine

固定来源：[compact.engine](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/compact.engine/IMPLEMENTATION_MAP.json)。Map Git blob：`9f9c5e34ad955f899eb9256cb6b0640e03806ef0`。

owner：` cognitive-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` compact ` | ` compact ` | ` compact ` | ` codex-rs/hepta-compact-engine/src/lib.rs ` | ` owner_native ` |
| ` build_qualified_candidate ` | ` build_qualified_candidate ` | ` build_qualified_candidate ` | ` codex-rs/hepta-compact-engine/src/qualified.rs ` | ` owner_native ` |
| ` prove_compaction ` | ` prove_compaction ` | ` prove_compaction ` | ` codex-rs/hepta-compact-engine/src/qualified.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "operation": "compact",
    "nativeSymbol": "compact",
    "sourcePath": "codex-rs/hepta-compact-engine/src/lib.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "compact",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "build_qualified_candidate",
    "nativeSymbol": "build_qualified_candidate",
    "sourcePath": "codex-rs/hepta-compact-engine/src/qualified.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "build_qualified_candidate",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  },
  {
    "operation": "prove_compaction",
    "nativeSymbol": "prove_compaction",
    "sourcePath": "codex-rs/hepta-compact-engine/src/qualified.rs",
    "state": "source_implemented_not_product_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "prove_compaction",
    "mappingClass": "owner_native",
    "delegatedCallees": []
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 29. learning.ledger

固定来源：[learning.ledger](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.ledger/IMPLEMENTATION_MAP.json)。Map Git blob：`89cfe11b1403b003ab351baf49d587c4e940933b`。

owner：` learning-platform `；productCallerState：` qualification_consumer_composed_live_product_not_established `；productionWriterState：` source_implemented_host_not_established `。

### 操作导航（18 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` durable_run_start_journal ` | ` durable_run_start_journal ` | ` DurableRunStartJournal ` | ` codex-rs/hepta-learning-ledger/src/run_start.rs ` | ` owner_native ` |
| ` append_decision ` | ` append_decision ` | ` LedgerWriter::append_decision ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` append_outcome ` | ` append_outcome ` | ` LedgerWriter::append_outcome ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` reconcile_committed_append ` | ` reconcile_committed_append ` | ` LedgerWriter::reconcile_committed_append ` | ` codex-rs/hepta-learning-ledger/src/production_reconciliation.rs ` | ` owner_native ` |
| ` append_credit_batch ` | ` append_credit_batch ` | ` LedgerWriter::append_credit_batch ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` append_unlearning ` | ` append_unlearning ` | ` LedgerWriter::append_unlearning ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` freeze_dataset ` | ` freeze_dataset ` | ` LedgerWriter::freeze_dataset ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` revalidate_dataset_snapshot ` | ` revalidate_dataset_snapshot ` | ` LedgerWriter::revalidate_dataset_snapshot ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` rotate_segment ` | ` rotate_segment ` | ` LedgerWriter::rotate_segment ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` ledger_witness_store ` | ` ledger_witness_store ` | ` LedgerWitnessStore ` | ` codex-rs/hepta-learning-ledger/src/witness.rs ` | ` owner_native ` |
| ` activate_learning_trust ` | ` activate_learning_trust ` | ` activate_learning_trust ` | ` codex-rs/hepta-learning-ledger/src/trust_distribution.rs ` | ` owner_native ` |
| ` canonical_protocol_adapters ` | ` canonical_protocol_adapters ` | ` LearningDecisionV1 ` | ` codex-rs/hepta-learning-ledger/src/protocol.rs ` | ` owner_native ` |
| ` build_ledger_index_checkpoint ` | ` build_ledger_index_checkpoint ` | ` build_ledger_index_checkpoint ` | ` codex-rs/hepta-learning-ledger/src/checkpoint.rs ` | ` owner_native ` |
| ` validate_candidate_set_completeness ` | ` validate_candidate_set_completeness ` | ` validate_candidate_set_completeness ` | ` codex-rs/hepta-learning-ledger/src/causal_v2.rs ` | ` owner_native ` |
| ` sync_directory_handle ` | ` sync_directory_handle ` | ` sync_directory_handle ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` LedgerWriter::rotate_trust ` | ` LedgerWriter::rotate_trust ` | ` codex_hepta_learning_ledger::LedgerWriter::rotate_trust ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |
| ` measure_ledger_recovery_work ` | ` measure_ledger_recovery_work ` | ` codex_hepta_learning_ledger::measure_ledger_recovery_work ` | ` codex-rs/hepta-learning-ledger/src/recovery_work.rs ` | ` owner_native ` |
| ` read_dataset_records ` | ` read_dataset_records ` | ` pub fn read_dataset_records( ` | ` codex-rs/hepta-learning-ledger/src/production.rs ` | ` owner_native ` |

### operations 原文（18 项）

```json
[
  {
    "operation": "durable_run_start_journal",
    "nativeSymbol": "DurableRunStartJournal",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/run_start.rs",
    "state": "source_implemented_destination_owned_run_start_durability",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/run_start_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "durable_run_start_journal",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cb387137df02044221c2b2caa0bc8db0ccde3fd7"
  },
  {
    "operation": "append_decision",
    "nativeSymbol": "LedgerWriter::append_decision",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_authenticated_product_writer",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs",
      "codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_decision",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-ledger/src/durable.rs",
        "symbol": "DurableLedger"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/segments.rs",
        "symbol": "SegmentedLedger"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/witness.rs",
        "symbol": "LedgerWitnessStore"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/signed_evidence.rs",
        "symbol": "LearningEvidenceVerifierV1"
      }
    ],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "append_outcome",
    "nativeSymbol": "LedgerWriter::append_outcome",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_authenticated_product_writer",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs",
      "codex-rs/hepta-intelligence/src/outcome_credit_v2.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_outcome",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "reconcile_committed_append",
    "nativeSymbol": "LedgerWriter::reconcile_committed_append",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production_reconciliation.rs",
    "state": "source_implemented_exact_historical_ack",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_reconciliation_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "reconcile_committed_append",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-ledger/src/production.rs",
        "symbol": "LedgerWriter::commit"
      }
    ],
    "sourceBlob": "f63fd6698fdc2ba3343b04277f0f9b3438e134a9"
  },
  {
    "operation": "append_credit_batch",
    "nativeSymbol": "LedgerWriter::append_credit_batch",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_atomic_conserved_credit",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/ledger_tests.rs",
      "codex-rs/hepta-learning-ledger/src/production_tests.rs",
      "codex-rs/hepta-intelligence/src/outcome_credit_v2.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_credit_batch",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "append_unlearning",
    "nativeSymbol": "LedgerWriter::append_unlearning",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_verified_source_dataset_membership_artifact_handoff",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/ledger_tests.rs",
      "codex-rs/hepta-learning-ledger/src/production_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "append_unlearning",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "freeze_dataset",
    "nativeSymbol": "LedgerWriter::freeze_dataset",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_ledger_derived",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "freeze_dataset",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "revalidate_dataset_snapshot",
    "nativeSymbol": "LedgerWriter::revalidate_dataset_snapshot",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_final_use_currentness",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "revalidate_dataset_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "rotate_segment",
    "nativeSymbol": "LedgerWriter::rotate_segment",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_directory_sync_before_witness",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs",
      "codex-rs/hepta-intelligence/src/evaluated_shadow_segment_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "rotate_segment",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "ledger_witness_store",
    "nativeSymbol": "LedgerWitnessStore",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/witness.rs",
    "state": "source_implemented_independent_frontier",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/witness_tests.rs",
      "codex-rs/hepta-learning-ledger/src/production_tests.rs",
      "codex-rs/hepta-learning-ledger/src/witness_tests.rs::complete_unconfirmed_witness_frame_requires_successful_recovery_sync"
    ],
    "sourcePathExists": true,
    "designOperation": "ledger_witness_store",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8eab326e0c90021a1eca5939b7127b07fb26fd14"
  },
  {
    "operation": "activate_learning_trust",
    "nativeSymbol": "activate_learning_trust",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/trust_distribution.rs",
    "state": "source_implemented_root_authenticated_distribution_transport_external",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/trust_distribution_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "activate_learning_trust",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-ledger/src/trust_distribution.rs",
        "symbol": "LearningTrustRootV1"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/trust_distribution.rs",
        "symbol": "SignedLearningTrustDistributionV1"
      },
      {
        "path": "codex-rs/hepta-learning-ledger/src/signed_evidence.rs",
        "symbol": "LearningEvidenceVerifierV1"
      }
    ],
    "sourceBlob": "4a077f8f9601b0ca1dc5973c044da2201b8c6686"
  },
  {
    "operation": "canonical_protocol_adapters",
    "nativeSymbol": "LearningDecisionV1",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/protocol.rs",
    "state": "source_implemented_registered_v1_views",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/protocol_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "canonical_protocol_adapters",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "19c1c8804bf05a0b8eba70f0e930995d4b9cecd8"
  },
  {
    "operation": "build_ledger_index_checkpoint",
    "nativeSymbol": "build_ledger_index_checkpoint",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/checkpoint.rs",
    "state": "source_implemented_rebuildable_projection",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/checkpoint_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "build_ledger_index_checkpoint",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "14c908e13440b340095aaeaed10080ed15acf9e7"
  },
  {
    "operation": "validate_candidate_set_completeness",
    "nativeSymbol": "validate_candidate_set_completeness",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
    "state": "source_implemented_compatibility_validator",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/causal_v2_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "validate_candidate_set_completeness",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2bd6de5896b2cf1db2a65d82aeb3046dfa1a36af"
  },
  {
    "operation": "sync_directory_handle",
    "nativeSymbol": "sync_directory_handle",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "state": "source_implemented_host_authorized_directory_fsync",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "sync_directory_handle",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "LedgerWriter::rotate_trust",
    "designOperation": "LedgerWriter::rotate_trust",
    "nativeSymbol": "codex_hepta_learning_ledger::LedgerWriter::rotate_trust",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "sourcePathExists": true,
    "state": "source_implemented_ci_pending",
    "mappingClass": "owner_native",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/production_tests.rs"
    ],
    "delegatedCallees": [],
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  },
  {
    "operation": "measure_ledger_recovery_work",
    "designOperation": "measure_ledger_recovery_work",
    "nativeSymbol": "codex_hepta_learning_ledger::measure_ledger_recovery_work",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/recovery_work.rs",
    "sourcePathExists": true,
    "state": "source_implemented_ci_pending",
    "mappingClass": "owner_native",
    "tests": [
      "codex-rs/hepta-learning-ledger/src/checkpoint_tests.rs"
    ],
    "delegatedCallees": [],
    "sourceBlob": "17605c9a41c57aaacc843b4069c2a1733ed673af"
  },
  {
    "operation": "read_dataset_records",
    "designOperation": "read_dataset_records",
    "nativeSymbol": "pub fn read_dataset_records(",
    "sourcePath": "codex-rs/hepta-learning-ledger/src/production.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs::real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "1feb4ed1a405c05d7d47b2d8d37f988be904b31c"
  }
]
```

### repositoryControlledGaps 原文（6 项）

```json
[
  "Bind the durable run-start owner to the authenticated canonical objective/product producer and current-trust Agentd consumer; raw retained records are not self-authenticating current evidence.",
  "Keep restart recovery non-redispatchable after possible external dispatch and reconcile terminal observations through the existing execution owner.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary.",
  "Retain candidate-bound native RED/GREEN receipts for exact committed Decision/Outcome acknowledgement after witness-write uncertainty, proof expiry and reopen; mismatched/missing references, poisoned handles, non-tail witness lag and revoked decisions must retain their existing refusal semantics.",
  "Retain candidate-bound native receipts showing that a complete recovered witness frame is not exposed unless recovery sync succeeds; the injected sync failure must return Indeterminate and a later real sync must recover without appending.",
  "Default daemon Decision/Outcome admission and durable pending-intent recovery remain separate open gates; the committed-only API accepts no new event body and grants no renewed signing, execution or current-use authority."
]
```

### externalEvidenceGates 原文（6 项）

```json
[
  "exclusive physical writer and directory ownership on the selected live host",
  "production root provisioning/rotation ceremony, trust-distribution transport, key custody and independent witness placement",
  "target-host latency, storage growth, reopen, sustained throughput, RSS and physical power-loss/filesystem qualification",
  "live independent outcomes and genuine future-window longitudinal evidence",
  "live learning.artifacts dataset-withdrawal fanout, descendant revocation and rebuild handoff",
  "independent semantic review, operator acceptance, canary, promotion and release"
]
```

## 30. learning.operator

固定来源：[learning.operator](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.operator/IMPLEMENTATION_MAP.json)。Map Git blob：`aecd120c3b8f23e6d0ef5bbfd343c6410b4c3de0`。

owner：` learning-platform `；productCallerState：` explicit_read_consumer_composed_default_learning_loop_absent `；productionWriterState：` not_established `。

### 操作导航（20 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` build_targets ` | ` build_targets ` | ` build_targets ` | ` codex-rs/hepta-bellman-operator/src/lib.rs ` | ` owner_native ` |
| ` build_sensor_core ` | ` build_sensor_core ` | ` build_sensor_core ` | ` codex-rs/hepta-bellman-operator/src/reference.rs ` | ` owner_native ` |
| ` evaluate_bellman_reference ` | ` evaluate_bellman_reference ` | ` evaluate_bellman_reference ` | ` codex-rs/hepta-bellman-operator/src/reference.rs ` | ` owner_native ` |
| ` validate_applicability_certificate ` | ` validate_applicability_certificate ` | ` validate_applicability_certificate ` | ` codex-rs/hepta-bellman-operator/src/reference.rs ` | ` owner_native ` |
| ` validate_applicability_with_signed_evidence_v2 ` | ` validate_applicability_with_signed_evidence_v2 ` | ` validate_applicability_with_signed_evidence_v2 ` | ` codex-rs/hepta-bellman-operator/src/authenticated.rs ` | ` owner_native ` |
| ` fit_tabular_operator ` | ` fit_tabular_operator ` | ` fit_tabular_operator ` | ` codex-rs/hepta-bellman-operator/src/learned.rs ` | ` owner_native ` |
| ` fit_tabular_operator_strict_v2 ` | ` fit_tabular_operator_strict_v2 ` | ` fit_tabular_operator_strict_v2 ` | ` codex-rs/hepta-bellman-operator/src/learned_strict.rs ` | ` owner_native ` |
| ` verify_tabular_operator_plan_v2 ` | ` verify_tabular_operator_plan_v2 ` | ` verify_tabular_operator_plan_v2 ` | ` codex-rs/hepta-bellman-operator/src/dataset_bound.rs ` | ` owner_native ` |
| ` fit_tabular_operator_verified_v2 ` | ` fit_tabular_operator_verified_v2 ` | ` fit_tabular_operator_verified_v2 ` | ` codex-rs/hepta-bellman-operator/src/dataset_bound.rs ` | ` owner_native ` |
| ` predict_tabular_operator ` | ` predict_tabular_operator ` | ` predict_tabular_operator ` | ` codex-rs/hepta-bellman-operator/src/learned.rs ` | ` owner_native ` |
| ` encode_tabular_payload_v1 ` | ` encode_tabular_payload_v1 ` | ` encode_tabular_payload_v1 ` | ` codex-rs/hepta-bellman-operator/src/loaded.rs ` | ` owner_native ` |
| ` load_pinned_tabular_operator_v1 ` | ` load_pinned_tabular_operator_v1 ` | ` LoadedTabularOperatorV1::from_pinned_payload ` | ` codex-rs/hepta-bellman-operator/src/loaded.rs ` | ` owner_native ` |
| ` admit_operator_regularity ` | ` admit_operator_regularity ` | ` admit_operator_regularity ` | ` codex-rs/hepta-bellman-operator/src/reference.rs ` | ` owner_native ` |
| ` admit_operator_regularity_with_signed_evidence_v2 ` | ` admit_operator_regularity_with_signed_evidence_v2 ` | ` admit_operator_regularity_with_signed_evidence_v2 ` | ` codex-rs/hepta-bellman-operator/src/authenticated.rs ` | ` owner_native ` |
| ` fit_transition_model ` | ` fit_transition_model ` | ` fit_transition_model ` | ` codex-rs/hepta-bellman-operator/src/world_model.rs ` | ` owner_native ` |
| ` verify_world_model_dataset_v2 ` | ` verify_world_model_dataset_v2 ` | ` verify_world_model_dataset_v2 ` | ` codex-rs/hepta-bellman-operator/src/dataset_bound.rs ` | ` owner_native ` |
| ` fit_transition_model_verified_v2 ` | ` fit_transition_model_verified_v2 ` | ` fit_transition_model_verified_v2 ` | ` codex-rs/hepta-bellman-operator/src/dataset_bound.rs ` | ` owner_native ` |
| ` predict_transition ` | ` predict_transition ` | ` predict_transition ` | ` codex-rs/hepta-bellman-operator/src/world_model.rs ` | ` owner_native ` |
| ` freeze_terminal_cell_from_owner_v1 ` | ` freeze_terminal_cell_from_owner_v1 ` | ` pub fn freeze_terminal_cell_from_owner_v1( ` | ` codex-rs/hepta-bellman-operator/src/owner_terminal.rs ` | ` owner_native ` |
| ` fit_terminal_cell_from_owner_v1 ` | ` fit_terminal_cell_from_owner_v1 ` | ` pub fn fit_terminal_cell_from_owner_v1( ` | ` codex-rs/hepta-bellman-operator/src/owner_terminal.rs ` | ` owner_native ` |

### operations 原文（20 项）

```json
[
  {
    "operation": "build_targets",
    "nativeSymbol": "build_targets",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/lib.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "build_targets",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "4ab6f3074524e87a66777e9dfbb34b1426adbe72"
  },
  {
    "operation": "build_sensor_core",
    "nativeSymbol": "build_sensor_core",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/reference.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "build_sensor_core",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f25b30be042dc7922311d8b43a3ade746a3b0df6"
  },
  {
    "operation": "evaluate_bellman_reference",
    "nativeSymbol": "evaluate_bellman_reference",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/reference.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "evaluate_bellman_reference",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f25b30be042dc7922311d8b43a3ade746a3b0df6"
  },
  {
    "operation": "validate_applicability_certificate",
    "nativeSymbol": "validate_applicability_certificate",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/reference.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "validate_applicability_certificate",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f25b30be042dc7922311d8b43a3ade746a3b0df6"
  },
  {
    "operation": "validate_applicability_with_signed_evidence_v2",
    "nativeSymbol": "validate_applicability_with_signed_evidence_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/authenticated.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "validate_applicability_with_signed_evidence_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b051815e3f38374fd4a3261d5e977de0a897e47c"
  },
  {
    "operation": "fit_tabular_operator",
    "nativeSymbol": "fit_tabular_operator",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/learned.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "fit_tabular_operator",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "893f0d5bf8f1313cd0c20fdd13ab50fad3257293"
  },
  {
    "operation": "fit_tabular_operator_strict_v2",
    "nativeSymbol": "fit_tabular_operator_strict_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/learned_strict.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "fit_tabular_operator_strict_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "63efa2f84b011b41d8a4bc58c24aced6cef2b873"
  },
  {
    "operation": "verify_tabular_operator_plan_v2",
    "nativeSymbol": "verify_tabular_operator_plan_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "verify_tabular_operator_plan_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8ac1e1cc98d989a64e45781aecfce968acc1af61"
  },
  {
    "operation": "fit_tabular_operator_verified_v2",
    "nativeSymbol": "fit_tabular_operator_verified_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "fit_tabular_operator_verified_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8ac1e1cc98d989a64e45781aecfce968acc1af61"
  },
  {
    "operation": "predict_tabular_operator",
    "nativeSymbol": "predict_tabular_operator",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/learned.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "predict_tabular_operator",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "893f0d5bf8f1313cd0c20fdd13ab50fad3257293"
  },
  {
    "operation": "encode_tabular_payload_v1",
    "nativeSymbol": "encode_tabular_payload_v1",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/loaded.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "encode_tabular_payload_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2f8452594305cf0d05ce1c034a33a6e004be55b2"
  },
  {
    "operation": "load_pinned_tabular_operator_v1",
    "nativeSymbol": "LoadedTabularOperatorV1::from_pinned_payload",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/loaded.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "load_pinned_tabular_operator_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2f8452594305cf0d05ce1c034a33a6e004be55b2"
  },
  {
    "operation": "admit_operator_regularity",
    "nativeSymbol": "admit_operator_regularity",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/reference.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "admit_operator_regularity",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f25b30be042dc7922311d8b43a3ade746a3b0df6"
  },
  {
    "operation": "admit_operator_regularity_with_signed_evidence_v2",
    "nativeSymbol": "admit_operator_regularity_with_signed_evidence_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/authenticated.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "admit_operator_regularity_with_signed_evidence_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b051815e3f38374fd4a3261d5e977de0a897e47c"
  },
  {
    "operation": "fit_transition_model",
    "nativeSymbol": "fit_transition_model",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/world_model.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "fit_transition_model",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "0c1494d4a627f1eeaffd8315a1cc4aed048ca7eb"
  },
  {
    "operation": "verify_world_model_dataset_v2",
    "nativeSymbol": "verify_world_model_dataset_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "verify_world_model_dataset_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8ac1e1cc98d989a64e45781aecfce968acc1af61"
  },
  {
    "operation": "fit_transition_model_verified_v2",
    "nativeSymbol": "fit_transition_model_verified_v2",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "fit_transition_model_verified_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8ac1e1cc98d989a64e45781aecfce968acc1af61"
  },
  {
    "operation": "predict_transition",
    "nativeSymbol": "predict_transition",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/world_model.rs",
    "state": "source_implemented_not_default_product_loop_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "predict_transition",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "0c1494d4a627f1eeaffd8315a1cc4aed048ca7eb"
  },
  {
    "operation": "freeze_terminal_cell_from_owner_v1",
    "designOperation": "freeze_terminal_cell_from_owner_v1",
    "nativeSymbol": "pub fn freeze_terminal_cell_from_owner_v1(",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/owner_terminal.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs::real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "a66b1b9098116911a79ffee154caa8c94e857ce2"
  },
  {
    "operation": "fit_terminal_cell_from_owner_v1",
    "designOperation": "fit_terminal_cell_from_owner_v1",
    "nativeSymbol": "pub fn fit_terminal_cell_from_owner_v1(",
    "sourcePath": "codex-rs/hepta-bellman-operator/src/owner_terminal.rs",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "tests": [
      "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs::real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal"
    ],
    "state": "source_implemented_bounded_candidate_profile_not_deployment_qualified",
    "authority": "none",
    "sourcePathExists": true,
    "sourceBlob": "a66b1b9098116911a79ffee154caa8c94e857ce2"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Compose the default dataset freeze -> verified training -> independent evaluation -> selection -> new-process load shadow loop.",
  "Obtain successful exact-head and deterministic synthetic-merge qualification receipts for this candidate.",
  "Execute the verified training and independent evidence regressions on the unified candidate."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent scientific and semantic review",
  "target-host training/inference measurements and real future-window efficacy",
  "operator acceptance, canary, promotion and release"
]
```

## 31. learning.eval

固定来源：[learning.eval](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.eval/IMPLEMENTATION_MAP.json)。Map Git blob：`b5f289e197c8ec541a922d24d54d6156437b29c6`。

owner：` learning-platform `；productCallerState：` product_qualification_receipt_consumed_by_evaluated_shadow `；productionWriterState：` qualification_evidence_sink_contract_composed_target_host_binding_unproved `。

### 操作导航（12 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` estimate_ope ` | ` estimate_ope ` | ` estimate_ope ` | ` codex-rs/hepta-intelligence-eval/src/ope.rs ` | ` owner_native ` |
| ` estimate_cluster_intervals ` | ` estimate_cluster_intervals ` | ` estimate_cluster_intervals ` | ` codex-rs/hepta-intelligence-eval/src/ope_confidence.rs ` | ` owner_native ` |
| ` estimate_sequential ` | ` estimate_sequential ` | ` estimate_sequential ` | ` codex-rs/hepta-intelligence-eval/src/sequential.rs ` | ` owner_native ` |
| ` evaluate_temporal_holdout ` | ` evaluate_temporal_holdout ` | ` evaluate_temporal_holdout ` | ` codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs ` | ` owner_native ` |
| ` freeze_product_evaluation_plan_v1 ` | ` freeze_product_evaluation_plan_v1 ` | ` freeze_product_evaluation_plan_v1 ` | ` codex-rs/hepta-intelligence-eval/src/product_runner.rs ` | ` owner_native ` |
| ` ProductEvaluationRunnerV1::evaluate_temporal_comparison ` | ` product_temporal_comparison ` | ` ProductEvaluationRunnerV1::evaluate_temporal_comparison ` | ` codex-rs/hepta-intelligence-eval/src/product_runner.rs ` | ` owner_native ` |
| ` ProductEvaluationRunnerV1::qualify_and_persist ` | ` product_signed_qualification ` | ` ProductEvaluationRunnerV1::qualify_and_persist ` | ` codex-rs/hepta-intelligence-eval/src/product_runner.rs ` | ` owner_native ` |
| ` FencedFinalHoldoutOwnerV1::consume ` | ` fenced_final_holdout_consume ` | ` FencedFinalHoldoutOwnerV1::consume ` | ` codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs ` | ` owner_native ` |
| ` LockedFileFinalHoldoutCasStoreV1 ` | ` locked_file_final_holdout_cas_store ` | ` LockedFileFinalHoldoutCasStoreV1 ` | ` codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs ` | ` owner_native ` |
| ` decide_with_signed_evidence_v2 ` | ` signed_v2_admission ` | ` decide_with_signed_evidence_v2 ` | ` codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs ` | ` owner_native ` |
| ` decide_with_signed_longitudinal_evidence_v3 ` | ` signed_v3_longitudinal_admission ` | ` decide_with_signed_longitudinal_evidence_v3 ` | ` codex-rs/hepta-intelligence-eval/src/longitudinal_time.rs ` | ` owner_native ` |
| ` run_evaluated_shadow_v1 ` | ` consume_product_qualification_receipt ` | ` codex_hepta_intelligence::run_evaluated_shadow_v1 ` | ` codex-rs/hepta-intelligence/src/evaluated_shadow.rs ` | ` delegated_product_consumer ` |

### operations 原文（12 项）

```json
[
  {
    "operation": "estimate_ope",
    "nativeSymbol": "estimate_ope",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/ope.rs",
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/ope_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "estimate_ope",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "52fb8b882012f2561c65a95639a63da8e2c12ff4"
  },
  {
    "operation": "estimate_cluster_intervals",
    "nativeSymbol": "estimate_cluster_intervals",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/ope_confidence.rs",
    "state": "source_implemented_sealed_receipt",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/ope_confidence_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "estimate_cluster_intervals",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/ope.rs",
        "symbol": "estimate_ope"
      }
    ],
    "sourceBlob": "1a6467723a7f1060178869f915b08286bcaeb502"
  },
  {
    "operation": "estimate_sequential",
    "nativeSymbol": "estimate_sequential",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/sequential.rs",
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/sequential_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "estimate_sequential",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "72d41fe1fd6c2710ba7873778d5b74140c89faa4"
  },
  {
    "operation": "evaluate_temporal_holdout",
    "nativeSymbol": "evaluate_temporal_holdout",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs",
    "state": "source_implemented_sealed_receipt",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/temporal_evaluation_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "evaluate_temporal_holdout",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/temporal_fold.rs",
        "symbol": "fit_temporal_fold"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval/src/ope_confidence.rs",
        "symbol": "estimate_cluster_intervals"
      }
    ],
    "sourceBlob": "1f6e4b9d675b235a91b4129fc27ff374fd796481"
  },
  {
    "operation": "freeze_product_evaluation_plan_v1",
    "nativeSymbol": "freeze_product_evaluation_plan_v1",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "state": "source_product_composition_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "freeze_product_evaluation_plan_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/metric_roles.rs",
        "symbol": "freeze_cross_fold_plan_v2"
      }
    ],
    "sourceBlob": "0c374acd8c5e25626c213c1ed9f6ba36d3fcbe42"
  },
  {
    "operation": "ProductEvaluationRunnerV1::evaluate_temporal_comparison",
    "nativeSymbol": "ProductEvaluationRunnerV1::evaluate_temporal_comparison",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "state": "source_product_composition_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "product_temporal_comparison",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs",
        "symbol": "FencedFinalHoldoutOwnerV1::consume"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "symbol": "FinalHoldoutProviderV1::release_after_consumption"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs",
        "symbol": "evaluate_temporal_holdout"
      }
    ],
    "sourceBlob": "0c374acd8c5e25626c213c1ed9f6ba36d3fcbe42"
  },
  {
    "operation": "ProductEvaluationRunnerV1::qualify_and_persist",
    "nativeSymbol": "ProductEvaluationRunnerV1::qualify_and_persist",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "state": "source_product_composition_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "product_signed_qualification",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs",
        "symbol": "decide_with_signed_evidence_v2"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval/src/longitudinal_time.rs",
        "symbol": "decide_with_signed_longitudinal_evidence_v3"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "symbol": "ProductQualificationEvidenceSinkV1::persist"
      }
    ],
    "sourceBlob": "0c374acd8c5e25626c213c1ed9f6ba36d3fcbe42"
  },
  {
    "operation": "FencedFinalHoldoutOwnerV1::consume",
    "nativeSymbol": "FencedFinalHoldoutOwnerV1::consume",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs",
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/fenced_holdout_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "fenced_final_holdout_consume",
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs",
        "symbol": "FinalHoldoutCasStoreV1::compare_and_swap"
      }
    ],
    "sourceBlob": "b46cb572492afa8646b92e5213ce9c47a4feaf7d"
  },
  {
    "operation": "LockedFileFinalHoldoutCasStoreV1",
    "nativeSymbol": "LockedFileFinalHoldoutCasStoreV1",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
    "state": "source_concrete_cas_backend_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "locked_file_final_holdout_cas_store",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b6a08ab16dfd972d293733fd34d798b024bf9403"
  },
  {
    "operation": "decide_with_signed_evidence_v2",
    "nativeSymbol": "decide_with_signed_evidence_v2",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs",
    "state": "source_implemented_low_level_signed_admission",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/closure_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "signed_v2_admission",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "35237acc5fa429dcd0eb5e8641a2dad33fa77667"
  },
  {
    "operation": "decide_with_signed_longitudinal_evidence_v3",
    "nativeSymbol": "decide_with_signed_longitudinal_evidence_v3",
    "sourcePath": "codex-rs/hepta-intelligence-eval/src/longitudinal_time.rs",
    "state": "source_implemented_pairwise_actor_separation",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence-eval/src/longitudinal_time_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "signed_v3_longitudinal_admission",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "a75053280ae55e6329eab4276034cbfebb8d23b3"
  },
  {
    "operation": "run_evaluated_shadow_v1",
    "nativeSymbol": "codex_hepta_intelligence::run_evaluated_shadow_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "state": "source_product_consumer_implemented",
    "authority": "deny_all",
    "tests": [
      "codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs",
      "codex-rs/hepta-intelligence/src/evaluated_shadow_segment_tests.rs"
    ],
    "sourcePathExists": true,
    "designOperation": "consume_product_qualification_receipt",
    "mappingClass": "delegated_product_consumer",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "symbol": "ProductQualificationReceiptV1::validate_integrity"
      }
    ],
    "sourceBlob": "51f32b736c9aa0bc067776b3b4ca9c80a3cb42aa"
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "Obtain passing exact-head and ordered-parent synthetic-merge learning.eval qualification artifacts for the final immutable candidate."
]
```

### externalEvidenceGates 原文（4 项）

```json
[
  "target-host authentication and durable binding for ProductQualificationEvidenceSinkV1 and final-holdout namespace",
  "real future-calendar windows, independent snapshots, retention/change-point/privacy/power and unlearning evidence",
  "cross-host storage qualification when LockedFileFinalHoldoutCasStoreV1 is used on a shared filesystem",
  "independent semantic/operator acceptance, selection, canary, promotion and release"
]
```

## 32. learning.artifacts

固定来源：[learning.artifacts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json)。Map Git blob：`faf4889729bd172bcdda255730c92f4abf439ab3`。

owner：` learning-platform `；productCallerState：` explicit_read_and_writer_service_composed `；productionWriterState：` named_owner_service_composed_source_qualification_pending `。

### 操作导航（25 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` artifact_registry_append ` | ` artifact_registry_append ` | ` ArtifactRegistry::append ` | ` codex-rs/hepta-learning-artifacts/src/registry.rs ` | ` owner_native ` |
| ` sensor_core_registry_read ` | ` sensor_core_registry_read ` | ` project_operator_sensor_core_registry_v1 ` | ` codex-rs/hepta-learning-artifacts/src/sensor_core_registry.rs ` | ` owner_native ` |
| ` write_candidate_payload ` | ` write_candidate_payload ` | ` write_candidate_payload_beneath ` | ` codex-rs/hepta-learning-artifacts/src/storage.rs ` | ` owner_native ` |
| ` load_pinned_candidate ` | ` load_pinned_candidate ` | ` load_pinned_candidate ` | ` codex-rs/hepta-learning-artifacts/src/pinned.rs ` | ` owner_native ` |
| ` revalidate_pinned_candidate ` | ` revalidate_pinned_candidate ` | ` RevalidatingCandidate::with_current ` | ` codex-rs/hepta-learning-artifacts/src/pinned.rs ` | ` owner_native ` |
| ` validate_manifest_v2 ` | ` validate_manifest_v2 ` | ` validate_artifact_manifest_v2 ` | ` codex-rs/hepta-learning-artifacts/src/closure_v2.rs ` | ` owner_native ` |
| ` withdrawal_append ` | ` withdrawal_append ` | ` DatasetWithdrawalRegistry::append ` | ` codex-rs/hepta-learning-artifacts/src/closure_v2.rs ` | ` owner_native ` |
| ` admit_manifest_at_withdrawal_head_v3 ` | ` admit_manifest_at_withdrawal_head_v3 ` | ` admit_manifest_at_withdrawal_head_v3 ` | ` codex-rs/hepta-learning-artifacts/src/admission_v3.rs ` | ` owner_native ` |
| ` publication_begin ` | ` publication_begin ` | ` ArtifactPublicationTransactionV1::begin ` | ` codex-rs/hepta-learning-artifacts/src/publication.rs ` | ` owner_native ` |
| ` publication_checkpoint ` | ` publication_checkpoint ` | ` LearningArtifactOwnerHost::recover_publication ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` authenticated_current_head ` | ` authenticated_current_head ` | ` LearningArtifactOwnerHost::discover_current_head ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` authenticated_current_registry_view ` | ` authenticated_current_registry_view ` | ` LearningArtifactOwnerService::current_registry_view ` | ` codex-rs/hepta-learning-artifacts/src/owner_service.rs ` | ` owner_native ` |
| ` owner_writer_fence ` | ` owner_writer_fence ` | ` LearningArtifactOwnerHost::open ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` lifecycle_journal_append ` | ` lifecycle_journal_append ` | ` ArtifactLifecycleJournalV2::append ` | ` codex-rs/hepta-learning-artifacts/src/lifecycle_journal.rs ` | ` owner_native ` |
| ` durable_withdrawal_snapshot ` | ` durable_withdrawal_snapshot ` | ` write_dataset_withdrawal_snapshot ` | ` codex-rs/hepta-learning-artifacts/src/durable_snapshots.rs ` | ` owner_native ` |
| ` durable_lifecycle_snapshot ` | ` durable_lifecycle_snapshot ` | ` write_artifact_lifecycle_snapshot ` | ` codex-rs/hepta-learning-artifacts/src/durable_snapshots.rs ` | ` owner_native ` |
| ` iteration_transition ` | ` iteration_transition ` | ` IterationLedgerV1::transition ` | ` codex-rs/hepta-learning-artifacts/src/iteration_ledger.rs ` | ` owner_native ` |
| ` owner_service_open ` | ` owner_service_open ` | ` LearningArtifactOwnerService::open ` | ` codex-rs/hepta-learning-artifacts/src/owner_service.rs ` | ` owner_native ` |
| ` owner_service_publish ` | ` owner_service_publish ` | ` LearningArtifactOwnerService::publish ` | ` codex-rs/hepta-learning-artifacts/src/owner_service.rs ` | ` owner_native ` |
| ` recover_current_registry ` | ` recover_current_registry ` | ` LearningArtifactOwnerHost::recover_current_registry ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` recover_registry_by_head ` | ` recover_registry_by_head ` | ` LearningArtifactOwnerHost::recover_registry_by_head ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` current_head_restart_anchor ` | ` current_head_restart_anchor ` | ` LearningArtifactOwnerHost::open_with_required_current_head ` | ` codex-rs/hepta-learning-artifacts/src/owner_host.rs ` | ` owner_native ` |
| ` independent_selection_verify ` | ` independent_selection_verify ` | ` ArtifactSelectionVerifierV1::verify ` | ` codex-rs/hepta-learning-artifacts/src/selection.rs ` | ` owner_native ` |
| ` record_verified_selection ` | ` record_verified_selection ` | ` record_verified_selection ` | ` codex-rs/hepta-learning-artifacts/src/selection.rs ` | ` owner_native ` |
| ` load_selected_candidate ` | ` load_selected_candidate ` | ` load_selected_candidate ` | ` codex-rs/hepta-learning-artifacts/src/selection.rs ` | ` owner_native ` |

### operations 原文（25 项）

```json
[
  {
    "operation": "artifact_registry_append",
    "nativeSymbol": "ArtifactRegistry::append",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/registry.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "artifact_registry_append",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "e723e3cf7c8e53ef59405bf71aa8cd4f5dc95f42"
  },
  {
    "operation": "sensor_core_registry_read",
    "nativeSymbol": "project_operator_sensor_core_registry_v1",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/sensor_core_registry.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "sensor_core_registry_read",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "58d629d83c697c66977f8f26db9e260d99d08c81"
  },
  {
    "operation": "write_candidate_payload",
    "nativeSymbol": "write_candidate_payload_beneath",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/storage.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "write_candidate_payload",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "d25f9e2a3070b3cf13aebfd5259611c4d66e1956"
  },
  {
    "operation": "load_pinned_candidate",
    "nativeSymbol": "load_pinned_candidate",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/pinned.rs",
    "state": "product_read_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "load_pinned_candidate",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "3a097702ef7294467e2a16b5ae8624b716372c41"
  },
  {
    "operation": "revalidate_pinned_candidate",
    "nativeSymbol": "RevalidatingCandidate::with_current",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/pinned.rs",
    "state": "product_read_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "revalidate_pinned_candidate",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "3a097702ef7294467e2a16b5ae8624b716372c41"
  },
  {
    "operation": "validate_manifest_v2",
    "nativeSymbol": "validate_artifact_manifest_v2",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "validate_manifest_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "49af2232566bf4c38380d88b7cf63e9b7975537a"
  },
  {
    "operation": "withdrawal_append",
    "nativeSymbol": "DatasetWithdrawalRegistry::append",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "withdrawal_append",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "49af2232566bf4c38380d88b7cf63e9b7975537a"
  },
  {
    "operation": "admit_manifest_at_withdrawal_head_v3",
    "nativeSymbol": "admit_manifest_at_withdrawal_head_v3",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/admission_v3.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "admit_manifest_at_withdrawal_head_v3",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "8e4f8830dbda3f387b54992f297c8d1f8baa329f"
  },
  {
    "operation": "publication_begin",
    "nativeSymbol": "ArtifactPublicationTransactionV1::begin",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/publication.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "publication_begin",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "eef46b0ab4d27214cad511ac2b0152a5b05a24b3"
  },
  {
    "operation": "publication_checkpoint",
    "nativeSymbol": "LearningArtifactOwnerHost::recover_publication",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "publication_checkpoint",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "authenticated_current_head",
    "nativeSymbol": "LearningArtifactOwnerHost::discover_current_head",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "authenticated_current_head",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "authenticated_current_registry_view",
    "nativeSymbol": "LearningArtifactOwnerService::current_registry_view",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "authenticated_current_registry_view",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1427589355efa2ea3ac12cc076d0e9a028b29f0b"
  },
  {
    "operation": "owner_writer_fence",
    "nativeSymbol": "LearningArtifactOwnerHost::open",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "owner_writer_fence",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "lifecycle_journal_append",
    "nativeSymbol": "ArtifactLifecycleJournalV2::append",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/lifecycle_journal.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "lifecycle_journal_append",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "afa6ee9f052def7d17e291bf0fcd4e483bf4e08f"
  },
  {
    "operation": "durable_withdrawal_snapshot",
    "nativeSymbol": "write_dataset_withdrawal_snapshot",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/durable_snapshots.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "durable_withdrawal_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f1e2bb61b6c5a8cff9b5742e2899f2dbde8b49bf"
  },
  {
    "operation": "durable_lifecycle_snapshot",
    "nativeSymbol": "write_artifact_lifecycle_snapshot",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/durable_snapshots.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "durable_lifecycle_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "f1e2bb61b6c5a8cff9b5742e2899f2dbde8b49bf"
  },
  {
    "operation": "iteration_transition",
    "nativeSymbol": "IterationLedgerV1::transition",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/iteration_ledger.rs",
    "state": "source_implemented",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "iteration_transition",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "a0b1fd3db118cba0498209e38ad650850270c807"
  },
  {
    "operation": "owner_service_open",
    "nativeSymbol": "LearningArtifactOwnerService::open",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "owner_service_open",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1427589355efa2ea3ac12cc076d0e9a028b29f0b"
  },
  {
    "operation": "owner_service_publish",
    "nativeSymbol": "LearningArtifactOwnerService::publish",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "owner_service_publish",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "1427589355efa2ea3ac12cc076d0e9a028b29f0b"
  },
  {
    "operation": "recover_current_registry",
    "nativeSymbol": "LearningArtifactOwnerHost::recover_current_registry",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "recover_current_registry",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "recover_registry_by_head",
    "nativeSymbol": "LearningArtifactOwnerHost::recover_registry_by_head",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "recover_registry_by_head",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "current_head_restart_anchor",
    "nativeSymbol": "LearningArtifactOwnerHost::open_with_required_current_head",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
    "state": "product_writer_service_composed",
    "authority": "none",
    "tests": [],
    "sourcePathExists": true,
    "designOperation": "current_head_restart_anchor",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "cdde5193d614f464f4b6b917a2eeffa3e1ee126b"
  },
  {
    "operation": "independent_selection_verify",
    "nativeSymbol": "ArtifactSelectionVerifierV1::verify",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/selection.rs",
    "state": "source_implemented_external_selector_authority_required",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-artifacts/src/selection.rs::art_12_independent_selector_binds_exact_current_and_manifest",
      "codex-rs/hepta-learning-artifacts/src/selection.rs::art_12_selection_rejects_self_selection_and_revoked_selector"
    ],
    "sourcePathExists": true,
    "designOperation": "independent_selection_verify",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "83bfc190f930409df01d099668370ad2d7578f7f"
  },
  {
    "operation": "record_verified_selection",
    "nativeSymbol": "record_verified_selection",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/selection.rs",
    "state": "source_implemented_external_selector_authority_required",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-learning-artifacts/src/selection.rs::art_12_verified_selection_records_only_selected_transition"
    ],
    "sourcePathExists": true,
    "designOperation": "record_verified_selection",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "83bfc190f930409df01d099668370ad2d7578f7f"
  },
  {
    "operation": "load_selected_candidate",
    "nativeSymbol": "load_selected_candidate",
    "sourcePath": "codex-rs/hepta-learning-artifacts/src/selection.rs",
    "state": "source_implemented_qualification_consumer_composed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-shadow-qualification/tests/support/tabular_reload.rs::existing_artifact_owner_new_process_predictions_and_revoked_rollback"
    ],
    "sourcePathExists": true,
    "designOperation": "load_selected_candidate",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "83bfc190f930409df01d099668370ad2d7578f7f"
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "Execute exact unified-candidate source binding, build and owner recovery qualification after cross-family composition."
]
```

### externalEvidenceGates 原文（4 项）

```json
[
  "independent semantic review",
  "target-host product execution and power-loss qualification",
  "production owner/selector trust provisioning and independent operator acceptance",
  "canary, promotion and release"
]
```

## 33. learning.plasticity

固定来源：[learning.plasticity](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json)。Map Git blob：`0237680471d75f9a3eb3f85606580a17f86e770c`。

owner：` learning-platform `；productCallerState：` agentd_process_bootstrap_and_named_learning_producer_source_composed_self_iteration_trigger_not_product_composed_or_target_host_qualified `；productionWriterState：` agentd_append_only_parameter_and_topology_anchor_fence_journal_plus_final_use_runtime_topology_executor_source_implemented_target_host_unproved `。

### 操作导航（27 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` propose_v2 ` | ` propose_v2 ` | ` propose_v2 ` | ` codex-rs/hepta-plasticity/src/parameter_v2.rs ` | ` owner_native ` |
| ` verify_parameter_proposal_v2 ` | ` verify_parameter_proposal_v2 ` | ` verify_parameter_proposal_v2 ` | ` codex-rs/hepta-plasticity/src/parameter_v2.rs ` | ` owner_native ` |
| ` generate_parameter_candidates_v3 ` | ` generate_parameter_candidates_v3 ` | ` generate_parameter_candidates_v3 ` | ` codex-rs/hepta-plasticity/src/generator_v3.rs ` | ` owner_native ` |
| ` verify_generated_parameter_candidates_v3 ` | ` verify_generated_parameter_candidates_v3 ` | ` verify_generated_parameter_candidates_v3 ` | ` codex-rs/hepta-plasticity/src/generator_v3.rs ` | ` owner_native ` |
| ` propose_topology_v2 ` | ` propose_topology_v2 ` | ` propose_topology_v2 ` | ` codex-rs/hepta-plasticity/src/topology_v2.rs ` | ` owner_native ` |
| ` verify_topology_proposal_v2 ` | ` verify_topology_proposal_v2 ` | ` verify_topology_proposal_v2 ` | ` codex-rs/hepta-plasticity/src/topology_v2.rs ` | ` owner_native ` |
| ` durableproposalregistry ` | ` durableproposalregistry ` | ` DurableProposalRegistry ` | ` codex-rs/hepta-plasticity/src/durable_registry.rs ` | ` owner_native ` |
| ` authenticated_product_composition ` | ` authenticated_product_composition ` | ` propose_authenticated_parameter_plasticity_v1 ` | ` codex-rs/hepta-intelligence/src/plasticity_product.rs ` | ` delegated_composition ` |
| ` anchored_product_writer ` | ` anchored_product_writer ` | ` AnchoredPlasticityWriterV1 ` | ` codex-rs/hepta-intelligence/src/plasticity_product.rs ` | ` delegated_composition ` |
| ` parameter_mutation_policy ` | ` parameter_mutation_policy ` | ` verify_parameter_mutation_policy_v1 ` | ` codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs ` | ` owner_native ` |
| ` agentd_process_bootstrap ` | ` agentd_process_bootstrap ` | ` load_plasticity_process_bootstrap_v1 ` | ` codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs ` | ` delegated_composition ` |
| ` agentd_plasticity_runtime_owner ` | ` agentd_plasticity_runtime_owner ` | ` PlasticityRuntimeOwnerV1 ` | ` codex-rs/hepta-agentd/src/plasticity_runtime.rs ` | ` delegated_composition ` |
| ` agentd_named_parameter_submission ` | ` agentd_named_parameter_submission ` | ` AgentdLearningPlasticityProducerV1::submit_parameter ` | ` codex-rs/hepta-agentd/src/plasticity_learning_producer.rs ` | ` delegated_composition ` |
| ` agentd_named_topology_submission ` | ` agentd_named_topology_submission ` | ` AgentdLearningPlasticityProducerV1::submit_topology ` | ` codex-rs/hepta-agentd/src/plasticity_learning_producer.rs ` | ` delegated_composition ` |
| ` agentd_parameter_host ` | ` agentd_parameter_host ` | ` propose_agentd_plasticity_v1 ` | ` codex-rs/hepta-agentd/src/plasticity_host.rs ` | ` delegated_composition ` |
| ` agentd_owner_evidence_resolution ` | ` agentd_owner_evidence_resolution ` | ` resolve_agentd_plasticity_owner_evidence_set_v1 ` | ` codex-rs/hepta-agentd/src/plasticity_host.rs ` | ` delegated_composition ` |
| ` concrete_owner_evidence_adapters ` | ` concrete_owner_evidence_adapters ` | ` ConcretePlasticityOwnerEvidenceResolverV1 ` | ` codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs ` | ` delegated_composition ` |
| ` topology_governed_admission ` | ` topology_governed_admission ` | ` admit_governed_topology_v1 ` | ` codex-rs/hepta-plasticity/src/topology_governance.rs ` | ` owner_native ` |
| ` durable_topology_registry ` | ` durable_topology_registry ` | ` DurableTopologyProposalRegistryV1 ` | ` codex-rs/hepta-plasticity/src/topology_registry.rs ` | ` owner_native ` |
| ` authenticated_topology_product_composition ` | ` authenticated_topology_product_composition ` | ` propose_authenticated_topology_plasticity_v1 ` | ` codex-rs/hepta-intelligence/src/topology_product.rs ` | ` delegated_composition ` |
| ` agentd_topology_host ` | ` agentd_topology_host ` | ` propose_agentd_topology_plasticity_v1 ` | ` codex-rs/hepta-agentd/src/topology_plasticity_host.rs ` | ` delegated_composition ` |
| ` agentd_anchor_fence_journal ` | ` agentd_anchor_fence_journal ` | ` AdaptiveAnchorJournalV1 ` | ` codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs ` | ` delegated_composition ` |
| ` structural_canary_controller ` | ` structural_canary_controller ` | ` StructuralCanaryControllerV1 ` | ` codex-rs/hepta-plasticity/src/topology_canary.rs ` | ` owner_native ` |
| ` authenticated_structural_canary_observation ` | ` authenticated_structural_canary_observation ` | ` observe_authenticated_structural_canary_v1 ` | ` codex-rs/hepta-intelligence/src/topology_canary_product.rs ` | ` delegated_composition ` |
| ` runtime_topology_execution ` | ` runtime_topology_execution ` | ` apply_governed_topology ` | ` codex-rs/hepta-runtime/src/lib.rs ` | ` delegated_composition ` |
| ` runtime_topology_recovery ` | ` runtime_topology_recovery ` | ` recover_governed_topology ` | ` codex-rs/hepta-runtime/src/lib.rs ` | ` delegated_composition ` |
| ` runtime_structural_canary_fault_rollback ` | ` runtime_structural_canary_fault_rollback ` | ` recover_governed_topology ` | ` codex-rs/hepta-runtime/src/lib.rs ` | ` delegated_composition ` |

### operations 原文（27 项）

```json
[
  {
    "operation": "propose_v2",
    "nativeSymbol": "propose_v2",
    "sourcePath": "codex-rs/hepta-plasticity/src/parameter_v2.rs",
    "state": "source_implemented_product_and_agentd_host_composed_not_target_host_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/lib_tests.rs::v2_matches_canonical_golden_vectors_and_grants_no_authority"
    ],
    "sourcePathExists": true,
    "designOperation": "propose_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "bfbfc27f8f4210ced8eee4210c6120e7cb8a2d00"
  },
  {
    "operation": "verify_parameter_proposal_v2",
    "nativeSymbol": "verify_parameter_proposal_v2",
    "sourcePath": "codex-rs/hepta-plasticity/src/parameter_v2.rs",
    "state": "source_implemented_product_and_agentd_host_composed_not_target_host_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/lib_tests.rs::read_validation_rejects_tampered_metrics_digest_and_profile"
    ],
    "sourcePathExists": true,
    "designOperation": "verify_parameter_proposal_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "bfbfc27f8f4210ced8eee4210c6120e7cb8a2d00"
  },
  {
    "operation": "generate_parameter_candidates_v3",
    "nativeSymbol": "generate_parameter_candidates_v3",
    "sourcePath": "codex-rs/hepta-plasticity/src/generator_v3.rs",
    "state": "source_implemented_agentd_host_composed_not_target_host_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/generator_v3.rs::tests::generator_is_deterministic_complete_and_content_identified"
    ],
    "sourcePathExists": true,
    "designOperation": "generate_parameter_candidates_v3",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "c201c954f302cc21fd82ae265cbf012debd57902"
  },
  {
    "operation": "verify_generated_parameter_candidates_v3",
    "nativeSymbol": "verify_generated_parameter_candidates_v3",
    "sourcePath": "codex-rs/hepta-plasticity/src/generator_v3.rs",
    "state": "source_implemented_agentd_host_composed_not_target_host_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/generator_v3.rs::tests::generator_is_deterministic_complete_and_content_identified"
    ],
    "sourcePathExists": true,
    "designOperation": "verify_generated_parameter_candidates_v3",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "c201c954f302cc21fd82ae265cbf012debd57902"
  },
  {
    "operation": "propose_topology_v2",
    "nativeSymbol": "propose_topology_v2",
    "sourcePath": "codex-rs/hepta-plasticity/src/topology_v2.rs",
    "state": "source_implemented_governed_durable_host_composed_not_applied",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/topology_v2.rs::tests::topology_v2_is_typed_deterministic_and_authority_free"
    ],
    "sourcePathExists": true,
    "designOperation": "propose_topology_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "07f89aed5d9c0162ed29f4b5feae6798883db6e2"
  },
  {
    "operation": "verify_topology_proposal_v2",
    "nativeSymbol": "verify_topology_proposal_v2",
    "sourcePath": "codex-rs/hepta-plasticity/src/topology_v2.rs",
    "state": "source_implemented_governed_durable_host_composed_not_applied",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/topology_v2.rs::tests::topology_verifier_rejects_duplicate_module_operation_with_drift"
    ],
    "sourcePathExists": true,
    "designOperation": "verify_topology_proposal_v2",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "07f89aed5d9c0162ed29f4b5feae6798883db6e2"
  },
  {
    "operation": "durableproposalregistry",
    "nativeSymbol": "DurableProposalRegistry",
    "sourcePath": "codex-rs/hepta-plasticity/src/durable_registry.rs",
    "state": "source_implemented_anchored_plus_explicit_zero_complete_frame_unacknowledged_bootstrap_recovery",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/durable_registry_tests.rs::append_reopen_and_anchor_preserve_exact_record",
      "codex-rs/hepta-plasticity/src/durable_registry_tests.rs::resume_unacknowledged_bootstrap_repairs_only_pre_frame_crash_state"
    ],
    "sourcePathExists": true,
    "designOperation": "durableproposalregistry",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "867fc7ee755b11819566afc369a03bc88d47023a"
  },
  {
    "operation": "authenticated_product_composition",
    "nativeSymbol": "propose_authenticated_parameter_plasticity_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "state": "adapter_implemented_called_by_long_lived_agentd_owner_pairwise_roles_and_durable_no_change_terminal_not_target_host_qualified",
    "authority": "proposal_append_only",
    "tests": [
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::authenticated_product_path_generates_evaluates_appends_and_commits_anchor",
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::product_path_rejects_generator_evaluator_controller_collision",
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::product_path_rejects_observer_evaluator_controller_collision",
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::durable_v2_evaluation_digest_binds_governed_admission_context",
      "codex-rs/hepta-learning-ledger/src/signed_evidence_tests.rs::observer_and_evaluator_require_pairwise_independence",
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::no_admissible_update_is_independently_attested_and_durably_recorded"
    ],
    "sourcePathExists": true,
    "designOperation": "authenticated_product_composition",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "7004ae2981587a63f9941376196af9435dbbdc6d"
  },
  {
    "operation": "anchored_product_writer",
    "nativeSymbol": "AnchoredPlasticityWriterV1",
    "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "state": "adapter_implemented_agentd_external_anchor_host_not_target_host_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::anchor_commit_failure_poison_writer_after_durable_append",
      "codex-rs/hepta-intelligence/src/plasticity_product.rs::tests::product_writer_refuses_unanchored_nonempty_bootstrap"
    ],
    "sourcePathExists": true,
    "designOperation": "anchored_product_writer",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [],
    "sourceBlob": "7004ae2981587a63f9941376196af9435dbbdc6d"
  },
  {
    "operation": "parameter_mutation_policy",
    "nativeSymbol": "verify_parameter_mutation_policy_v1",
    "sourcePath": "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs",
    "state": "source_implemented_typed_parameter_projection_bound_to_control_engineering_mutation_grammar",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs::tests::protected_surface_fails_closed",
      "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs::tests::canonical_mutation_grammar_digest_is_mandatory_and_bound"
    ],
    "sourcePathExists": true,
    "designOperation": "parameter_mutation_policy",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "faedfdd2e5ebe46e0227fb0cdd3b8b52a652b32a"
  },
  {
    "operation": "agentd_process_bootstrap",
    "nativeSymbol": "load_plasticity_process_bootstrap_v1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs",
    "state": "source_implemented_child_process_reconstructs_owner_native_stores_from_independent_receipts_not_target_host_qualified",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-agentd/tests/plasticity_process_e2e.rs::supervisor_exec_reconstructs_named_plasticity_owner_from_durable_descriptor",
      "codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs::tests::descriptor_digest_rejects_byte_substitution",
      "codex-rs/hepta-agentd/src/plasticity_process_bootstrap.rs::tests::mutable_owner_hardlink_alias_is_rejected"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_process_bootstrap",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-ndu",
        "module": "utility.ndu",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-neuron",
        "module": "neuron.runtime",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "f44c8858a55886c7997562a02ba87b9a7d359bf2"
  },
  {
    "operation": "agentd_plasticity_runtime_owner",
    "nativeSymbol": "PlasticityRuntimeOwnerV1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_runtime.rs",
    "state": "named_agentd_runtime_bootstrap_creates_long_lived_owner_and_state_held_producer_generation_fenced_bounded_queue_restart_reconcile_tested_not_target_host_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_runtime.rs::tests::runtime_queue_capacity_is_bounded",
      "codex-rs/hepta-agentd/src/plasticity_runtime_lifetime_tests.rs::agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_plasticity_runtime_owner",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "d1c57448d9c344171ae85d0abe888fe990e7a021"
  },
  {
    "operation": "agentd_named_parameter_submission",
    "nativeSymbol": "AgentdLearningPlasticityProducerV1::submit_parameter",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
    "state": "named_non_test_agentd_learning_producer_source_implemented_calls_state_submission_final_owner_revalidation_not_target_host_executed_or_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_runtime_lifetime_tests.rs::agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_named_parameter_submission",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-plasticity",
        "module": "learning.plasticity",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "507dc9a4e89399a3a67dc48c8f8b12f2a1a46a67"
  },
  {
    "operation": "agentd_named_topology_submission",
    "nativeSymbol": "AgentdLearningPlasticityProducerV1::submit_topology",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
    "state": "named_non_test_agentd_learning_topology_producer_source_implemented_calls_state_submission_final_owner_revalidation_not_target_host_executed_or_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_runtime_lifetime_tests.rs::agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_named_topology_submission",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-plasticity",
        "module": "learning.plasticity",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "507dc9a4e89399a3a67dc48c8f8b12f2a1a46a67"
  },
  {
    "operation": "agentd_parameter_host",
    "nativeSymbol": "propose_agentd_plasticity_v1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_host.rs",
    "state": "host_entrypoint_called_by_long_lived_agentd_owner_with_real_append_ack_crash_registry_only_rollback_rejection_not_target_host_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::anchor_store_fence_is_monotonic_and_reopen_preserves_acknowledged_state",
      "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs::authenticated_product_path_generates_evaluates_appends_and_commits_anchor",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::retained_external_anchor_blocks_rolled_back_registry_reopen",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::real_append_ack_crash_then_registry_rollback_is_rejected_on_restart"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_parameter_host",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-intelligence-eval",
        "module": "learning.eval",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "085d85fde32b89d59eb3169d8d8f6e7f005c2ac5"
  },
  {
    "operation": "agentd_owner_evidence_resolution",
    "nativeSymbol": "resolve_agentd_plasticity_owner_evidence_set_v1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_host.rs",
    "state": "host_enforced_live_frontier_exact_signal_value_owner_allowlist_and_dynamic_ndu_neuron_broadcast_resolution",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::owner_evidence_receipt_is_context_bound",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::owner_evidence_rejects_context_substitution",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::owner_evidence_set_includes_mutation_policy_and_canonical_kinds",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::owner_evidence_policy_rejects_authenticated_wrong_owner",
      "codex-rs/hepta-agentd/src/plasticity_host.rs::tests::owner_evidence_rejects_parameter_signal_value_substitution"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_owner_evidence_resolution",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-evidence",
        "module": "kernel.evidence",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "085d85fde32b89d59eb3169d8d8f6e7f005c2ac5"
  },
  {
    "operation": "concrete_owner_evidence_adapters",
    "nativeSymbol": "ConcretePlasticityOwnerEvidenceResolverV1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs",
    "state": "dataset_policy_ndu_neuron_broadcast_and_parameter_signal_adapters_bind_live_frontiers_and_exact_values_fail_closed",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs::tests::concrete_dataset_and_policy_adapters_bind_live_frontiers",
      "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs::tests::concrete_adapters_reject_rollback_frontiers_and_missing_dynamic_owner",
      "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs::tests::dynamic_owner_adapters_bind_ndu_neuron_broadcast_and_exact_signal_values",
      "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs::tests::dynamic_owner_adapters_reject_stale_wrong_owner_and_value_substitution",
      "codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs::tests::dynamic_owner_adapters_reject_ndu_rollback_and_unavailable_neuron_owner"
    ],
    "sourcePathExists": true,
    "designOperation": "concrete_owner_evidence_adapters",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "c3db02b42db094556889774b40306198292dc27e"
  },
  {
    "operation": "topology_governed_admission",
    "nativeSymbol": "admit_governed_topology_v1",
    "sourcePath": "codex-rs/hepta-plasticity/src/topology_governance.rs",
    "state": "source_implemented_typed_writer_handoff_validated",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/topology_governance.rs::tests::governed_topology_binds_exact_writer_handoff",
      "codex-rs/hepta-plasticity/src/topology_governance.rs::tests::writer_handoff_requires_distinct_owner_and_advancing_fence"
    ],
    "sourcePathExists": true,
    "designOperation": "topology_governed_admission",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "67293895c1de5d3edac98afcd1b8835317e3f656"
  },
  {
    "operation": "durable_topology_registry",
    "nativeSymbol": "DurableTopologyProposalRegistryV1",
    "sourcePath": "codex-rs/hepta-plasticity/src/topology_registry.rs",
    "state": "source_implemented_anchored_plus_explicit_zero_complete_frame_unacknowledged_bootstrap_recovery",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/topology_registry.rs::tests::topology_registry_reopen_and_old_idempotent_retry_preserve_original_frame",
      "codex-rs/hepta-plasticity/src/topology_registry.rs::tests::topology_resume_unacknowledged_bootstrap_repairs_only_pre_frame_crash_state"
    ],
    "sourcePathExists": true,
    "designOperation": "durable_topology_registry",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b108ad1c24514bf395733570493e6527cf71dfd4"
  },
  {
    "operation": "authenticated_topology_product_composition",
    "nativeSymbol": "propose_authenticated_topology_plasticity_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_product.rs",
    "state": "adapter_implemented_called_by_agentd_host_entrypoint_not_target_host_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-intelligence/src/topology_product.rs::tests::authenticated_topology_path_verifies_three_roles_and_persists_governed_record",
      "codex-rs/hepta-learning-ledger/src/signed_evidence_tests.rs::observer_and_evaluator_require_pairwise_independence"
    ],
    "sourcePathExists": true,
    "designOperation": "authenticated_topology_product_composition",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "e4d71ed863344823e5dcf4522375ad4cf1f1dd38"
  },
  {
    "operation": "agentd_topology_host",
    "nativeSymbol": "propose_agentd_topology_plasticity_v1",
    "sourcePath": "codex-rs/hepta-agentd/src/topology_plasticity_host.rs",
    "state": "host_entrypoint_called_by_long_lived_agentd_owner_external_anchor_not_target_host_qualified",
    "authority": "proposal_registry_only",
    "tests": [
      "codex-rs/hepta-agentd/src/topology_plasticity_host.rs::tests::topology_anchor_store_preserves_fence_and_anchor",
      "codex-rs/hepta-intelligence/src/topology_product.rs::tests::authenticated_topology_path_verifies_three_roles_and_persists_governed_record",
      "codex-rs/hepta-agentd/src/topology_plasticity_host.rs::tests::topology_real_append_ack_crash_then_registry_rollback_is_rejected_on_restart"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_topology_host",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-artifacts",
        "module": "learning.artifacts",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "a21aeb28e95cfaf19c1440ee4f32584f07c6ce36"
  },
  {
    "operation": "agentd_anchor_fence_journal",
    "nativeSymbol": "AdaptiveAnchorJournalV1",
    "sourcePath": "codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs",
    "state": "source_implemented_append_only_checksum_journal_crash_tail_repair_monotonic_generation_fences_and_safe_bootstrap_resume",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs::tests::journal_preserves_committed_anchor_across_reopen_and_generation_rollover",
      "codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs::tests::journal_repairs_only_an_incomplete_crash_tail",
      "codex-rs/hepta-agentd/src/plasticity_anchor_journal.rs::tests::journal_never_discards_a_complete_invalid_frame"
    ],
    "sourcePathExists": true,
    "designOperation": "agentd_anchor_fence_journal",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [],
    "sourceBlob": "cb2c3ae9bbb75c067c7745e82c33cded0e241baa"
  },
  {
    "operation": "structural_canary_controller",
    "nativeSymbol": "StructuralCanaryControllerV1",
    "sourcePath": "codex-rs/hepta-plasticity/src/topology_canary.rs",
    "state": "source_implemented_durable_candidate_plan_history_bound_observation_only_no_topology_apply_authority",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-plasticity/src/topology_canary.rs::tests::canary_accepts_only_after_bounded_success_and_verified_rollback",
      "codex-rs/hepta-plasticity/src/topology_canary.rs::tests::regression_budget_cannot_exceed_canary_horizon",
      "codex-rs/hepta-plasticity/src/topology_canary.rs::tests::any_safety_violation_aborts_terminally",
      "codex-rs/hepta-plasticity/src/topology_canary.rs::tests::receipt_binds_the_full_plan_and_observation_history",
      "qualification/lane-f-shadow/tests/plasticity_structural_canary.rs::pls3_governed_topology_persists_then_accepts_bounded_canary",
      "qualification/lane-f-shadow/tests/plasticity_structural_canary.rs::pls3_safety_violation_aborts_after_durable_admission"
    ],
    "sourcePathExists": true,
    "designOperation": "structural_canary_controller",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b7f02f34ff58006ba4e73afcf400c1cb27ed0d4e"
  },
  {
    "operation": "authenticated_structural_canary_observation",
    "nativeSymbol": "observe_authenticated_structural_canary_v1",
    "sourcePath": "codex-rs/hepta-intelligence/src/topology_canary_product.rs",
    "state": "source_implemented_observer_signature_binds_exact_plan_and_observation_no_topology_apply_authority",
    "authority": "none",
    "tests": [
      "codex-rs/hepta-intelligence/src/topology_canary_product.rs::tests::payload_binds_every_caller_asserted_canary_fact"
    ],
    "sourcePathExists": true,
    "designOperation": "authenticated_structural_canary_observation",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "52148b2b9968759782e76963eb16acc0b2e7c34d"
  },
  {
    "operation": "runtime_topology_execution",
    "nativeSymbol": "apply_governed_topology",
    "sourcePath": "codex-rs/hepta-runtime/src/lib.rs",
    "state": "source_implemented_external_final_use_exact_handoff_migration_owner_and_live_cns_replacement_not_target_host_qualified",
    "authority": "external_final_use_required",
    "tests": [
      "codex-rs/hepta-runtime/src/organs_tests.rs::governed_topology_requires_final_use_and_replaces_the_live_cns_generation",
      "codex-rs/hepta-runtime/src/organs_tests.rs::revoked_final_use_never_mutates_the_live_topology",
      "codex-rs/hepta-runtime/src/organs_tests.rs::topology_migration_owner_must_bind_exact_handoff_plan"
    ],
    "sourcePathExists": true,
    "designOperation": "runtime_topology_execution",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-contracts",
        "module": "kernel.authority",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-control-plane",
        "module": "control.runtime",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "a58dfaa26fb8544530603f0c14ca0339514b17bf"
  },
  {
    "operation": "runtime_topology_recovery",
    "nativeSymbol": "recover_governed_topology",
    "sourcePath": "codex-rs/hepta-runtime/src/lib.rs",
    "state": "source_implemented_external_recovery_final_use_exact_handoff_migration_owner_and_stopped_quarantined_forward_recovery_not_target_host_qualified",
    "authority": "external_recovery_final_use_required",
    "tests": [
      "codex-rs/hepta-runtime/src/organs_tests.rs::authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics"
    ],
    "sourcePathExists": true,
    "designOperation": "runtime_topology_recovery",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-contracts",
        "module": "kernel.authority",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-control-plane",
        "module": "control.runtime",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "a58dfaa26fb8544530603f0c14ca0339514b17bf"
  },
  {
    "operation": "runtime_structural_canary_fault_rollback",
    "nativeSymbol": "recover_governed_topology",
    "sourcePath": "codex-rs/hepta-runtime/src/lib.rs",
    "state": "qualification_composed_live_apply_with_migration_forced_stopped_host_fault_distinct_recovery_final_use_with_migration_rollforward_and_authenticated_observer_receipt_not_target_host_qualified",
    "authority": "external_final_use_required_for_apply_and_rollback",
    "tests": [
      "codex-rs/hepta-runtime/src/organs_tests.rs::authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics"
    ],
    "sourcePathExists": true,
    "designOperation": "runtime_structural_canary_fault_rollback",
    "mappingClass": "delegated_composition",
    "delegatedCallees": [
      {
        "path": "codex-rs/hepta-contracts",
        "module": "kernel.authority",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-learning-ledger",
        "module": "learning.ledger",
        "role": "declared_module_dependency_not_callsite_proof"
      },
      {
        "path": "codex-rs/hepta-plasticity",
        "module": "learning.plasticity",
        "role": "declared_module_dependency_not_callsite_proof"
      }
    ],
    "sourceBlob": "a58dfaa26fb8544530603f0c14ca0339514b17bf"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Compose a real non-test control.engineering/self-iteration coordinator that submits frozen, independently evaluated next-generation parameter/topology requests through AgentdLearningPlasticityProducerV1; the repository now has process bootstrap, the named producer and lifetime E2E, but IterationEnvelopeV1 still has no production caller.",
  "Run exact-head and deterministic synthetic-merge compilation, tests, strict lint, document verification, Agentd process qualification, Lane F qualification and the live-runtime structural-canary regression for this final source/document head.",
  "Execute exact unified-candidate descriptor recovery, proposal lifetime and independent live-topology canary tests."
]
```

### externalEvidenceGates 原文（5 项）

```json
[
  "independent semantic and security review",
  "target-host execution with the anchor/fence journal placed in a rollback domain physically independent from each proposal registry, plus crash/recovery telemetry",
  "operator acceptance and incident-recovery exercise",
  "target-host topology application with production telemetry and a forced-fault rollback/reconciliation canary; the repository now contains a live-runtime source qualification but not deployment evidence",
  "promotion, activation and release"
]
```

## 34. automation.taskflow

固定来源：[automation.taskflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json)。Map Git blob：`c30f3b653a41b13ca5e20b035b3667250ebe7301`。

owner：` automation-platform `；productCallerState：` agentd_app_server_and_capability_negotiated_calendar_v2_control_composed_external_effect_product_caller_pending `；productionWriterState：` automation_store_durable_schedule_occurrence_taskflow_owner_established `。

### 操作导航（4 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` register_schedule ` | ` register_schedule ` | ` pub async fn create_calendar_task_v2( ` | ` codex-rs/hepta-automation/src/schedule_v2.rs ` | ` owner_native ` |
| ` materialize_due ` | ` materialize_due ` | ` pub async fn tick( ` | ` codex-rs/hepta-automation/src/scheduler.rs ` | ` owner_native ` |
| ` claim_occurrence ` | ` claim_occurrence ` | ` pub async fn materialize_occurrence( ` | ` codex-rs/hepta-automation/src/lifecycle.rs ` | ` owner_native ` |
| ` execute_step ` | ` execute_step ` | ` pub async fn execute_authorized_taskflow_effect ` | ` codex-rs/hepta-automation/src/authorized_effect.rs ` | ` owner_native ` |

### operations 原文（4 项）

```json
[
  {
    "designOperation": "register_schedule",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-automation/src/schedule_v2.rs",
      "symbol": "pub async fn create_calendar_task_v2(",
      "buildTarget": "codex-hepta-automation"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-automation/src/schedule_v2.rs",
        "kind": "calendar_v2_dst_tzdb_revision",
        "command": "cargo test -p codex-hepta-automation"
      },
      {
        "path": "codex-rs/hepta-automation/tests/automation.rs",
        "kind": "legacy_schedule_compatibility",
        "command": "cargo test -p codex-hepta-automation"
      },
      {
        "path": "codex-rs/hepta-agentd/tests/five_agent_rolling_upgrade.rs",
        "kind": "real_agentd_calendar_v2_capability_negotiation_and_product_control",
        "command": "cargo test -p codex-hepta-agentd --test five_agent_rolling_upgrade five_real_agentd_processes_roll_one_agent_without_stopping_peers"
      }
    ],
    "sourceSemantics": "Persists append-only Calendar V2 revisions with explicit timezone/tzdb identity, start/end, DST gap/overlap policy and bounded recurrence while preserving Once/FixedInterval compatibility records; Agentd advertises automation.calendar_v2@1.0 and generation-fences the typed creation call.",
    "operation": "register_schedule",
    "nativeSymbol": "pub async fn create_calendar_task_v2(",
    "sourcePath": "codex-rs/hepta-automation/src/schedule_v2.rs",
    "sourcePathExists": true,
    "productCallers": [
      {
        "role": "product_control_dispatch",
        "path": "codex-rs/hepta-agentd/src/state_control.rs",
        "symbol": "AgentdMethod::AutomationCreateCalendarV2",
        "ownerModule": "runtime.agentd"
      },
      {
        "role": "typed_product_client",
        "path": "codex-rs/hepta-agentd/src/client.rs",
        "symbol": "pub async fn automation_create_calendar_v2(",
        "ownerModule": "runtime.agentd"
      }
    ],
    "sourceBlob": "efd8ce9d853b5fc17f7f71b639aea3f778c0fc6e"
  },
  {
    "designOperation": "materialize_due",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-automation/src/scheduler.rs",
      "symbol": "pub async fn tick(",
      "buildTarget": "codex-hepta-automation"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-automation/src/scheduler.rs",
        "kind": "scheduler_and_recovery",
        "command": "cargo test -p codex-hepta-automation"
      },
      {
        "path": "codex-rs/hepta-automation/src/schedule_v2.rs",
        "kind": "calendar_due_materialization",
        "command": "cargo test -p codex-hepta-automation"
      }
    ],
    "sourceSemantics": "Claims bounded due work, freezes schedule revision, derives canonical UTC occurrence identity from the authoritative schedule profile, and commits TaskFlow step intent before App Server or external-provider contact.",
    "operation": "materialize_due",
    "nativeSymbol": "pub async fn tick(",
    "sourcePath": "codex-rs/hepta-automation/src/scheduler.rs",
    "sourcePathExists": true,
    "sourceBlob": "4cd695be9113d4e8cd0d4100fa7451ef95be2351"
  },
  {
    "designOperation": "claim_occurrence",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-automation/src/lifecycle.rs",
      "symbol": "pub async fn materialize_occurrence(",
      "buildTarget": "codex-hepta-automation"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-automation/src/store.rs",
        "symbol": "pub async fn claim_due(",
        "ownerModule": "automation.taskflow",
        "buildTarget": "codex-hepta-automation"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-automation/tests/durable_causal_chain.rs",
        "kind": "deterministic_occurrence_and_generation_fence",
        "command": "cargo test -p codex-hepta-automation --test durable_causal_chain"
      },
      {
        "path": "codex-rs/hepta-automation/src/effect_dispatch_ledger.rs",
        "kind": "restart_reconciliation_identity",
        "command": "cargo test -p codex-hepta-automation"
      }
    ],
    "sourceSemantics": "Binds one due compatibility lease to a deterministic durable occurrence and generation/token fence; safe reclaim preserves occurrence/client identity, while unresolved provider contact remains quarantined.",
    "operation": "claim_occurrence",
    "nativeSymbol": "pub async fn materialize_occurrence(",
    "sourcePath": "codex-rs/hepta-automation/src/lifecycle.rs",
    "sourcePathExists": true,
    "sourceBlob": "4fd34632b554984ed193fa58ffa78a99efd937d2"
  },
  {
    "designOperation": "execute_step",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-automation/src/authorized_effect.rs",
      "symbol": "pub async fn execute_authorized_taskflow_effect",
      "buildTarget": "codex-hepta-automation"
    },
    "delegatedCallees": [
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-automation/src/taskflow_step.rs",
        "symbol": "pub async fn record_taskflow_step(",
        "ownerModule": "automation.taskflow",
        "buildTarget": "codex-hepta-automation"
      },
      {
        "role": "delegated_callee",
        "path": "codex-rs/hepta-automation/src/authorized_effect.rs",
        "symbol": "pub async fn execute_authorized_taskflow_effect_async",
        "ownerModule": "automation.taskflow",
        "buildTarget": "codex-hepta-automation"
      }
    ],
    "tests": [
      {
        "path": "codex-rs/hepta-automation/src/authorized_effect.rs",
        "kind": "canonical_final_use_intent_binding",
        "command": "cargo test -p codex-hepta-automation"
      },
      {
        "path": "codex-rs/hepta-automation/src/effect_dispatch_ledger.rs",
        "kind": "durable_indeterminate_terminal_reconciliation",
        "command": "cargo test -p codex-hepta-automation"
      },
      {
        "path": "codex-rs/hepta-automation/tests/durable_causal_chain.rs",
        "kind": "durable_step_and_terminal_propagation",
        "command": "cargo test -p codex-hepta-automation --test durable_causal_chain"
      },
      {
        "path": "codex-rs/hepta-automation/tests/authorized_effect.rs",
        "kind": "final_use_provider_at_most_once_and_recovery",
        "command": "cargo test -p codex-hepta-automation --test authorized_effect"
      }
    ],
    "sourceSemantics": "Computes the canonical typed effect-intent digest inside automation, verifies independently signed final-use subject/destination/scope/payload binding immediately around provider entry, appends an immutable provider-attempt row before contact, supports a synchronous driver and an async ProviderEffectAdapter bridge whose exact wire bytes are hashed before grant consumption, derives a provider-stable logical key from destination + TaskFlow run/step, and records initial plus terminal/proven-absent reconciliation evidence without blind redispatch.",
    "operation": "execute_step",
    "nativeSymbol": "pub async fn execute_authorized_taskflow_effect",
    "sourcePath": "codex-rs/hepta-automation/src/authorized_effect.rs",
    "sourcePathExists": true,
    "productCallers": [],
    "productCompositionState": "async_bridge_source_composed_named_independent_authority_provider_host_pending",
    "sourceBlob": "21db22ee30ffd50463b1721ef3fd8046ef5b3950"
  }
]
```

### repositoryControlledGaps 原文（0 项）

```json
[]
```

### externalEvidenceGates 原文（4 项）

```json
[
  "selected-host Agentd/App Server execution receipt for the composed durable causal path",
  "independently provisioned FinalUseAuthority signer/verifying-key/revocation-head configuration plus a concrete attested downstream effect provider and trusted terminal/reconciliation evidence for every activated external effect",
  "real IANA timezone-profile provenance/tzdb refresh plus DST and multi-scheduler target qualification",
  "independent acceptance, activation, promotion and release evidence"
]
```

## 35. channel.matrix

固定来源：[channel.matrix](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/channel.matrix/IMPLEMENTATION_MAP.json)。Map Git blob：`004297c8a80305edabc4b0994b031b042b943436`。

owner：` channels-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` admit_event ` | ` admit_event ` | ` pub async fn process_event( ` | ` codex-rs/hepta-matrixd/src/runtime.rs ` | ` owner_native ` |
| ` prepare_send ` | ` prepare_send ` | ` pub fn prepare_send( ` | ` codex-rs/hepta-matrixd/src/send_observer.rs ` | ` owner_native ` |
| ` observe_send ` | ` observe_send ` | ` pub fn observe_send( ` | ` codex-rs/hepta-matrixd/src/send_observer.rs ` | ` owner_native ` |

### operations 原文（3 项）

```json
[
  {
    "designOperation": "admit_event",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-matrixd/src/runtime.rs",
      "symbol": "pub async fn process_event(",
      "buildTarget": "codex-hepta-matrixd"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-matrixd/src/tests.rs",
        "kind": "runtime_ingress",
        "command": "just test -p codex-hepta-matrixd --lib"
      }
    ],
    "sourceSemantics": "Deduplicates enrolled-room events and advances the durable sync frontier with correction/redaction handling.",
    "operation": "admit_event",
    "nativeSymbol": "pub async fn process_event(",
    "sourcePath": "codex-rs/hepta-matrixd/src/runtime.rs",
    "sourcePathExists": true
  },
  {
    "designOperation": "prepare_send",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-matrixd/src/send_observer.rs",
      "symbol": "pub fn prepare_send(",
      "buildTarget": "codex-hepta-matrixd::send_observer"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-matrixd/src/send_observer_tests.rs",
        "kind": "send_identity",
        "command": "just test -p codex-hepta-matrixd --lib"
      }
    ],
    "sourceSemantics": "Binds room, session, payload, authority epoch, and one Matrix transaction identity before dispatch.",
    "operation": "prepare_send",
    "nativeSymbol": "pub fn prepare_send(",
    "sourcePath": "codex-rs/hepta-matrixd/src/send_observer.rs",
    "sourcePathExists": true
  },
  {
    "designOperation": "observe_send",
    "mappingClass": "owner_native",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "codex-rs/hepta-matrixd/src/send_observer.rs",
      "symbol": "pub fn observe_send(",
      "buildTarget": "codex-hepta-matrixd::send_observer"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "codex-rs/hepta-matrixd/src/send_observer_tests.rs",
        "kind": "acknowledgement_and_reconciliation",
        "command": "just test -p codex-hepta-matrixd --lib"
      }
    ],
    "sourceSemantics": "Records trusted server-event acknowledgement or preserves the same transaction as indeterminate for reconciliation.",
    "operation": "observe_send",
    "nativeSymbol": "pub fn observe_send(",
    "sourcePath": "codex-rs/hepta-matrixd/src/send_observer.rs",
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（1 项）

```json
[
  "Integrate any new send-observer state with the existing MatrixDurableStore transaction identity; the component alone is not a second durable sender."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "real enrolled homeserver/user/device/encryption identity",
  "live sync and send transport callsites",
  "rate-limit/reconnect/redaction/restore target qualification"
]
```

## 36. browser.servo

固定来源：[browser.servo](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/browser.servo/IMPLEMENTATION_MAP.json)。Map Git blob：`95232cb60bc15e0787122e49b12f0a451c58f8e1`。

owner：` browser-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` open_profile ` | ` open_profile ` | ` async openProfile( ` | ` apps/hepta-browser/src/runtime.js ` | ` owner_boundary ` |
| ` observe_page ` | ` observe_page ` | ` async observePage( ` | ` apps/hepta-browser/src/runtime.js ` | ` owner_boundary ` |
| ` navigate_or_act ` | ` navigate_or_act ` | ` async navigateOrAct( ` | ` apps/hepta-browser/src/runtime.js ` | ` owner_boundary ` |

### operations 原文（3 项）

```json
[
  {
    "designOperation": "open_profile",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-browser/src/runtime.js",
      "symbol": "async openProfile(",
      "buildTarget": "hepta-browser"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-browser/test/runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-browser/test/runtime.test.js"
      }
    ],
    "sourceSemantics": "Admits an isolated profile identity, allowed origins, effect grants, generation, and expiry before driver start.",
    "operation": "open_profile",
    "nativeSymbol": "async openProfile(",
    "sourcePath": "apps/hepta-browser/src/runtime.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "observe_page",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-browser/src/runtime.js",
      "symbol": "async observePage(",
      "buildTarget": "hepta-browser"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-browser/test/runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-browser/test/runtime.test.js"
      }
    ],
    "sourceSemantics": "Publishes bounded page observations with monotonic page generation and origin identity.",
    "operation": "observe_page",
    "nativeSymbol": "async observePage(",
    "sourcePath": "apps/hepta-browser/src/runtime.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "navigate_or_act",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-browser/src/runtime.js",
      "symbol": "async navigateOrAct(",
      "buildTarget": "hepta-browser"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-browser/test/runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-browser/test/runtime.test.js"
      }
    ],
    "sourceSemantics": "Revalidates page, destination, payload, authority, and operation identity before one driver effect.",
    "operation": "navigate_or_act",
    "nativeSymbol": "async navigateOrAct(",
    "sourcePath": "apps/hepta-browser/src/runtime.js",
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（0 项）

```json
[]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "reproducible Servo binary and patch digest",
  "OS sandbox/profile/credential/network enforcement",
  "real navigation/download/business terminal observation"
]
```

## 37. ui.control

固定来源：[ui.control](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/ui.control/IMPLEMENTATION_MAP.json)。Map Git blob：`69c29b168567252cb5f9d4c0a0892b6c6b8b4284`。

owner：` ui-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（3 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` read_view ` | ` read_view ` | ` readView() ` | ` apps/hepta-control-ui/src/runtime-client.js ` | ` owner_boundary ` |
| ` submit_request ` | ` submit_request ` | ` async submitRequest( ` | ` apps/hepta-control-ui/src/runtime-client.js ` | ` owner_boundary ` |
| ` request_stop ` | ` request_stop ` | ` async requestStop( ` | ` apps/hepta-control-ui/src/runtime-client.js ` | ` owner_boundary ` |

### operations 原文（3 项）

```json
[
  {
    "designOperation": "read_view",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-control-ui/src/runtime-client.js",
      "symbol": "readView()",
      "buildTarget": "hepta-control-ui"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-control-ui/test/runtime-client.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-control-ui/test/runtime-client.test.js"
      }
    ],
    "sourceSemantics": "Projects a coherent generation/revision snapshot and explicitly marks absent snapshots stale.",
    "operation": "read_view",
    "nativeSymbol": "readView()",
    "sourcePath": "apps/hepta-control-ui/src/runtime-client.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "submit_request",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-control-ui/src/runtime-client.js",
      "symbol": "async submitRequest(",
      "buildTarget": "hepta-control-ui"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-control-ui/test/runtime-client.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-control-ui/test/runtime-client.test.js"
      }
    ],
    "sourceSemantics": "Submits an authenticated request bound to displayed revision, operation identity, and semantic digest.",
    "operation": "submit_request",
    "nativeSymbol": "async submitRequest(",
    "sourcePath": "apps/hepta-control-ui/src/runtime-client.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "request_stop",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-control-ui/src/runtime-client.js",
      "symbol": "async requestStop(",
      "buildTarget": "hepta-control-ui"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-control-ui/test/runtime-client.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-control-ui/test/runtime-client.test.js"
      }
    ],
    "sourceSemantics": "Uses the same authenticated identity/revision path for stop while preserving backend terminality.",
    "operation": "request_stop",
    "nativeSymbol": "async requestStop(",
    "sourcePath": "apps/hepta-control-ui/src/runtime-client.js",
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（0 项）

```json
[]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "selected Web framework/build artifact and browser support matrix",
  "deployed authentication/CSP/CSRF/WebSocket topology",
  "end-to-end accessibility and backend deployment qualification"
]
```

## 38. ui.native

固定来源：[ui.native](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/ui.native/IMPLEMENTATION_MAP.json)。Map Git blob：`781dc2075b3f53e11a4160b51ca886af82dcc5ee`。

owner：` ui-platform `；productCallerState：` not_composed `；productionWriterState：` not_established `。

### 操作导航（4 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` connect_runtime ` | ` connect_runtime ` | ` async connectRuntime( ` | ` apps/hepta-native/src/shell-runtime.js ` | ` owner_boundary ` |
| ` render_runtime_view ` | ` render_runtime_view ` | ` renderRuntimeView( ` | ` apps/hepta-native/src/shell-runtime.js ` | ` owner_boundary ` |
| ` request_platform_capability ` | ` request_platform_capability ` | ` async requestPlatformCapability( ` | ` apps/hepta-native/src/shell-runtime.js ` | ` owner_boundary ` |
| ` apply_shell_update ` | ` apply_shell_update ` | ` async applyShellUpdate( ` | ` apps/hepta-native/src/shell-runtime.js ` | ` owner_boundary ` |

### operations 原文（4 项）

```json
[
  {
    "designOperation": "connect_runtime",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-native/src/shell-runtime.js",
      "symbol": "async connectRuntime(",
      "buildTarget": "hepta-native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-native/test/shell-runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-native/test/shell-runtime.test.js"
      }
    ],
    "sourceSemantics": "Authenticates endpoint manifest, protocol version, session identity, and process generation.",
    "operation": "connect_runtime",
    "nativeSymbol": "async connectRuntime(",
    "sourcePath": "apps/hepta-native/src/shell-runtime.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "render_runtime_view",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-native/src/shell-runtime.js",
      "symbol": "renderRuntimeView(",
      "buildTarget": "hepta-native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-native/test/shell-runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-native/test/shell-runtime.test.js"
      }
    ],
    "sourceSemantics": "Rejects mixed/regressed view generations and exposes one coherent presentation state.",
    "operation": "render_runtime_view",
    "nativeSymbol": "renderRuntimeView(",
    "sourcePath": "apps/hepta-native/src/shell-runtime.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "request_platform_capability",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-native/src/shell-runtime.js",
      "symbol": "async requestPlatformCapability(",
      "buildTarget": "hepta-native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-native/test/shell-runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-native/test/shell-runtime.test.js"
      }
    ],
    "sourceSemantics": "Requires both platform permission and final-payload-bound operation identity before invoking a narrow OS adapter.",
    "operation": "request_platform_capability",
    "nativeSymbol": "async requestPlatformCapability(",
    "sourcePath": "apps/hepta-native/src/shell-runtime.js",
    "sourcePathExists": true
  },
  {
    "designOperation": "apply_shell_update",
    "mappingClass": "owner_boundary",
    "ownerEntrypoint": {
      "role": "owner_entrypoint",
      "path": "apps/hepta-native/src/shell-runtime.js",
      "symbol": "async applyShellUpdate(",
      "buildTarget": "hepta-native"
    },
    "delegatedCallees": [],
    "tests": [
      {
        "path": "apps/hepta-native/test/shell-runtime.test.js",
        "kind": "node_product_boundary",
        "command": "node --test apps/hepta-native/test/shell-runtime.test.js"
      }
    ],
    "sourceSemantics": "Requires independent selection, signature/compatibility verification, explicit restart, and predecessor rollback on uncertain update.",
    "operation": "apply_shell_update",
    "nativeSymbol": "async applyShellUpdate(",
    "sourcePath": "apps/hepta-native/src/shell-runtime.js",
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（0 项）

```json
[]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "selected native framework and supported platform matrix",
  "real code signing/notarization/keychain and updater trust roots",
  "packaged crash/restart/accessibility/update rollback qualification"
]
```

## 39. control.runtime

固定来源：[control.runtime](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/control.runtime/IMPLEMENTATION_MAP.json)。Map Git blob：`b0183a3a3898c354d2fe18d43054b8cf3f341187`。

owner：` runtime-control `；productCallerState：` not_composed `；productionWriterState：` not_composed `。

### 操作导航（6 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` collect_snapshot ` | ` collect_snapshot ` | ` codex_hepta_control_plane::collect_snapshot ` | ` codex-rs/hepta-control-plane/src/planner.rs ` | ` owner_native ` |
| ` prepare_plan ` | ` prepare_plan ` | ` codex_hepta_control_plane::prepare_plan ` | ` codex-rs/hepta-control-plane/src/planner.rs ` | ` owner_native ` |
| ` bind_ndu_plan_evaluation_v1 ` | ` bind_ndu_plan_evaluation_v1 ` | ` codex_hepta_control_plane::bind_ndu_plan_evaluation_v1 ` | ` codex-rs/hepta-control-plane/src/planner.rs ` | ` owner_native ` |
| ` finalize_plan ` | ` finalize_plan ` | ` codex_hepta_control_plane::finalize_plan ` | ` codex-rs/hepta-control-plane/src/planner.rs ` | ` owner_native ` |
| ` request_execution_grants ` | ` request_execution_grants ` | ` codex_hepta_control_plane::request_execution_grants ` | ` codex-rs/hepta-control-plane/src/planner.rs ` | ` owner_native ` |
| ` PlannerJournalV1 ` | ` PlannerJournalV1 ` | ` codex_hepta_control_plane::PlannerJournalV1 ` | ` codex-rs/hepta-control-plane/src/planner_journal.rs ` | ` owner_native ` |

### operations 原文（6 项）

```json
[
  {
    "operation": "collect_snapshot",
    "nativeSymbol": "codex_hepta_control_plane::collect_snapshot",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner.rs",
    "inputs": [
      "SnapshotRequestV1",
      "OwnerSummaryV1 list"
    ],
    "outputs": [
      "GlobalStateSnapshotV1"
    ],
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "missing_or_stale_required_owner_blocks_global_planning"
      }
    ],
    "designOperation": "collect_snapshot",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  },
  {
    "operation": "prepare_plan",
    "nativeSymbol": "codex_hepta_control_plane::prepare_plan",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner.rs",
    "inputs": [
      "GlobalStateSnapshotV1",
      "PlanningRequestV1"
    ],
    "outputs": [
      "PreparedPlanInputV1"
    ],
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "essential_floor_survives_overload_before_ndu_evaluation"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "missing_resource_axis_is_unavailable_not_zero_cost"
      }
    ],
    "designOperation": "prepare_plan",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  },
  {
    "operation": "bind_ndu_plan_evaluation_v1",
    "nativeSymbol": "codex_hepta_control_plane::bind_ndu_plan_evaluation_v1",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner.rs",
    "inputs": [
      "NduPlanEvaluationInputV1"
    ],
    "outputs": [
      "NduPlanEvaluationV1"
    ],
    "state": "source_implemented_owner_port_adapter",
    "authority": "deny_all",
    "ownerBoundary": "utility.ndu computes the opaque evaluation digest; control.runtime binds only the consumed projection",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "tampered_ndu_binding_is_rejected"
      }
    ],
    "designOperation": "bind_ndu_plan_evaluation_v1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  },
  {
    "operation": "finalize_plan",
    "nativeSymbol": "codex_hepta_control_plane::finalize_plan",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner.rs",
    "inputs": [
      "GlobalStateSnapshotV1",
      "PreparedPlanInputV1",
      "NduPlanEvaluationV1",
      "current monotonic time"
    ],
    "outputs": [
      "FeasiblePlanReceiptV1"
    ],
    "state": "source_implemented",
    "authority": "deny_all",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "coherent_snapshot_prepares_finalizes_and_emits_authority_free_grant_requests"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "evaluation_must_cover_exact_prepared_candidate_set"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "evaluation_policy_is_frozen_before_ndu_evaluation"
      }
    ],
    "designOperation": "finalize_plan",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  },
  {
    "operation": "request_execution_grants",
    "nativeSymbol": "codex_hepta_control_plane::request_execution_grants",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner.rs",
    "inputs": [
      "current GlobalStateSnapshotV1",
      "PreparedPlanInputV1",
      "FeasiblePlanReceiptV1",
      "current monotonic time"
    ],
    "outputs": [
      "GrantRequestSetV1"
    ],
    "state": "source_implemented_request_only",
    "authority": "deny_all",
    "nonClaim": "GrantRequestSetV1 is not a capability or execution acknowledgement",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "changed_configuration_invalidates_prepared_plan"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "tampered_candidate_payload_is_rejected_before_grant_request"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "tampered_candidate_operation_resource_or_owner_is_rejected"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_tests.rs",
        "symbol": "grant_request_revalidates_snapshot_masks_and_digest"
      }
    ],
    "designOperation": "request_execution_grants",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  },
  {
    "operation": "PlannerJournalV1",
    "nativeSymbol": "codex_hepta_control_plane::PlannerJournalV1",
    "sourcePath": "codex-rs/hepta-control-plane/src/planner_journal.rs",
    "inputs": [
      "snapshot, decision, selection and revocation records"
    ],
    "outputs": [
      "bounded hash-chain bytes",
      "selected plan projection"
    ],
    "state": "source_implemented_owner_local_durability_reference",
    "authority": "none",
    "nonClaim": "not an activated production store or external-effect ledger",
    "tests": [
      {
        "path": "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
        "symbol": "hash_chain_round_trips_and_preserves_selected_pointer"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
        "symbol": "truncation_and_tampering_fail_closed"
      },
      {
        "path": "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
        "symbol": "revocation_clears_selection_and_prevents_reselection"
      }
    ],
    "designOperation": "PlannerJournalV1",
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourcePathExists": true
  }
]
```

### repositoryControlledGaps 原文（2 项）

```json
[
  "Bind every operation to an authenticated consumer callsite and owner store.",
  "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review",
  "product execution and target-host qualification",
  "operator acceptance, canary, promotion and release"
]
```

## 40. control.engineering

固定来源：[control.engineering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/797116d61cf422c26274ffef31297dce84a53a80/docs/modules/control.engineering/IMPLEMENTATION_MAP.json)。Map Git blob：`f81f0f0dc211a6e35d606ba9bda66c0b3da6e2a2`。

owner：` developer-productivity `；productCallerState：` repository_product_caller_dual_lane_defined_execution_pending `；productionWriterState：` named_product_owner_composed_execution_pending `。

### 操作导航（25 项）

| operation | designOperation | nativeSymbol | sourcePath | mappingClass |
| --- | --- | --- | --- | --- |
| ` issue_repository_work_envelope ` | ` issue_work_envelope ` | ` issue_repository_work_envelope ` | ` tools/hepta-engineering-control/control_engineering_v2/orchestration.py ` | ` owner_native ` |
| ` plan_engineering_work ` | ` schedule_ready_packages ` | ` plan_engineering_work ` | ` tools/hepta-engineering-control/control_engineering_v2/orchestration.py ` | ` owner_native ` |
| ` generate_candidates ` | ` generate_candidate ` | ` generate_candidates ` | ` tools/hepta-engineering-control/control_engineering_v2/candidate.py ` | ` owner_native ` |
| ` sandbox_candidate ` | ` execute_candidate_sandbox ` | ` sandbox_candidate ` | ` tools/hepta-engineering-control/control_engineering_v2/candidate.py ` | ` owner_native ` |
| ` run_mutation_testing ` | ` mutation_testing ` | ` run_mutation_testing ` | ` tools/hepta-engineering-control/control_engineering_v2/mutation_testing.py ` | ` owner_native ` |
| ` verify_integration_evidence ` | ` verify_integration_evidence ` | ` verify_integration_evidence ` | ` tools/hepta-engineering-control/control_engineering_v2/evidence.py ` | ` owner_native ` |
| ` record_integration_decision ` | ` record_integration_decision ` | ` record_integration_decision ` | ` tools/hepta-engineering-control/control_engineering_v2/seal.py ` | ` owner_native ` |
| ` admit_distributed_fence ` | ` production_distributed_fence_admission ` | ` admit_distributed_fence ` | ` tools/hepta-engineering-control/control_engineering_v2/external_controls.py ` | ` owner_native ` |
| ` verify_production_controls ` | ` production_control_admission ` | ` verify_production_controls ` | ` tools/hepta-engineering-control/control_engineering_v2/external_controls.py ` | ` owner_native ` |
| ` build_product_receipt ` | ` repository_product_caller ` | ` build_product_receipt ` | ` tools/hepta-engineering-control/control_engineering_v2/product_gate.py ` | ` owner_native ` |
| ` claim_assignment ` | ` durable_worker_assignment_lifecycle ` | ` claim_assignment ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` observe_claim_completion ` | ` durable_worker_completion_observation ` | ` observe_claim_completion ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` submit_worker_result ` | ` durable_worker_result ` | ` submit_worker_result ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` heartbeat_claim ` | ` durable_worker_heartbeat ` | ` heartbeat_claim ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` register_worker ` | ` durable_worker_registration ` | ` register_worker ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` EngineeringControlProduct ` | ` named_product_owner_composition ` | ` EngineeringControlProduct ` | ` tools/hepta-engineering-control/control_engineering_v2/product_runtime.py ` | ` owner_native ` |
| ` publish_integration_queue ` | ` durable_integration_queue_publication ` | ` publish_integration_queue ` | ` tools/hepta-engineering-control/control_engineering_v2/integration_controller.py ` | ` owner_native ` |
| ` observe_integration_stage ` | ` authenticated_integration_stage_reconciliation ` | ` observe_integration_stage ` | ` tools/hepta-engineering-control/control_engineering_v2/integration_controller.py ` | ` owner_native ` |
| ` reconcile_integration_item ` | ` durable_integration_terminal_reconciliation ` | ` reconcile_integration_item ` | ` tools/hepta-engineering-control/control_engineering_v2/integration_controller.py ` | ` owner_native ` |
| ` bind_github_review_observations ` | ` github_reviewer_identity_observation ` | ` bind_github_review_observations ` | ` tools/hepta-engineering-control/control_engineering_v2/product_gate.py ` | ` owner_native ` |
| ` validate_engineering_store_schema ` | ` validate_engineering_store_schema ` | ` EngineeringStore._validate_schema_objects ` | ` tools/hepta-engineering-control/control_engineering_v2/control_plane.py ` | ` owner_native ` |
| ` reserve_worker_capacity ` | ` reserve_worker_capacity ` | ` worker_capacity_usage ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` recover_worker_lifecycle ` | ` recover_worker_lifecycle ` | ` recover_worker_lifecycle ` | ` tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py ` | ` owner_native ` |
| ` integration_context_binding ` | ` bind_integration_observation_context ` | ` integration_context_binding ` | ` tools/hepta-engineering-control/control_engineering_v2/integration_controller.py ` | ` owner_native ` |
| ` build_host_profile ` | ` measure_target_host_profile ` | ` build_host_profile ` | ` tools/hepta-engineering-control/control_engineering_v2/qualification_profile.py ` | ` owner_native ` |

### operations 原文（25 项）

```json
[
  {
    "operation": "issue_repository_work_envelope",
    "designOperation": "issue_work_envelope",
    "nativeSymbol": "issue_repository_work_envelope",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_orchestration.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore.issue_work_envelope",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "c745e071a2e669d5e1d984c03b92dd1f13ae1e54"
  },
  {
    "operation": "plan_engineering_work",
    "designOperation": "schedule_ready_packages",
    "nativeSymbol": "plan_engineering_work",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_orchestration.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore._transaction",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/hardening.py",
        "symbol": "bind_assignment_frontier",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "c745e071a2e669d5e1d984c03b92dd1f13ae1e54"
  },
  {
    "operation": "generate_candidates",
    "designOperation": "generate_candidate",
    "nativeSymbol": "generate_candidates",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/candidate.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_candidate_changeset.py"
      },
      {
        "path": "tools/hepta-engineering-control/test_candidate_policy.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2e227293eb8359ca7df7c7397df3621c9641927c"
  },
  {
    "operation": "sandbox_candidate",
    "designOperation": "execute_candidate_sandbox",
    "nativeSymbol": "sandbox_candidate",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/candidate.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_candidate_sandbox_hardening.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "2e227293eb8359ca7df7c7397df3621c9641927c"
  },
  {
    "operation": "run_mutation_testing",
    "designOperation": "mutation_testing",
    "nativeSymbol": "run_mutation_testing",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/mutation_testing.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_mutation_testing.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/sandbox_control.py",
        "symbol": "SandboxCoordinator.execute",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "60fef0290956f7f064c8e61264cc10e5cfdd2702"
  },
  {
    "operation": "verify_integration_evidence",
    "designOperation": "verify_integration_evidence",
    "nativeSymbol": "verify_integration_evidence",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/evidence.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_control_engineering_v2.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "b3022b17f6a4310a27f6a1355af9305164a86fd0"
  },
  {
    "operation": "record_integration_decision",
    "designOperation": "record_integration_decision",
    "nativeSymbol": "record_integration_decision",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/seal.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_lane_g_seal.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore.record_integration_decision",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "dac5309812dc6a885d64524b48842f04414f40c8"
  },
  {
    "operation": "admit_distributed_fence",
    "designOperation": "production_distributed_fence_admission",
    "nativeSymbol": "admit_distributed_fence",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
    "state": "source_implemented_external_receipts_required",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_external_controls.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore._transaction",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore._append_audit",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "b1788c4917818c7afe12e0be4e4e54fe3c3f1a45"
  },
  {
    "operation": "verify_production_controls",
    "designOperation": "production_control_admission",
    "nativeSymbol": "verify_production_controls",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
    "state": "source_implemented_external_receipts_required",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_external_controls.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
        "symbol": "verify_persisted_distributed_fence",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
        "symbol": "verify_external_audit_anchor",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
        "symbol": "verify_external_key_custody",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "b1788c4917818c7afe12e0be4e4e54fe3c3f1a45"
  },
  {
    "operation": "build_product_receipt",
    "designOperation": "repository_product_caller",
    "nativeSymbol": "build_product_receipt",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/product_gate.py",
    "state": "repository_product_caller_v4_fixture_execution_dual_lane_pending",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_product_gate.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
        "symbol": "plan_engineering_work",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
        "symbol": "issue_repository_work_envelope",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "register_worker",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore.acquire_path_lease",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "claim_assignment",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "heartbeat_claim",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "submit_worker_result",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "observe_claim_completion",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "publish_integration_queue",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "observe_integration_stage",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "recover_worker_lifecycle",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "integration_context_binding",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "reconcile_integration_item",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "116c174b144b23548c238f9f264cb9f7e01b12f6"
  },
  {
    "operation": "claim_assignment",
    "designOperation": "durable_worker_assignment_lifecycle",
    "nativeSymbol": "claim_assignment",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "orchestration_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "path_leases",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_registrations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_claims",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_heartbeat_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_result_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_completion_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_capacity_reservations",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "observe_claim_completion",
    "designOperation": "durable_worker_completion_observation",
    "nativeSymbol": "observe_claim_completion",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_claims",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_completion_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "assignment_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "submit_worker_result",
    "designOperation": "durable_worker_result",
    "nativeSymbol": "submit_worker_result",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_claims",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_result_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "heartbeat_claim",
    "designOperation": "durable_worker_heartbeat",
    "nativeSymbol": "heartbeat_claim",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_claims",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_heartbeat_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_registrations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "register_worker",
    "designOperation": "durable_worker_registration",
    "nativeSymbol": "register_worker",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_registrations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "EngineeringControlProduct",
    "designOperation": "named_product_owner_composition",
    "nativeSymbol": "EngineeringControlProduct",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py",
    "state": "source_implemented_fixture_execution_pending",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_product_runtime.py"
      },
      {
        "path": "tools/hepta-engineering-control/test_product_gate.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
        "symbol": "plan_engineering_work",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "claim_assignment",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "observe_claim_completion",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "register_worker",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore.acquire_path_lease",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "heartbeat_claim",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "submit_worker_result",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "publish_integration_queue",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "observe_integration_stage",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_completion_observations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "recover_worker_lifecycle",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "worker_capacity_usage",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "integration_context_binding",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_capacity_reservations",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "e79b6a00d04d72e21f23f45046e22300c24724e7"
  },
  {
    "operation": "publish_integration_queue",
    "designOperation": "durable_integration_queue_publication",
    "nativeSymbol": "publish_integration_queue",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_integration_controller.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "orchestration_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_items",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "4161735b10d881bda82dce3bd05b331e72bddb02"
  },
  {
    "operation": "observe_integration_stage",
    "designOperation": "authenticated_integration_stage_reconciliation",
    "nativeSymbol": "observe_integration_stage",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
    "state": "source_implemented_authenticated_stage_boundary",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_integration_controller.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "reconcile_integration_item",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_items",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "symbol": "integration_context_binding",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "4161735b10d881bda82dce3bd05b331e72bddb02"
  },
  {
    "operation": "reconcile_integration_item",
    "designOperation": "durable_integration_terminal_reconciliation",
    "nativeSymbol": "reconcile_integration_item",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
    "state": "source_implemented_internal_product_callee",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_integration_controller.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_items",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "audit_events",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "4161735b10d881bda82dce3bd05b331e72bddb02"
  },
  {
    "operation": "bind_github_review_observations",
    "designOperation": "github_reviewer_identity_observation",
    "nativeSymbol": "bind_github_review_observations",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/product_gate.py",
    "state": "source_implemented_live_ci_execution_pending",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_product_gate.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [],
    "sourceBlob": "116c174b144b23548c238f9f264cb9f7e01b12f6"
  },
  {
    "operation": "validate_engineering_store_schema",
    "designOperation": "validate_engineering_store_schema",
    "nativeSymbol": "EngineeringStore._validate_schema_objects",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_consolidated_engineering.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "engineering_schema_meta",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore._validate_store_integrity",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore._verify_capacity_reservations",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "cc02bfc1201096d60b66014d97d53b79e1499d60"
  },
  {
    "operation": "reserve_worker_capacity",
    "designOperation": "reserve_worker_capacity",
    "nativeSymbol": "worker_capacity_usage",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_capacity_reservations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "claim_assignment",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "_release_capacity_reservation",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "recover_worker_lifecycle",
    "designOperation": "recover_worker_lifecycle",
    "nativeSymbol": "recover_worker_lifecycle",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
    "state": "source_implemented_product_execution_pending",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_product_runtime.py"
      },
      {
        "path": "tools/hepta-engineering-control/test_worker_lifecycle.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_claims",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "worker_capacity_reservations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "path_leases",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "10fba38fc3f69270f898b953894ebd5c965f0abc"
  },
  {
    "operation": "integration_context_binding",
    "designOperation": "bind_integration_observation_context",
    "nativeSymbol": "integration_context_binding",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
    "state": "source_implemented_authenticated_stage_boundary",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_integration_controller.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "integration_queue_items",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "orchestration_generations",
        "role": "schema_reference"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "symbol": "work_envelopes",
        "role": "schema_reference"
      }
    ],
    "sourceBlob": "4161735b10d881bda82dce3bd05b331e72bddb02"
  },
  {
    "operation": "build_host_profile",
    "designOperation": "measure_target_host_profile",
    "nativeSymbol": "build_host_profile",
    "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/qualification_profile.py",
    "state": "source_implemented_live_ci_execution_pending",
    "authority": "none",
    "tests": [
      {
        "path": "tools/hepta-engineering-control/test_qualification_profile.py"
      }
    ],
    "sourcePathExists": true,
    "mappingClass": "owner_native",
    "delegatedCallees": [
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "symbol": "EngineeringStore",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "symbol": "recover_worker_lifecycle",
        "role": "source_declaration"
      },
      {
        "path": "tools/hepta-engineering-control/control_engineering_v2/sandbox_control.py",
        "symbol": "SandboxCoordinator",
        "role": "source_declaration"
      }
    ],
    "sourceBlob": "697270c8421503a6313e4bfb4b878843de65fc2a"
  }
]
```

### repositoryControlledGaps 原文（3 项）

```json
[
  "Observe successful exact-source and deterministic synthetic-merge runs of the repository product caller before changing the product-execution claim boundary.",
  "Retain strong Linux/Bubblewrap, mutation-testing and sandbox-controller receipts for the exact candidate.",
  "Product execution receipts prove the full composed path with explicit CI reference fixtures; external independent completion/review observations remain separate evidence and must not be inferred from those fixtures."
]
```

### externalEvidenceGates 原文（3 项）

```json
[
  "independent semantic review and external key custody",
  "distributed lease/fencing service and external immutable audit anchor",
  "authorized target-host deployment, rollback rehearsal, operator acceptance and release"
]
```
