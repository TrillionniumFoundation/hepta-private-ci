"""Restore exact historical evidence from individually compressed containers."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zlib


INDEX = "qa/repository-consolidation/20261115/raw-evidence-storage.json"
EXTENSION_INDEX = (
    "qa/repository-consolidation/20261124/source53-log-gzip/raw-evidence-storage.json"
)
SOURCE84_INDEX = (
    "qa/repository-consolidation/20261124/source84-log-gzip/raw-evidence-storage.json"
)
SOURCE0A5_INDEX = (
    "qa/repository-consolidation/20261124/source0a5-log-gzip/raw-evidence-storage.json"
)
EVALUATED_READ_INDEX = "qa/repository-consolidation/20261124/evaluated-read-logs/raw-evidence-storage.json"
HOSTED_QUALIFICATION_INDEX = "qa/repository-consolidation/20261124/hosted-qualification-logs/raw-evidence-storage.json"
MEM8_INDEX = "qa/repository-consolidation/20261124/mem8-log-gzip/raw-evidence-storage.json"
HOSTED_1026_WINDOWS_INDEX = "qa/repository-consolidation/20261124/hosted-1026-windows-learn/raw-evidence-storage.json"
HISTORICAL_CARGO_DENY_INDEX = "qa/repository-consolidation/20261124/historical-cargo-deny-logs/raw-evidence-storage.json"
PAIRED_DIAGNOSTIC_INDEX = "qa/repository-consolidation/20261124/paired-diagnostic-logs/raw-evidence-storage.json"
VENDORED_PATCH_INDEX = "qa/repository-consolidation/20261124/vendored-patch-custody/raw-evidence-storage.json"
QUALIFIED_CONSOLE_INDEX = "qa/repository-consolidation/20261124/qualified-console-custody/raw-evidence-storage.json"
MEM8_BOUNDED_GNU_INDEX = "qa/repository-consolidation/20261125/mem8-bounded-gnu-logs/raw-evidence-storage.json"
RUNNER_CONSOLE_INDEX = "qa/repository-consolidation/20261125/qualified-runner-console/raw-evidence-storage.json"
HISTORICAL_PATCH_INDEX = "qa/repository-consolidation/20261125/review-only-source-diffs/raw-evidence-storage.json"
QUALIFICATION_TRANSFER_MANIFEST_INDEX = "qa/repository-consolidation/20261125/qualification-transfer-manifest/raw-evidence-storage.json"
VENDOR_MAINTENANCE_PATCH_INDEX = "qa/repository-consolidation/20261125/vendor-maintenance-patches/raw-evidence-storage.json"
HCSN_HOSTED_CONSOLE_INDEX = "qa/repository-consolidation/20261125/hcsn-hosted-console-custody/raw-evidence-storage.json"
CLOSED_RESULTS_INDEX = "qa/repository-consolidation/20261125/closed-public-results/raw-evidence-storage.json"
EXEC_ACCEPTANCE_DIFF_INDEX = "qa/repository-consolidation/20261125/exec-acceptance-diff-custody/raw-evidence-storage.json"
AFTER_ACTION_LOG_INDEX = "qa/repository-consolidation/20261125/after-action-log-custody/raw-evidence-storage.json"
CALLER_REVIEW_DIFF_INDEX = "qa/repository-consolidation/20261125/caller-review-diff-custody/raw-evidence-storage.json"
AGENTD_STATIC_READELF_INDEX = "qa/repository-consolidation/20261125/agentd-static-readelf-custody/raw-evidence-storage.json"
LEARNING_NATIVE_TUPLE_INDEX = "qa/repository-consolidation/20261125/learning-native-tuple-custody/raw-evidence-storage.json"
NATIVE_NOTICE_BYTE_INDEX = "qa/repository-consolidation/20261125/native-notice-byte-custody/raw-evidence-storage.json"
HISTORICAL_READBACK_INDEX = "qa/repository-consolidation/20261125/historical-readback-custody/raw-evidence-storage.json"
TERMINAL_DIFF_INDEX = "qa/repository-consolidation/20261125/terminal-and-diff-custody/raw-evidence-storage.json"
SOURCE_LIBRARY_INDEX = "qa/repository-consolidation/20261125/source-library-custody/raw-evidence-storage.json"
PRED_AND_HPCA_HOSTED_INDEX = "qa/repository-consolidation/20261125/pred-and-hpca-hosted-custody/raw-evidence-storage.json"
OCT21_HISTORY_INDEX = "qa/repository-consolidation/20261125/oct21-historical-custody/raw-evidence-storage.json"
MEM8_STATIC_SOURCE_INDEX = "qa/repository-consolidation/20261125/mem8-static-source-custody/raw-evidence-storage.json"
MEM8_LEASE_REVIEW_INDEX = "qa/repository-consolidation/20261125/mem8-lease-review-custody/raw-evidence-storage.json"
SYNTECT_FIXTURE_INDEX = "codex-rs/third_party/syntect-5.3.0-maintained-codec/fixture-custody/raw-evidence-storage.json"
HISTORICAL_RESEARCH_CONSOLE_INDEX = "qa/repository-consolidation/20261125/historical-hosted-research-console/raw-evidence-storage.json"
SYNTECT_UPSTREAM_GRAMMAR_INDEX = "codex-rs/third_party/syntect-5.3.0-maintained-codec/fixture-custody/upstream/raw-evidence-storage.json"
FROZEN_CREDIT_RAW_BUDGET_INDEX = "qa/repository-consolidation/20261125/frozen-credit-raw-budget-custody/raw-evidence-storage.json"
ORDINARY_HISTORICAL_REVIEW_INDEX = "qa/repository-consolidation/20261125/ordinary-historical-review-custody/raw-evidence-storage.json"
VERIFY2_IMAGE_LOG_INDEX = "qa/repository-consolidation/20261125/verify2-image-log-custody/raw-evidence-storage.json"
ORDINARY_REVIEWED_PATCH_CONTINUATION_INDEX = "qa/repository-consolidation/20261125/ordinary-reviewed-patch-continuation/raw-evidence-storage.json"
N128_ORIGINAL_HOSTED_LOG_INDEX = "qa/repository-consolidation/20261125/hosted-n128-original-log-custody/raw-evidence-storage.json"
OWNER_QUALIFICATION_LOG_INDEX = "qa/repository-consolidation/20261125/owner-qualification-log-custody/raw-evidence-storage.json"
HISTORICAL_REVIEW_READBACK_INDEX = "qa/repository-consolidation/20261125/historical-review-readback-custody/raw-evidence-storage.json"
HISTORICAL_HOSTED_READBACK_INDEX = "qa/repository-consolidation/20261125/historical-hosted-readback-custody/raw-evidence-storage.json"
PEER_REVIEWED_DIFF_INDEX = "qa/repository-consolidation/20261125/reviewed-diff-custody/raw-evidence-storage.json"
STANDALONE_QUALIFICATION_LOG_INDEX = "qa/repository-consolidation/20261125/standalone-qualification-log-custody/raw-evidence-storage.json"
REVIEWED_QUALIFICATION_DIFF_INDEX = "qa/repository-consolidation/20261125/reviewed-qualification-diff-custody/raw-evidence-storage.json"
NATIVE_BRIDGE_JUNIT_INDEX = "qa/repository-consolidation/20261125/frozen-native-bridge-junit/raw-evidence-storage.json"
REVIEW_ONLY_FROZEN_PATCH_INDEX = "qa/repository-consolidation/20261125/review-only-frozen-patch-custody/raw-evidence-storage.json"
REVIEWED_BRANCH_DIFF_INDEX = "qa/repository-consolidation/20261125/reviewed-branch-diff-replay/raw-evidence-storage.json"
CORE_MEMORY_REVIEWED_SOURCE_INDEX = "qa/repository-consolidation/20261125/core-memory-reviewed-source-custody/raw-evidence-storage.json"
HCSN_ARCHITECTURE_SOURCE_CONSOLE_INDEX = "qa/repository-consolidation/20261125/hcsn-architecture-source-console/raw-evidence-storage.json"
REGISTERED_HISTORICAL_CONSOLE_INDEX = "qa/repository-consolidation/20261125/registered-historical-console/raw-evidence-storage.json"
REGISTERED_NATIVE_READBACK_CONSOLE_INDEX = "qa/repository-consolidation/20261125/registered-native-readback-console/raw-evidence-storage.json"
ORIGINAL_NATIVE_QUALIFICATION_EVIDENCE_INDEX = "qa/repository-consolidation/20261125/original-native-qualification-evidence/raw-evidence-storage.json"
OCTOBER_AUDIT_INVENTORY_INDEX = "qa/repository-consolidation/20261125/october-audit-inventory-custody/raw-evidence-storage.json"
HCSN_PATCH_CUSTODY_INDEX = "qa/repository-consolidation/20261125/hcsn-patch-custody/raw-evidence-storage.json"
HCSN_PUBLICATION_LOG_CUSTODY_INDEX = "qa/repository-consolidation/20261125/hcsn-publication-log-custody/raw-evidence-storage.json"
ARCHIVED_HISTORY_CONSOLE_RETENTION_INDEX = "qa/repository-consolidation/20261125/archived-console-retention/raw-evidence-storage.json"
ARCHIVED_NATIVE_CONSOLE_RETENTION_INDEX = "qa/repository-consolidation/20261125/archived-native-console-retention/raw-evidence-storage.json"
INACTIVE_QUALIFICATION_OUTPUT_CUSTODY_INDEX = "qa/repository-consolidation/20261126/inactive-qualification-output-custody/raw-evidence-storage.json"
AGE_VERBATIM_TESTKIT_FIXTURES_INDEX = "qa/repository-consolidation/20261126/age-verbatim-testkit-fixtures/raw-evidence-storage.json"
REFUSAL_HARNESS_CUSTODY_INDEX = "qa/repository-consolidation/20261126/refusal-harness-custody/raw-evidence-storage.json"
GENERATED_DEPTH6_DIFF_CUSTODY_INDEX = "qa/repository-consolidation/20261126/generated-diff-custody/raw-evidence-storage.json"
RETAINED_CONSOLE_PARTS_CUSTODY_INDEX = "qa/repository-consolidation/20261126/retained-console-custody/raw-evidence-storage.json"
ARCHIVED_VALIDATION_READBACKS_INDEX = "qa/repository-consolidation/20261126/archived-validation-readbacks/raw-evidence-storage.json"
ARCHIVED_DEPENDENCY_DIAGNOSTICS_INDEX = "qa/repository-consolidation/20261126/archived-dependency-diagnostics/raw-evidence-storage.json"
ARCHIVED_CONTEXT_COMPILER_QUALIFICATION_INDEX = "qa/repository-consolidation/20261126/archived-context-compiler-qualification/raw-evidence-storage.json"
ARCHIVED_ARTIFACT_WITHDRAWAL_INDEX = "qa/repository-consolidation/20261126/archived-artifact-withdrawal-qualification/raw-evidence-storage.json"
ARCHIVED_SEALED_PR_READBACKS_INDEX = "qa/repository-consolidation/20261126/archived-sealed-pr-readbacks/raw-evidence-storage.json"
ARCHIVED_SEALED_QUALIFICATION_READBACKS_INDEX = "qa/repository-consolidation/20261126/archived-sealed-qualification-readbacks/raw-evidence-storage.json"
ARCHIVED_ARTIFACT_PUBLICATION_INDEX = "qa/repository-consolidation/20261126/archived-artifact-publication-qualification/raw-evidence-storage.json"
ARCHIVED_SEALED_REVIEW_READBACKS_INDEX = "qa/repository-consolidation/20261126/archived-sealed-review-readbacks/raw-evidence-storage.json"
ARCHIVED_SEALED_READER_SOURCE_INDEX = "qa/repository-consolidation/20261126/archived-sealed-reader-source/raw-evidence-storage.json"
ARCHIVED_SEALED_RUN_RECORDS_INDEX = "qa/repository-consolidation/20261126/archived-sealed-run-records/raw-evidence-storage.json"
ARCHIVED_AGE_APACHE_LICENSE_INDEX = "qa/repository-consolidation/20261126/archived-age-apache-license/raw-evidence-storage.json"
SYNTECT_METADATA_ORIGINALS_INDEX = "qa/repository-consolidation/20261126/syntect-metadata/raw-evidence-storage.json"
BM25_FORMAT_ORIGINALS_INDEX = "qa/repository-consolidation/20261126/bm25-format-originals/raw-evidence-storage.json"
COMPANION_DOCUMENT_ORIGINALS_INDEX = "qa/repository-consolidation/20261126/companion-document-originals/raw-evidence-storage.json"
CONTEXT_DOCUMENT_ORIGINALS_INDEX = "qa/repository-consolidation/20261126/context-document-originals/raw-evidence-storage.json"
ARCHIVED_PAIRED_OWNER_LOGS_INDEX = "qa/repository-consolidation/20261126/archived-paired-owner-logs/raw-evidence-storage.json"
HCSN_SPLIT_REPLAY_INDEX = "qa/repository-consolidation/20261126/hcsn-split-replay/raw-evidence-storage.json"
HCSN_NATIVE_READBACK_INDEX = "qa/repository-consolidation/20261126/hcsn-native-readback-storage.json"
FINITE_NOTES_NATIVE_LAUNCHER_INDEX = "qa/repository-consolidation/20261126/finite-notes-native-launcher-storage.json"
VERIFIED_REPORTS_INDEX = "qa/repository-consolidation/20261126/verified-reports-storage.json"
TERMINAL_REVIEW_INDEX = "qa/repository-consolidation/20261126/terminal-report-storage.json"
HISTORICAL_INVENTORY_DOCUMENTS_INDEX = (
    "qa/repository-consolidation/20261126/historical-inventory-documents/raw-evidence-storage.json"
)
C2_ORIGINAL_STATUS_INDEX = "qa/repository-consolidation/20261126/c2-original-status/raw-evidence-storage.json"
HISTORICAL_UPSTREAM_TEST_RECIPES_INDEX = "qa/repository-consolidation/20261126/upstream-test-recipe-custody/raw-evidence-storage.json"
FSDD_UPSTREAM_ATTRIBUTION_INDEX = "qa/repository-consolidation/20261126/fsdd-upstream-attribution/raw-evidence-storage.json"
JOINT_GENERATION_SOURCE_SEALS_INDEX = (
    "qa/repository-consolidation/20261126/joint-generation-source-seals/raw-evidence-storage.json"
)
INDEX_SHA256 = {
    "qa/repository-consolidation/20261127/n256-uniformization-source-chain/raw-evidence-storage.json": (
        "c9e71b773a7f8fe6afabda331005212782d209ec0eb8e6bebe55f41041b9fb19"
    ),
    "qa/repository-consolidation/20261127/hcsn-frozen-vjp-sources/raw-evidence-storage.json": (
        "e6d0268d8f0338066a9d6c7549656e913a864fdc2dae2013c16fe7ee1f54d080"
    ),
    "qa/repository-consolidation/20261127/hcsn-historical-source-pins/raw-evidence-storage.json": (
        "91b0fa2237b9db16b90539be072c553479e5d81352f3b12889b54f5576412099"
    ),
    "qa/repository-consolidation/20261126/fp64-rounding-predecessors/raw-evidence-storage.json": (
        "48513353a2cafa38c5e899bc0613936deb0680c8923fff2413dc397c5a8b6c28"
    ),
    "qa/repository-consolidation/20261126/patch-source-custody/raw-evidence-storage.json": (
        "cddbb382da7ae892cf017bc562098c6cabd4bc1a6422fd2dfd60ee6b46816b28"
    ),
    "qa/repository-consolidation/20261126/macos-six-source/raw-evidence-storage.json": (
        "f3bde1f495dea35633a821b3f25324c338cada5ed4ddc4e9b54f42800cdfae8f"
    ),
    "qa/repository-consolidation/20261126/resident-evaluation-rows/raw-evidence-storage.json": (
        "df2b30159224cad7168c4a035db4537a45e90ae1cfaac475d89f76f4562c1035"
    ),
    "qa/repository-consolidation/20261126/macos-release-qualification-source/raw-evidence-storage.json": (
        "144443115109d9b24b0e2f10a69b98a4668cec037ce4c8ecd84d251c66b7f13f"
    ),
    "qa/repository-consolidation/20261126/n256-uniformization-source-proofs/raw-evidence-storage.json": (
        "f9b15cdd054052525b62126d53973158e215aadaf2cb95090e70922b5fffcc46"
    ),
    "qa/repository-consolidation/20261126/n256-paired-source-seals/raw-evidence-storage.json": (
        "5ac0602fc4c063a2bb20e5dfb16948ec1cb2467743803434ceb83577c50d5f43"
    ),
    "qa/repository-consolidation/20261126/n256-fp64-input-source-seal/raw-evidence-storage.json": (
        "588de247b9efa3914427b00f4ce8f222fce7bcdf21894dcdad2a4e50ec0865a0"
    ),
    "qa/repository-consolidation/20261126/neuroscience-reference-source-seals/raw-evidence-storage.json": (
        "6c969dc4d3100d574997756f12b6ccffd5247dac6d5e355b50c4982047f84df5"
    ),
    "qa/repository-consolidation/20261126/native-publication-source-seal/raw-evidence-storage.json": (
        "c625443574e9b011a714cd15661ff517272bf9e64e617cbe62cac7c0dd4368be"
    ),
    "qa/repository-consolidation/20261126/clock-source-seals/raw-evidence-storage.json": (
        "4c88d481cff54921d612d5a95bc314cbe47fe28d53fbe6b94d09745f62fb08cd"
    ),
    "qa/repository-consolidation/20261126/hcsn-training-domain-adapter/raw-evidence-storage.json": (
        "7af31342eac4c95f5d96d217c3dda087bd46be83cf0b55ae16dd53f29463f216"
    ),
    JOINT_GENERATION_SOURCE_SEALS_INDEX: "77bbf4f7ec7429c78c00c135419f06ee839269479804055f84d6ade317320778",
    FSDD_UPSTREAM_ATTRIBUTION_INDEX: "2ad6221210c32b84c49c86924edc525996aeb226c3fd8c13916e3348b6b1255b",
    HISTORICAL_UPSTREAM_TEST_RECIPES_INDEX: "6be8378b48363ca551fe0e9437d5df336d52fa76d87b861c9b04f1f2e65865e5",
    C2_ORIGINAL_STATUS_INDEX: "3830a7eedfde9596e53c213d4a9b35068d5e388b87573622eca9d8115289253e",
    HISTORICAL_INVENTORY_DOCUMENTS_INDEX: "68724c09eee37616476c66e0fd94503f9500b95654ca868696b24dd97e56ccf0",
    TERMINAL_REVIEW_INDEX: "b5847c3675ceec9a0d33754022837a628b2a47b2f446a10fcc7d9489afb13359",
    VERIFIED_REPORTS_INDEX: "dab53d7a440850d210cd1ea8b4bd06d3335ead6bda37ea735a27086956fcf1a1",
    FINITE_NOTES_NATIVE_LAUNCHER_INDEX: "126f299feb14f46c9d22c57476652688740752adf92ad4b375bf66974f6ffe23",
    HCSN_NATIVE_READBACK_INDEX: "ea18725861c54e448ae74aacce27aa8902065c38b8de0c09f90336149d600375",
    HCSN_SPLIT_REPLAY_INDEX: "f9be5d3969f4f798bc1b35e9366d1f522642f6cb6759538ffc8f44c41f52a90d",
    ARCHIVED_PAIRED_OWNER_LOGS_INDEX: "9618111bf18d8a228f8681a7ba59db9b308a08906572de6d75fa6565ed86eece",
    CONTEXT_DOCUMENT_ORIGINALS_INDEX: "7db67de4c3a3fe9c69b9cc7a9d30f7f4cbe79a6851bbabab2965d7a1246139d7",
    COMPANION_DOCUMENT_ORIGINALS_INDEX: "29504ec13ca2d589170b5d723d36e9f786127408d38f3a31b3b02f0bfce41680",
    BM25_FORMAT_ORIGINALS_INDEX: "b2f7521d9e5332224bc20c777d92a4719357d88dceec64a0d029136df12ff900",
    SYNTECT_METADATA_ORIGINALS_INDEX: "5f3ae1405d41f753ba9f9fa899c049be21cea18452d4951539f26376efc43bed",
    ARCHIVED_AGE_APACHE_LICENSE_INDEX: "8f5382b798ea187bec27da72889d91cfc98457645dc6ea9b294ccd8639063943",
    ARCHIVED_SEALED_RUN_RECORDS_INDEX: "7c80d7b14048f6992137f22fd47c3a659625b203e7379798275762a1d82b8d07",
    ARCHIVED_SEALED_READER_SOURCE_INDEX: "af126b3db28aa9097b35ff715f37868e73f58a97b3f915077652b52758da8e9b",
    ARCHIVED_SEALED_REVIEW_READBACKS_INDEX: "d26cdb85dc0fba913037a1ed67ed6aaa9491fdcbcf9f37595d824a4f4e1092dd",
    ARCHIVED_ARTIFACT_PUBLICATION_INDEX: "de4196992518b933f5541c668734aaae8322a88b95d2f7503c3555e9ba0a97da",
    ARCHIVED_SEALED_QUALIFICATION_READBACKS_INDEX: "5e3c616ca3e39b0b235d3efbdfcd9f8c4701f9ab6d0048d670504456abebfe3f",
    ARCHIVED_SEALED_PR_READBACKS_INDEX: "5b43687d38cc0c2cfba0efa64fc328917664d82a789e46578375d31506d796ba",
    ARCHIVED_ARTIFACT_WITHDRAWAL_INDEX: "514e823146d9ed75a561307168654929814a410701d086a07428061cc0fa52fe",
    ARCHIVED_CONTEXT_COMPILER_QUALIFICATION_INDEX: "baa4b8980f650eb5840f3a499fcb846706217818877c98a80d369c4890f4e9bb",
    ARCHIVED_DEPENDENCY_DIAGNOSTICS_INDEX: "6db8aa6375c4955da92c69b166b10dc975cac283cb499a6cd8435ea38407f131",
    ARCHIVED_VALIDATION_READBACKS_INDEX: "0b2fe77a81623b8b4b921f35a7af1b78439fcbe7bd08d41593c5958d563a2b70",
    RETAINED_CONSOLE_PARTS_CUSTODY_INDEX: "0e4bb9cbc89ac82daff386e1ca1c97d77ca5de558fb794dcf604a8317c287462",
    GENERATED_DEPTH6_DIFF_CUSTODY_INDEX: "aac592f88085868a77e797ddda119d18317658892821611a2e029ff1a3422057",
    REFUSAL_HARNESS_CUSTODY_INDEX: "5c25beccbe41d17dc8b0da1541fcbf8e5564cf815329b88bafe62d922702f74a",
    AGE_VERBATIM_TESTKIT_FIXTURES_INDEX: "2885456444551f12ab1a3c7975088c61d3ec5181030dccddc520da262e731680",
    INACTIVE_QUALIFICATION_OUTPUT_CUSTODY_INDEX: "f01b8ce53b391a9507305d2d167b6e5f34de724fdf50bf51ef47c67cefb0241b",
    ARCHIVED_NATIVE_CONSOLE_RETENTION_INDEX: "7510da38801df159ee2b22639d8cd5e5a009cb194a39025c6631b7d5f315a6fc",
    ARCHIVED_HISTORY_CONSOLE_RETENTION_INDEX: "79405ea853d6f4c6f3752054ba2237331c3571666585b2a6072da6bb5667c408",
    HCSN_PUBLICATION_LOG_CUSTODY_INDEX: "2ebc09eba24548dab744aaa809040ced23cbb95c910b3857a148ab1906418dbd",
    HCSN_PATCH_CUSTODY_INDEX: "978ac665f70befa9494c84e1ea93566a35d1ff4bea058c35c051e0adf7edf46c",
    OCTOBER_AUDIT_INVENTORY_INDEX: "fc341ba4f1988f25a55d07d1c1006869ed8323ee8dc372426d38f2ed1c593817",
    ORIGINAL_NATIVE_QUALIFICATION_EVIDENCE_INDEX: "68bdb29cac60b51d6809c20d9a81f2afd173aaba123c8508310ccf91e047a26f",
    REGISTERED_NATIVE_READBACK_CONSOLE_INDEX: "8e0a2e13c7854389c2718ac5a38e0d8acf10205e11237fb513607848d1d6defa",
    REGISTERED_HISTORICAL_CONSOLE_INDEX: "2b71a73fe4d51d86baf853086a0088122979f81ed57bcf2fb6ee9f2b14295473",
    HCSN_ARCHITECTURE_SOURCE_CONSOLE_INDEX: "8acf741b49278909b811fed997ca6cb5958b246b9e5bbe6bd2b48a0ec5280142",
    CORE_MEMORY_REVIEWED_SOURCE_INDEX: "68fa2232ea0f288ad6453edec7c5e5aa8b03b62278d8dae1a290337322417cc3",
    REVIEWED_BRANCH_DIFF_INDEX: "ad1da0ba6dbc6161e8c2cb5cb185c15e9b5855f8ba43aab500391606c5955638",
    REVIEW_ONLY_FROZEN_PATCH_INDEX: "d5c3a411665ef6f1a35e51127d7bafa803972e10d3b6b083dbe7d209cd97c8f7",
    NATIVE_BRIDGE_JUNIT_INDEX: "e84e9ef3c80c88006d03f7bf810a81e498fec995dbf9258a6d6216924697b418",
    REVIEWED_QUALIFICATION_DIFF_INDEX: "2870ed2e62467322cca523716f73b5f6af64c862f09749a4c2000ce5f4f19df9",
    PEER_REVIEWED_DIFF_INDEX: "5060f74c596e407a8f6157079c89e0458b15363724204129f16a9beef032866b",
    STANDALONE_QUALIFICATION_LOG_INDEX: "ed2ead4783a4bc1bca1baf1ca46e6e38d11dc7dcef8df92cbf36e3b03b1a7d48",
    HISTORICAL_HOSTED_READBACK_INDEX: "8084bd1978e88798fbdb0f99ba4d7d46b591e195c3211b2bbc4b1f0dd6b713e0",
    HISTORICAL_REVIEW_READBACK_INDEX: "cfe5d3a4a7566d4aa3304c35401a286debd7ee1190ea4add1b0a0576b19bcf87",
    OWNER_QUALIFICATION_LOG_INDEX: "537852f987f9fb7d45347cf24a8923fa682925be0e616d27f56d912edfcd9c55",
    N128_ORIGINAL_HOSTED_LOG_INDEX: "f47e63042c169db4b0a326e16c9024913e217166ba8ef6c642c8a2346edb56cc",
    ORDINARY_REVIEWED_PATCH_CONTINUATION_INDEX: "40a153c55cf813e57a1a7a0ffc9e8f2e589781da048ba012b6828cf41474c3a4",
    VERIFY2_IMAGE_LOG_INDEX: "4a9fb5de9eeddd2f1375434e14d8d8a7815e9f61913da12bb6f29890321d76db",
    ORDINARY_HISTORICAL_REVIEW_INDEX: "b5b5874d3ff8fc5865a49a9b835a4dc76dc2a321da05d1770af7d5db708e01b7",
    FROZEN_CREDIT_RAW_BUDGET_INDEX: "3bd3218803ed7d02e28206c49865f31dd9bf43c26da87de33f81e3fcb5fe1084",
    SYNTECT_UPSTREAM_GRAMMAR_INDEX: "0473102fb0d2e6143441b74e6d1fd71051dcb5e0399a0f57bd29b03ac05f364b",
    HISTORICAL_RESEARCH_CONSOLE_INDEX: "877a50679f8f95964de2b81fee72520e71d9cf5fbb4d3820e28f45a70d8fd1a5",
    SYNTECT_FIXTURE_INDEX: "9eb3bbf2be6f8f76490906c7e98aae0334d4e7aa7eac13ec216c5f9a0936cbdc",
    MEM8_LEASE_REVIEW_INDEX: "23d1cbd5a5609c78fae6cb398676bfb5d26b51d0c3c7c97e8b287a9fa1575987",
    MEM8_STATIC_SOURCE_INDEX: "5d344321dd99a447b53fc7887414d4df4e08727507b644f9256ded6be61f253d",
    OCT21_HISTORY_INDEX: "7fd7751e0f14d503a68b1055f3a15723fc38542b17d992f337a17360569e4dc1",
    PRED_AND_HPCA_HOSTED_INDEX: "3c54780e43565c9e399e0ef64fb912d401a5fd641ed64a5e3a4ef78d166eaddc",
    SOURCE_LIBRARY_INDEX: "1cd1fbab750a5d9ecc239dcfc5f1e0d4dd7287f0fcbff0ecc8af1509d3576745",
    TERMINAL_DIFF_INDEX: "0cd34337c9529303071017c0ef80d7f4c053364ec4aecb8ab65d6ba692c5c15c",
    HISTORICAL_READBACK_INDEX: "4c9ac6db51751049cff2cdbcf060b35e53c50c1ce0ce83ba2c0dc05bd765963a",
    NATIVE_NOTICE_BYTE_INDEX: "ee7097c3b95446b3043e781c1cedae9e951de718b0ee985b2a92caecc9a4b7be",
    LEARNING_NATIVE_TUPLE_INDEX: "532391f27b873d2856a19be3cc05e679a1aca0f08be253bd847c9e0a99dff111",
    AGENTD_STATIC_READELF_INDEX: "57be021f57ddec181e324c83e0aafdc80b8657a712c4e428d3b4e1155a3f49d7",
    CALLER_REVIEW_DIFF_INDEX: "a56e025fc409a3cdc9376096ce9cf5908132531511ce9a4ed5fa97c155863a33",
    AFTER_ACTION_LOG_INDEX: "b88ee4c1373e6b1624b0172b6a4da96a0a024260c0c41b0cfd3f87d7fe0a16b6",
    EXEC_ACCEPTANCE_DIFF_INDEX: "17e0b6fe9aba3b7911da12302107b3324038aefbcec27d4375887b976751b678",
    CLOSED_RESULTS_INDEX: "c776af0182349d8ea398fb3356491fe1140ac49d1f483eeadca0c12406367865",
    HCSN_HOSTED_CONSOLE_INDEX: "cd356ec2c924596980da39e9d55156c6be4d003df4b62d535168e2619095db54",
    VENDOR_MAINTENANCE_PATCH_INDEX: "bd5b46cba3cb36b2c6233e625e6e48b60e3bf29eda849d59474a5c869d2e740b",
    QUALIFICATION_TRANSFER_MANIFEST_INDEX: "2b5ae403edfb29877d4766ac002e516b3593607d0e65092836fe28328759ea98",
    HISTORICAL_PATCH_INDEX: "6ccb39564994c6bc8efb95516325c442f0d6f0bfbfd80ee3eb8c723acaecb181",
    RUNNER_CONSOLE_INDEX: "47e503499077278820266ee068ed8d638f5b0767d8bd94657cb1205d2de7307b",
    MEM8_BOUNDED_GNU_INDEX: "d249597de292b7c5e9bec309552d8e52d05a0cbe3261d1032f8b5bbb2958841e",
    QUALIFIED_CONSOLE_INDEX: "974ab4cc5a9a5066a3598ef64ba3eb990e6dff68ae3995956790835969f253b7",
    VENDORED_PATCH_INDEX: "17ba3a271e6a289faea295617649ad6dfc7cb90e42709c6b8c9e96ff2d352de9",
    PAIRED_DIAGNOSTIC_INDEX: "01d68c678f8f5fddb3ed685bdf6604da7639d740faddeda6a5fc723cf89ed7cf",
    HISTORICAL_CARGO_DENY_INDEX: "afd074a431b6cec896c4f4d8ce93a8edefd6b9641149a76bbf7c9b4d53aa30fd",
    HOSTED_1026_WINDOWS_INDEX: "39586c184ddda5375d1dac27d98b41cedf664a8054f9592dda90966cbe77477a",
    MEM8_INDEX: "e9211b1fd070df8b4f8f622ef915171c5a7918279c07672ef8d637bbb41680c5",
    HOSTED_QUALIFICATION_INDEX: "eb8e44a4d72d6737a9deecf715fd38dcce94401d01925c1b6337771ec4aef434",
    EVALUATED_READ_INDEX: "b234ee9989eb6ed712905d6c9da748d35a1400d8b2c71ab197675520a5c8aa64",
    INDEX: "72103445cd088e31ee2e6d4887b9e24638d184389226b1577ff7342ebebc44c0",
    EXTENSION_INDEX: "9a4288af05724562b9aa4fde5782735531eeee048c3d4ce63a63f5f6b60e8b87",
    SOURCE84_INDEX: "a4b240eef423bab829e2150c63a603a5d0c3f001220ae5616b2f87eed7ec8184",
    SOURCE0A5_INDEX: "dde0cc0c597ed9d85d10aa68d0b4bbaaa32fd949efce445aeb1b346f08742f55",
}

# Human-readable archive notices are distinct from the historical bytes.
ARCHIVE_NOTICE_SHA256 = {
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/REQUEST.json": (
        "3fc75817c42e7bb68f100562964051a68ba05f2f07e1e1bf59435eb01873ca8b"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/review.py": (
        "7a211fff5ef5c0ebb5ecb5d11eb6f60cf4552f31a91929cd038337d85060cbdf"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/REQUEST.json": (
        "0ee36f9eb21b18ddacf06b7b3e8c3ae06fb981d97e560bbd51a1173d4bbc710a"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py": (
        "ac6114b0e19776374d9b6ab0ce61576b64c35c2db9332412a6d6e3bf6ea40614"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json": (
        "138d1df420e9305075ff936886c685f98df7d67dcd7fda1cf3a93f613961afaf"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/SOURCE_FREEZE.json": (
        "6e713042592cb1210364f9878dfbbf80cf0413201609f1a6b12b042bbeb5ecb6"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py": (
        "7e1a0051e7c81ab0499d4a7aa23a015b59588faff52330e4355c9357d16bd86e"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/verify_source.py": (
        "963c3e1aa407c8d43c204197400ecc8560bf41fdc083296bd050dcdad698847e"
    ),
    "qualification/hcsn_currentstate_n256_execution_freeze_protocol/verify_source.py": (
        "ae61d17d589206285570a7ff55b8598955f3fb090a40e907c0437066762a3328"
    ),
    "qualification/hcsn_currentstate_n256_execution_admission_bridge/verify_source.py": (
        "bd932cafba714b042e246394031e566544f34e4b2c5bcbb72c801753c9321729"
    ),
    "qualification/hcsn_currentstate_n256_provider_fullstate_bridge/verify_source.py": (
        "2c43ac884e3d57300cf771bc74834f589bc0aec57c8337363392900a988c90ec"
    ),
    "qualification/hcsn_source_migration_vjp_n128_parentclear_attempt/REQUEST.json": (
        "517e444413b5d1156399b68afdfe9294f7c788fd00c750874deda689ae7d66c2"
    ),
    "qualification/hcsn_source_migration_vjp_n128_parentclear_attempt/admission_inspector.py": (
        "520a4458a06c5af9029b840d5eca2a6550cade26307f8e59cb6959dc4884ae3f"
    ),
    "qualification/hcsn_source_migration_vjp_n128_parentclear_attempt/native_probe.py": (
        "1d6ab9db71ec8220da4482942bcaf081bc2740da963a82e40d9497f145c7643d"
    ),
    "qualification/hcsn_source_migration_vjp_n128_parentclear_attempt/source_flow.py": (
        "dcd25a833f5be575a3ea295d35026134301d5cbbfdcc36dd5ea0451ba03624de"
    ),
    "qualification/hcsn_source_migration_vjp_n128_scalepreserve_attempt/REQUEST.json": (
        "39df57dd725bce6dd4701f0f5e880dda1e58c751b034caac138d739aa505b334"
    ),
    "qualification/hcsn_source_migration_vjp_n128_scalepreserve_attempt/admission_inspector.py": (
        "d43c4d0d6cc8ec6abbe89f71a72eb183c3dd30241e4000dcccb0002645943c91"
    ),
    "qualification/hcsn_source_migration_vjp_n128_scalepreserve_attempt/native_probe.py": (
        "e97e17bce2a4a5af49f3a648422cf07e87fa95d333d04f94ec614c76dc0b2514"
    ),
    "qualification/hcsn_source_migration_vjp_n128_scalepreserve_attempt/source_flow.py": (
        "c49d0389f3bba905b32d62f2a21daf5855a2e5f53dabdcf9bd8e374c0be68923"
    ),
    "qualification/hcsn_source_migration_vjp_n128_stretch_attempt/FORENSIC.json": (
        "719a84dc583cd492d9d52635d3cb17943659e3d244697308f9f07a85d1ce140d"
    ),
    "qualification/hcsn_source_migration_vjp_n128_stretch_attempt/REQUEST.json": (
        "5849283db0a0f69ec4a12d44622f589c32bfb455336ef893a664ebe504bb3d81"
    ),
    "qualification/hcsn_source_migration_vjp_n128_stretch_attempt/admission_inspector.py": (
        "771a95d944d602a403e960335f8e4c0accf70657d5d236dd97097f2eb852d5ec"
    ),
    "qualification/hcsn_source_migration_vjp_n128_stretch_attempt/native_probe.py": (
        "810d4de44d4a38fbefa5423fe07632bfcbfa9a693e2878f50ad719f6c54dfb3a"
    ),
    "qualification/hcsn_source_migration_vjp_n128_stretch_attempt/source_flow.py": (
        "98aa4dc5e9e1ab6a6769eb6407ab95b6c4489d0bdd01a9add11a320e80989cb9"
    ),
    "qualification/hcsn_differentiable/evidence/p0p5-20261110/p2/hcsn-effective32-derived-summary.json": (
        "305c456f257b86b3a07337496cbee438bd317f89766577fa77e0f72e651416d0"
    ),
    "qualification/hcsn_differentiable/evidence/p0p5-20261110/publication/hosted-science-42827955616-metadata.json": (
        "a8ada5c5549eb56408abba0ede9ff2c619694e5aad2bcd6764b5ab2679e041ed"
    ),
    "qualification/hcsn_differentiable/evidence/p0p5-terminal-preparation-20261111/resource-core/drivers/validate_resource_rebuild_final_v2.py": (
        "f2d3e8fde4d995d9f855b1d4608bd51dabde2087f68610c95303c17ff0897332"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/fp64_round.py": (
        "742841e716fd2f80d0d7942ddea90c00d8f9c60797d6a2d9508e1527e18d8569"
    ),
    "qualification/hcsn_currentstate_n256_fp64_add_sub/verify_source.py": (
        "d005e3cf024a8b0b5453edf352e361a4f68f27ea580e1ed199857340bde1a9cd"
    ),
    "qualification/hcsn_currentstate_n256_fp64_fma/verify_source.py": (
        "bba1ac096f48d89208e7849a0320ef71249accf6f38ebea64032973632e1b04d"
    ),
    "qualification/hcsn_currentstate_n256_fp64_mul_div/verify_source.py": (
        "8f9b8d5b4ae70fdc71b0203ecfc2767e8e6eec2b71a0870ba2271cd0b3e4524a"
    ),
    "qualification/hcsn_currentstate_n256_fp64_sequence/verify_source.py": (
        "6ae877f389a1280d2a71711cd1d337f91fdf3e433d6a8ea18c4fbc985078402f"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/README.md": (
        "35540dd894e51bb933a6b62618481e310e8c98a0df8f355be550d77dcdd4ae4d"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/__init__.py": (
        "27e9f8f8fc656696bb719fefcd32513c7a2e986c077ca9a0237b185d09150990"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/REQUEST.json": (
        "7da4bf0656d6d275fff4ade64fc02dbd556fb87409763f40eefe40948f7c55b0"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/history/verify_source_v1.py": (
        "58d9129c3753715e8349d25d08d5d3031a32060f060b93935b3aa6e72e61ad5c"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/test_fp64_round.py": (
        "a943283043a7f0d2ab4f2f9cb06ebd61c735d97d77acb387eccc1433f69ba050"
    ),
    "qualification/hcsn_currentstate_n256_fp64_rounding/verify_source.py": (
        "4bc6070aff54d6b5dd126396db356f2e11dc029820b299edd26c7a4aa6493d2b"
    ),
    "qualification/memory-cell-mem8-ci-followup/pending-startup-diagnostics/CANDIDATE.patch": (
        "1664d01d545e479663fb3d4762364b139f4bf97e13af6c90ae60f0fe22c3ce5d"
    ),
    "qualification/memory-cell-mem8-ci-followup/v17/windows-current-d0f/AUDITOR_FROM_C895.patch": (
        "57cd49dbaa8832d96a2bff26b470959f7317c09ad9bc1d2f93e43c7e424eb611"
    ),
    "qualification/learn-ordinary-ce434/evaluation-resident-guards-514-20261112/remote-4ae6-candidate-evaluation-row.toml": (
        "bbd6e03a7acab2ad2b0ae826ae094c261792931d18454f9308d509f858456675"
    ),
    "qualification/learn-ordinary-ce434/evaluation-resident-guards-514-20261112/remote-4ae6-candidate-readback-row.toml": (
        "b79222bdefa3df22fb6143047a6ef4937e339fae423cf8372c72f02fb12648ea"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/README.md": (
        "9eee4c883a88b75fc588bb2e8969b7858caf337f80b1300613751d9c9b197ecd"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/__init__.py": (
        "c1c30f36586fe3006ab5c4412bc59ce06547d7d10cad12a774929a4ae1bc9b36"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/test_provider.py": (
        "fb08cf3a36cfcf6c9f4695379bf6373af8769c6369342517909da7796c553e68"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/verify_source.py": (
        "7923ba83deaa0ab1dafe7c19df65b79f9df3ec6900f6d888b7975e51e587fd23"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/README.md": (
        "59d7a1efd9115069f9c7040ce4c4fb0998bb6673f2be508637614aa13274de7d"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/__init__.py": (
        "309b819a922d151cddf80f6bd5b95d7d2eda53c507aae7fbeba0a8b02c9b0c0a"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/test_precision_policy.py": (
        "7b46ed672c3941cbf4bda608fd77011ba012a7c884cb1eb5b1529f019f5d5724"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/verify_source.py": (
        "6657b32aad8db3074515d1c3e2cde382e27e29b5ae71bb6ee95263a9e2bbe0e5"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/README.md": (
        "5d86e1f634d1f1b3ca42d4cdfa2aa64ced95deb4293f36679ec317036bfa9f58"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/__init__.py": (
        "3fd8cd2c8cef49c6bd19c21ac20ea571740705fb23be0742cb354859697984d3"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/test_review.py": (
        "71c2110a717183feb84faa5a09c6baa8ddeb49890cc7365cf31535fe2bf6cca0"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/verify_source.py": (
        "4cb53a4e8c320091d39a193d141762eeb34414ea2faedf87fe2947923127ee04"
    ),
    "AUDIT/2026-10-20-agent-continuation/p5_inventory/REPORT.md": (
        "7fc952a0b9ab00b96a783618b6a351069697265c2883194815e6308401a2c5a5"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/fp64_exact.py": (
        "54a68deb5edfa4772d2091db4fe671369e3c88dd5071eb6f352651384d994df7"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/test_fp64_exact.py": (
        "4ee7faf03bbc69d4e02ef02da2e5116746edbde97d8f8d253e4e19a5a857831b"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/README.md": (
        "324173f2dae2fefbd5ec9cba9a3d78af7d83a1bee2e9413d431c232809938f9b"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/REQUEST.json": (
        "a61b09d8ce79fabad08e62335f195d22ae095e66160985b0269a86ba7e889cb1"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/__init__.py": (
        "6cc949c5c91ab2019d66c3e4e29ddab4e746d4ebfdf28f0993e034f2b390d174"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/bridge.py": (
        "c1d2c81e6873cff873005b7f611b1df92453059c7709d608bc229f6fa2441671"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/test_bridge.py": (
        "ee4e12114ef8f414b08a64bb56166866c4469abd6dd8b7077d81aa00be0676c0"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/verify_source.py": (
        "506a8b42d468d0129dee9841a69a98812826df31b0ff6349187f07376453829a"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/README.md": (
        "dbd292c88ce16f74d3b694ee2d55c6e372f17dbdc905a53ea2539c84639a9d04"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/REQUEST.json": (
        "da33990511a09f9b555c40e69d7e157683c0242ec185ecd9a44aa80cdeeeadb9"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/__init__.py": (
        "8ae7fae3035f0917bf42baff1d87008d43bb70cdf03c7c7914a3abed3cd31fdb"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/output_interval.py": (
        "818c6dc8b486b9203ee3ed659bb84faf51419b167f5238bb8ed942fc9405f4f8"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/test_output_interval.py": (
        "ea51445b1c4a649328078d5dcfb346956558039dcba1a1fa9db3e8e70b7babf3"
    ),
    "qualification/hcsn_currentstate_n256_uniformization_output_interval/verify_source.py": (
        "6ea15e97a2e0cba07052c745a739fb22f9dfef9e07f54d30526b6ec39533c3b1"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/README.md": (
        "6d850edcc440119fc7e3d374dc4bbdd7085e1a443cabd1c9ac411b6a3255dc93"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/REQUEST.json": (
        "9532b99ce93555bf64f75679cf70c95cccef21ce5bfeccde96b81944a080f43f"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/__init__.py": (
        "55e7b04683f9cc750b6579ac554fd130269c9abfa2e2ad892c17705a04a68d4b"
    ),
    "qualification/hcsn_currentstate_n256_fp64_input_conversion/verify_source.py": (
        "98e60fd19a6e154eed429354ca8f4820451c27ee676df4a2e91db316d4272195"
    ),
    "qualification/neuroscience-20261110/study.py": (
        "f1619da3595976f13cdad1ae02c6265f5e72c356de6d78f711d6b9b6ab5f92e1"
    ),
    "qualification/neuroscience-20261110/test_credit_order_invariance.py": (
        "7bf4197258d93282956bdfe622f3d377f69bbb03ddc79780208c0473ff96f0ce"
    ),
    "qualification/hcsn_differentiable/replay_v1/evidence/native-desktop-20261112-d706/native_github_blob_upload.py": (
        "60ac36f7e99f8b75385055bf3a2d230f8d9b34de20e00c616c96ffb9424bcddc"
    ),
    "qualification/hpca-neuroscience-20261110/fresh_process_readback_v2.py": (
        "c65ce3e89fd04867149d59723618155a80911a1ff4a7e536f2d994f4cc93b89d"
    ),
    "qualification/hpca-neuroscience-20261110/native_lora_clock.py": (
        "65980f7e8dfcc14d07bea4f3ea8d118e32faeadad020f324189140eaa3308129"
    ),
    "qualification/hpca-neuroscience-20261110/real_cpu_clock_counterbalance.py": (
        "dc9546b0cdf682c34ce831eb50adbb1880b4a8edc35e1ef89c2ed88cfff1b4f8"
    ),
    "qualification/hcsn_boundary_audit/audit_training_domain.py": (
        "446b9564813d80548a6b170da6a89232607f06bcbb8ed0c1a6615144a1ef4d9b"
    ),
    "qualification/joint-generation/fit-group-holdout/group_data.py": "248cc4eb80a13f7204d63ec2656b069daa1e22f4356096c75ca60292ab9af972",
    "qualification/joint-generation/semantic-temperature-replication/validation_noise.py": "9c5fec8ab708e9b6278f184224df03b27dfc5739dfa2cf63d5774abb42c2c258",
    "qualification/joint-generation/source-scene-replication/replication_group_data.py": "3d6a03a9d95f608118a3554e1ef5106b8669d6dc225b32436c604bc4e33febf1",
    "experiments/hcsn_free_boundary_v1/data/FSDD_UPSTREAM_README.md": "f59207b4ee0ec917162a23a7d5471dc9341c92ad17f95373996f93d438ac686c",
    "qualification/hcsn_differentiable/replay_v1/evidence/native-desktop-20261112-d706/ORIGINAL_C2_STATUS.json": (
        "88ce606e73060d46d67b54f907f103b6533a428d80f157bbd78c1398bf8941a9"
    ),
    "AUDIT/2026-10-20-agent-continuation/pr_inventory/README.md": (
        "3886c85347bb0bc611d536a305a4da57a3c6436d335b9f805c200a76905c0b05"
    ),
    "qualification/hcsn_differentiable/evidence/localization-v2-20261108/math/repair-v2/REPAIR.md": (
        "fb6ad6d1b24706513dd486c2ab1bd49e5e2ba01a6260b8cc3c5002f8680ac72a"
    ),
    "qa/stem-bakeoff/reviews/cell-field-v8-remaining-terminal/REMAINING_TERMINAL_V8_REPORT.md": (
        "4785c96609cf424bc30d1a2d88b45e2c0559b8108fe18b46f34cedaadbf314de"
    ),
    "qualification/cell-p0-converged-20261110-f7c0/caller-cb/RESULTS.md": (
        "a1715f39fc8090b24159f759e12e15c8112775851f54bf3a782a33d98583d9ec"
    ),
    "qualification/learn-ordinary-ce434/ordinary-input-handoff-8bf-addendum-20261112/README.md": (
        "e9f06ad0392d1dba0bbb16c19b8243bd24affa5c56408cefb2ca504127225173"
    ),
    "qualification/learn-ordinary-ce434/positive-model-version-20261112/original-policy-eligibility-audit.md": (
        "701980a419884d9ad5d49e054a22d691e57545d21eb83a6c898100440f391a06"
    ),
}

MAX_BYTES = 8 * 1024 * 1024


def relative_path(name):
    if not isinstance(name, str) or "\\" in name or ":" in name or "\0" in name:
        raise ValueError("evidence path must use repository-relative syntax")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence path must remain relative to the repository")
    if path.as_posix() != name or not path.parts:
        raise ValueError("evidence path must be canonical")
    return path


def identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def read_regular(repo, relative, limit):
    path = repo / relative_path(relative)
    if not 0 <= limit <= MAX_BYTES:
        raise ValueError("invalid evidence byte bound")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("evidence parent must not be a symbolic link")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("evidence must be a regular single-link file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(opened) != identity(before):
            raise ValueError("evidence changed before reading")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (
        identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
        or len(data) > limit
    ):
        raise ValueError("evidence changed during reading or exceeds its bound")
    return data


def entries(repo):
    result = {}
    for index, expected in INDEX_SHA256.items():
        raw = read_regular(repo, index, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("registered evidence storage inventory changed")
        document = json.loads(raw)
        if document["schema"] != "hepta.raw-evidence.storage.v1":
            raise ValueError("unsupported raw evidence storage schema")
        for entry in document["files"]:
            name = relative_path(entry["original_path"]).as_posix()
            if name in result or entry["stored_path"] != name + ".evidence.gz":
                raise ValueError("duplicate or inconsistent stored evidence path")
            result[name] = entry
    return result


def read_verified(repo, relative, expected_bytes, expected_sha256, *, index=None):
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_BYTES:
        raise ValueError("invalid original evidence byte bound")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise ValueError("invalid original evidence checksum")
    relative = relative_path(str(relative)).as_posix()
    path = repo / relative
    display_digest = ARCHIVE_NOTICE_SHA256.get(relative)
    # A pinned active view can be larger than its archived original. This
    # only widens the bounded read; both exact digests are still required.
    source_limit = max(expected_bytes, 16 * 1024) if display_digest else expected_bytes
    data = (
        read_regular(repo, relative, source_limit)
        if path.exists() or path.is_symlink()
        else None
    )
    if data is None or (
        display_digest is not None and hashlib.sha256(data).hexdigest() == display_digest
    ):
        entry = (entries(repo) if index is None else index)[relative]
        if (
            entry["original_bytes"] != expected_bytes
            or entry["original_sha256"] != expected_sha256
        ):
            raise ValueError("storage index differs from the original manifest")
        compressed = read_regular(repo, entry["stored_path"], entry["stored_bytes"])
        if (
            len(compressed) != entry["stored_bytes"]
            or hashlib.sha256(compressed).hexdigest() != entry["stored_sha256"]
        ):
            raise ValueError("stored evidence checksum mismatch")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(compressed, expected_bytes + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(data) != expected_bytes
        ):
            raise ValueError("truncated, oversized or concatenated gzip evidence")
    if (
        len(data) != expected_bytes
        or hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise ValueError("original evidence length or checksum mismatch")
    return data


def read_frozen_source(repo, path, expected, index, *, require_current_view=False):
    raw = read_regular(repo, path, 256 * 1024)
    active_digest = hashlib.sha256(raw).hexdigest()
    approved_view = ARCHIVE_NOTICE_SHA256.get(path)
    if active_digest == expected and (not require_current_view or approved_view is None):
        return raw
    if approved_view != active_digest or path not in index:
        raise ValueError(f"active source differs from its frozen view: {path}")
    return read_verified(repo, path, index[path]["original_bytes"], expected, index=index)


def replay_source_freeze(repo, freeze_path, freeze_sha256, verifier_sha256=None):
    """Run an unchanged source-only verifier using its exact frozen tree."""
    freeze_path = relative_path(freeze_path)
    index = entries(repo)
    freeze_bytes = read_frozen_source(repo, freeze_path.as_posix(), freeze_sha256, index)
    manifest = json.loads(freeze_bytes)
    frozen = manifest["files"]
    bound_originals = manifest.get("bound_originals", {})
    verifier = freeze_path.with_name("verify_source.py")
    if verifier_sha256 is not None:
        # Earlier verifiers pinned extra parents in immutable source rather
        # than in their manifests. Read those literals from the pinned copy.
        original = read_frozen_source(repo, verifier.as_posix(), verifier_sha256, index)
        parent_bindings = {}
        for statement in ast.parse(original).body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            symbol = statement.targets[0]
            if not isinstance(symbol, ast.Name):
                continue
            if symbol.id == "EXPECTED" and ast.literal_eval(statement.value) != frozen:
                raise ValueError("pinned verifier differs from its source freeze")
            if symbol.id in {"PARENTS", "BOUND"}:
                parent_bindings.update(ast.literal_eval(statement.value))
        if parent_bindings.keys() & frozen.keys() or verifier.as_posix() in frozen:
            raise ValueError("pinned verifier duplicates a frozen source binding")
        frozen = {**frozen, **parent_bindings, verifier.as_posix(): verifier_sha256}
    if verifier.as_posix() not in frozen:
        raise ValueError("source freeze does not pin its original verifier")
    if bound_originals.keys() & frozen.keys():
        raise ValueError("source freeze duplicates a bound original")
    frozen = {**frozen, **bound_originals}

    with tempfile.TemporaryDirectory(prefix="hepta-frozen-source-") as scratch:
        original = Path(scratch)
        original_freeze = original / freeze_path
        original_freeze.parent.mkdir(parents=True)
        original_freeze.write_bytes(freeze_bytes)
        for path, expected in frozen.items():
            relative = relative_path(path)
            raw = read_frozen_source(repo, path, expected, index)
            destination = original / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)

        # Import only the restored module and its standard dependencies, not
        # the current checkout, the inherited PYTHONPATH, or user site code.
        optimization = ["-" + "O" * sys.flags.optimize] if sys.flags.optimize else []
        module = ".".join(verifier.with_suffix("").parts)
        subprocess.run(
            [sys.executable, "-B", "-E", "-s", *optimization, "-m", module],
            cwd=original, stdin=subprocess.DEVNULL, check=True,
        )


def restore(repo, destination):
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination must be a new directory")
    if not destination.parent.is_dir() or any(
        p.is_symlink() for p in destination.parents
    ):
        raise ValueError("destination parent must be an existing regular directory")
    if destination.is_relative_to(repo):
        raise ValueError("destination must be outside the repository")
    outputs = []
    for name, entry in entries(repo).items():
        data = read_verified(
            repo, name, entry["original_bytes"], entry["original_sha256"]
        )
        blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if blob != entry["original_git_blob"]:
            raise ValueError("original Git blob mismatch")
        outputs.append((name, data))
    destination.mkdir(mode=0o700)
    for name, data in outputs:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    print(f"Restored {len(outputs)} exact historical evidence files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parents[3], arguments.destination)
