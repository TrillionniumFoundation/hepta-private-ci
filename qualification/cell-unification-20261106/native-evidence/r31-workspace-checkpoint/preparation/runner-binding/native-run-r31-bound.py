"""INERT source53 r31 default workspace diagnostic-source gate.

Only actual same-source r30 strict/full-app-server PASS and natural outer0
can admit fresh193 metadata and the original no-p workspace command.
R28 four-package/Python PASS remains source52 historical evidence; R29
failed100 stays unchanged. Exact original20228 IDs are post-gate acceptance
only. No apply, locks update, retry, filter, feature change, fix or fmt.
Source53 is diagnostic-only; passing it does not prove a behavior repair.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

FROZEN = False
EXPECTED_COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
EXPECTED_TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
EXPECTED_CHANGED_COUNT = 197
SOURCE_MANIFEST_NAME = 'native-candidate-r30-source.json'
SOURCE_MANIFEST_SHA256 = '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda'
CARGO_LOCK_SHA256 = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_LOCK_SHA256 = 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
LOCK_INPUT_PINS = {'complete.json': {'bytes': 2292, 'sha256': '141820576f72e474b614a75b7414f1508575e636fca059b5593ab36ec05f8b7c'}, 'postguard.json': {'bytes': 1250, 'sha256': '835e143f4ebc54028640e25df8fef74e7fc3bf1a55caca4027e4e4c2ba7c20fe'}, 'generated-source.json': {'bytes': 52992, 'sha256': '7e5b9d8ba537cc527f94154ae405382ac4197e217d14a44a6c48d4e70099fe97'}, 'lock-update-raw-process-result.json': {'bytes': 384, 'sha256': '625775accc1f9507cb142f9b34a6d81aac05885ca4459b94eaf36b1d7e8839a8'}, 'lock-update-receipt.json': {'bytes': 777, 'sha256': 'dce6237eabf6c713e750dd6f6d5d8ac1336c98ab90a03a63b831a5cf0f503007'}, 'lock-update.log': {'bytes': 2808, 'sha256': '580619bbafa9c83e4d461572f7d138531b14d8cfb078be0933fc9467d8ebfff2'}, 'lock-update.resources.txt': {'bytes': 752, 'sha256': '95bc589bd25490158644c6c5eebae3f3e6a491be76565824b0fc0eb8cf7fc3bb'}}
LOCK_TERMINAL_NAME = 'native-source50-lock-update/terminal-process-status.json'
LOCK_TERMINAL_SHA256 = '9f983f56f14016b31725f9bb75dc8b4c8772a3e69581b7387afa5fdaaddfeda0'
LOCK_TERMINAL_BYTES = 729
LOCK_JOB_ID = '1a1b16cb87c-fc05-7898'
BASELINE_NAME = "source53-app-server-r29-baseline.json"

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
E = T / "evidence"
LOCK_DIRECTORY = E / "native-source50-lock-update"
FRAMEWORK_PARENT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
PREFIX = "native-workspace-r31"
PACKAGES = ["codex-app-server"]
LOCK_FILES = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
LOCK_EVIDENCE_FILES = (
    "complete.json", "postguard.json", "generated-source.json",
    "lock-update-raw-process-result.json", "lock-update-receipt.json",
    "lock-update.log", "lock-update.resources.txt",
)
BASELINE_SHA256 = "92e7ef41b0c2b08b81bb3ad9542f20ec820d86185f80369b4478cb5bd9c20cf1"
BASELINE_BYTES = 555309
BASELINE_COUNT = 1345
# All future apply/source53 identities remain explicitly unbound.
APPLY_COMPLETE_NAME = 'native-source53-apply/complete.json'
APPLY_COMPLETE_SHA256 = '5934056021848d5203e40458f97654556b97c113155a5512ed469c8df26efd93'
APPLY_COMPLETE_BYTES = 2220
APPLY_TERMINAL_NAME = 'native-source53-apply-v2-terminal-process-status.json'
APPLY_TERMINAL_SHA256 = '3b08ecbd4669fc5f171ea91e2a627fe84dd6aa924b0b39441698262703e3194b'
APPLY_TERMINAL_BYTES = 729
APPLY_JOB_ID = '1a1b2552130-fc05-7d91'
DELTA_MANIFEST_NAME = 'native-source53-apply/input/delta-manifest.json'
DELTA_MANIFEST_SHA256 = '26ade20e3c00fcd2e37b922b0d0f3caad1354af39767cd3fd35aafd3d7d99cf4'
DELTA_MANIFEST_BYTES = 1749

LOCK_SOURCE50_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
LOCK_SOURCE50_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
LOCK_SOURCE50_CHANGED_COUNT = 194
SOURCE50_MANIFEST_NAME = "native-candidate-r24-source.json"
SOURCE50_MANIFEST_BYTES = 53832
SOURCE50_MANIFEST_SHA256 = "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"
ALLOWED_SOURCE51_DELTA = (
    "codex-rs/exec-server/tests/common/fake_bwrap.rs",
    "codex-rs/network-proxy/src/http_proxy.rs",
)
R24_JOB_ID = "1a1b17f112c-fc05-792a"
R24_FAILURE_PINS = {
    "native-source50-project-r24-terminal-process-status.json": {
        "bytes": 730, "sha256": "644e58b095e57c8b037cb282aa1da04f50501cb04b7c3f472d18e48272cda14f",
    },
    "native-source50-project-r24-tests-raw-process-result.json": {
        "bytes": 637, "sha256": "052f63cb18e5fb4ff97004286a336ada1437ac7484826895c059497fb139125c",
    },
    "native-source50-project-r24-tests-receipt.json": {
        "bytes": 2314, "sha256": "cfd55b78649de4920ea9a3307b1fdfd6f9674b757cf39586cfa45bcee927e3af",
    },
    "native-source50-project-r24-tests-source-post-verification.json": {
        "bytes": 633, "sha256": "5188c63a461f0f3f0a11a3c238b2df7aceb97f8f599c48e53dba15514d358728",
    },
}

SOURCE51_COMMIT = "e28b0f385ee882f842911044958b2810f62f6379"
SOURCE51_TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
SOURCE51_CHANGED_COUNT = 194
SOURCE51_MANIFEST_NAME = "native-candidate-r26-source.json"
SOURCE51_MANIFEST_BYTES = 55418
SOURCE51_MANIFEST_SHA256 = "74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a"
ALLOWED_SOURCE52_DELTA = ("codex-rs/network-proxy/src/runtime.rs",)

HISTORICAL_FOUR_PACKAGES = ["codex-cli", "codex-exec-server", "codex-network-proxy", "codex-external-agent-migration"]
DIAGNOSTIC_ONLY = True
SOURCE52_COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
SOURCE52_TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
SOURCE52_CHANGED_COUNT = 195
SOURCE52_MANIFEST_NAME = "native-candidate-r28-source.json"
SOURCE52_MANIFEST_BYTES = 55209
SOURCE52_MANIFEST_SHA256 = "3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898"
ALLOWED_SOURCE53_DELTA = (
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
    "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs",
)
R29_JOB_ID = "1a1b1f83e4b-fc05-7bcd"
R29_FAILURE_PINS = {
    "native-workspace-r29-terminal-process-status.json": {
        "bytes": 730, "sha256": "9577b5c1f87e1f529edffcb262683067d0379dc4a9b16c84a2a43c68388374bf",
    },
    "native-workspace-r29-tests-raw-process-result.json": {
        "bytes": 500, "sha256": "c840e6ff388a9863aee1dce8b0bc148446ee6541025a7c7ba8b4ec96196d43c8",
    },
    "native-workspace-r29-tests-receipt.json": {
        "bytes": 2782, "sha256": "9ca2e64a0ff00b86840d76c2003caf7608965719e481a541235e43d462bd574a",
    },
    "native-workspace-r29-source-post-test-verification.json": {
        "bytes": 643, "sha256": "e116303f0a7fac5b3d9f79ca3471331c9be7640120b124585ce2a61c70623703",
    },
}

LOCK_INHERITANCE_RUST_PATHS = ALLOWED_SOURCE51_DELTA + ALLOWED_SOURCE52_DELTA + ALLOWED_SOURCE53_DELTA
R26_JOB_ID = "1a1b1b739ee-fc05-7a70"
R26_FAILURE_PINS = {
    "native-source51-project-r26-terminal-process-status.json": {
        "bytes": 730, "sha256": "c7f2154976a0df45dc721e6fefcfc5089f98c048c3755549464a257d11a1033a",
    },
    "native-source51-project-r26-tests-raw-process-result.json": {
        "bytes": 635, "sha256": "ac2729d6bd5424bc5744baa7625aa64daccd429b90f7e172e2f17c764fb112c2",
    },
    "native-source51-project-r26-tests-receipt.json": {
        "bytes": 2312, "sha256": "dd6e5fa8629a57f90774282d70a1a81fe641faaec7ca0e0a89590522bfdf7cf3",
    },
    "native-source51-project-r26-tests-source-post-verification.json": {
        "bytes": 633, "sha256": "f94acb64e0b875228625feac0a9485efbd3bf68d2058447130abcb1e4c15ea4b",
    },
}


MIN_FREE_BYTES = 20 * 1024**3
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
FILE_KEYS = ("path", "bytes", "sha256", "git_blob", "mode")



# Known historical originals are separate from every future r30 closure.
SOURCE_MANIFEST_BYTES = 56747
R30_PREFIX = 'native-source53-project-r30'
R30_INPUT_PINS = {'native-source53-project-r30-complete.json': {'bytes': 1904, 'sha256': '484414f82e700f79ee491dbb181c037e19ffea84cfa46ed491b9be083604500b'}, 'native-source53-project-r30-environment.json': {'bytes': 1404, 'sha256': 'b307ac5e863b22dbd8beb8d5126059e062449d70fc9dbc4c96836b2b6836c9d4'}, 'native-source53-project-r30-preconditions.json': {'bytes': 11176, 'sha256': 'f800262173d2a72be4cfa2db2c1214aa8ec786b93766df3d403a85dc5bef3d58'}, 'native-source53-project-r30-source-final-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5'}, 'native-source53-project-r30-source-pre-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5'}, 'native-source53-project-r30-strict-raw-process-result.json': {'bytes': 535, 'sha256': '0c9b0aef317c6dc152637cd6a1bbb2686c897b9ef2c2b73bd0cba7a35c06c170'}, 'native-source53-project-r30-strict-receipt.json': {'bytes': 1842, 'sha256': '9a7c05149f620d5a9b4f20c9c21758bc412386c363a4202f6777e47615566b42'}, 'native-source53-project-r30-strict-resources.txt': {'bytes': 802, 'sha256': 'd8879ec8f72cc32c0e657ac2f769ed367ac3c9baec5a914d87b360063571e540'}, 'native-source53-project-r30-strict-source-post-verification.json': {'bytes': 632, 'sha256': 'e09604f678e7fad9cc55870a9fc58a3acd3133141a8bb7fd68a540253b86ebe8'}, 'native-source53-project-r30-strict-source-pre-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5'}, 'native-source53-project-r30-strict.log': {'bytes': 11625, 'sha256': 'e8778c2ed53a38a41c85aa9bfeddf33e0350b20cb7e065f144d609621ba81a33'}, 'native-source53-project-r30-tests-raw-process-result.json': {'bytes': 522, 'sha256': '2df64589cf5b4b7201889af325bac0ef88457aeb444bbb45ee55f31bd60d99fa'}, 'native-source53-project-r30-tests-receipt.json': {'bytes': 2052, 'sha256': '39345148c8689bce57af61b47dca534db4e2dd80e72cc0b1bec5933129d165d5'}, 'native-source53-project-r30-tests-resources.txt': {'bytes': 808, 'sha256': '8227160babdded4fa5fb38565bb9896555d72dab3d4ed5de80bbb51f79d77764'}, 'native-source53-project-r30-tests-result-review.json': {'bytes': 1304, 'sha256': 'a3978d29cf0603bb7f2b9bbc01057252b1340ad0fa9521d86d5593c2a12d3cb2'}, 'native-source53-project-r30-tests-source-post-verification.json': {'bytes': 631, 'sha256': '9df5d2dcbf24909a177765ee9112d46545650fcd408c3167dbcd21c281a50890'}, 'native-source53-project-r30-tests-source-pre-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5'}, 'native-source53-project-r30-tests-test-results.json': {'bytes': 319763, 'sha256': '983ea2651aa1564afbc6ab901012112cc602bf727441bdc014c1bc611c2b777f'}, 'native-source53-project-r30-tests.log': {'bytes': 221127, 'sha256': 'f9dc6ce6b656b146658ad7d28b377c4c69046d54d6c8e52656c620d84612a88c'}}
R30_JOB_ID = '1a1b25b399f-fc05-7daa'
R30_TERMINAL_NAME = 'native-source53-project-r30-terminal-process-status.json'
R30_TERMINAL_SHA256 = '714f22dd64a60d5d9abb932c94c30803d081f365d1dd8ef06afc45d2ea7ede1d'
R30_TERMINAL_BYTES = 731
R30_PHASES = ('strict', 'tests')
R28_PHASES = ('python-runner', 'strict', 'tests')
PYTHON_TEST_COUNT = 32
COMMAND = ['just', 'test', '--locked', '--retries', '0']
METADATA_COMMAND = ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1']
EXPECTED_WORKSPACE_MEMBER_COUNT = 193
OUTER_TIMEOUT_SECONDS_CONTRACT = 9600
R28_PREFIX = 'native-source52-project-r28'
R28_INPUT_PINS = {'native-source52-project-r28-complete.json': {'bytes': 2152, 'sha256': '993d9a48333d093218a42cb8943f02b88d0e4a151354e8522dc1b51cbfea0b4d'}, 'native-source52-project-r28-environment.json': {'bytes': 1341, 'sha256': 'c892f430fe66420367fd086c9cb2f39158520872ef55409dd222b00adc6825ee'}, 'native-source52-project-r28-preconditions.json': {'bytes': 9513, 'sha256': '741cd5aa598adecb7d2a2c3a4f976e672aac0b6b84697785bfffbdc6a5ed618e'}, 'native-source52-project-r28-python-runner-raw-process-result.json': {'bytes': 551, 'sha256': '51d4478678c3776377e3cc9874e858319f41ad9bf091f36549b5324dc176cc94'}, 'native-source52-project-r28-python-runner-receipt.json': {'bytes': 2018, 'sha256': '132959ea0f647cdfc6bebf2ad1c6df1932cabaaf478df6766a9efe1b5cc1214c'}, 'native-source52-project-r28-python-runner-resources.txt': {'bytes': 799, 'sha256': 'b8f3cadb21631aa89ed6461c53c6578185e61201efe71d236849f77b33c11d36'}, 'native-source52-project-r28-python-runner-result-review.json': {'bytes': 573, 'sha256': '5ea50ce13ede9ded54defce0016eb9cfe02dba91e85bb8ade97639d14ec0e56d'}, 'native-source52-project-r28-python-runner-source-post-verification.json': {'bytes': 639, 'sha256': '4c3e8e822a1607b0b0073b9f09cfc07b20161997db7783d3c907c3a56666cb8c'}, 'native-source52-project-r28-python-runner-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-python-runner.log': {'bytes': 8449, 'sha256': '2eb07b7f4af98d408131099bf8980c3ac298d4447b4b5a6334634696c5f78d78'}, 'native-source52-project-r28-source-final-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-strict-raw-process-result.json': {'bytes': 648, 'sha256': 'ba9571183c1718b35852a662348685b649df801ca7a8d81b997b1eabf8ee65f0'}, 'native-source52-project-r28-strict-receipt.json': {'bytes': 1974, 'sha256': '72c3fc2b3eb14f24f921b00126b3cd0f97fb25001c3d2b7f616f5d0b9807dc33'}, 'native-source52-project-r28-strict-resources.txt': {'bytes': 875, 'sha256': '86a4a7cd6a1d6c0f1256c3f1b08673c7a2007a2b7d79517040e05f61e7324399'}, 'native-source52-project-r28-strict-source-post-verification.json': {'bytes': 632, 'sha256': 'fccf765f216c237050d82ac572f35d4820ba9c0b053280daf03e7c6b160b8288'}, 'native-source52-project-r28-strict-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-strict.log': {'bytes': 13645, 'sha256': 'a0ee362bdfc5f2811b26ee60bc0f4310003a786a27cd3190a48bdf064c656231'}, 'native-source52-project-r28-tests-raw-process-result.json': {'bytes': 634, 'sha256': 'cf8237de117ec35091a76f9aa19616bfbddf565902cf260b00a3c67c7b8942b5'}, 'native-source52-project-r28-tests-receipt.json': {'bytes': 2185, 'sha256': '5c9e23a6af959cb85cc6fb51ac64c9007598a0fc6e5249cc08317fc32eab94c9'}, 'native-source52-project-r28-tests-resources.txt': {'bytes': 874, 'sha256': '3bc47b2c37fba391808302569702b55882256cd22b31cdbc88fdd780f604b774'}, 'native-source52-project-r28-tests-result-review.json': {'bytes': 1530, 'sha256': '17be2fef913175a3a52d17d71a9a1d7d98006727c6e8531afbf9e7b1fd1ac314'}, 'native-source52-project-r28-tests-source-post-verification.json': {'bytes': 631, 'sha256': '2ef89440340e634d1e74643eb0b73091af88570fec8e6e7c3a6a3a1c3fafa023'}, 'native-source52-project-r28-tests-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-tests-test-results.json': {'bytes': 345527, 'sha256': '2963674ed389a0ba770355c56ba6eaeecc85c253a9c80b73e98b20f709d721c6'}, 'native-source52-project-r28-tests.log': {'bytes': 216247, 'sha256': '1af36d6404dff5026eca008da904354e4346523cb7cdca4d1231a59036d18347'}}
R28_JOB_ID = '1a1b1e9bee0-fc05-7b7c'
R28_TERMINAL_NAME = 'native-source52-project-r28-terminal-process-status.json'
R28_TERMINAL_SHA256 = '897df3ad774667b7fab516e0d93fc3c68c43eb4c6c91e713207326feb9cd1458'
R28_TERMINAL_BYTES = 731
PREVIOUS_SOURCE49_COMMIT = '50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a'
PREVIOUS_SOURCE49_TREE = 'be34ab1afe622ad3b8f030c8c5018f4f54fbc304'
HISTORICAL_BASELINE_NAME = 'source50-four-package-r23-baseline.json'
HISTORICAL_BASELINE_SHA256 = '6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e'
HISTORICAL_BASELINE_BYTES = 277789
HISTORICAL_BASELINE_COUNT = 1564
HISTORICAL_APPLY_COMPLETE_NAME = 'native-source52-apply/complete.json'
HISTORICAL_APPLY_COMPLETE_SHA256 = 'c9ecdc0ba8a34cd9f1a0a9bccb5e4d58034ce21558fe619d7351ca3e8eccfa14'
HISTORICAL_APPLY_COMPLETE_BYTES = 2046
HISTORICAL_APPLY_TERMINAL_NAME = 'native-source52-apply-terminal-process-status.json'
HISTORICAL_APPLY_TERMINAL_SHA256 = 'aa92d5cf988a3f2a1ea434dcdd4c39274c2c783cd69609edc04da655e3457a9e'
HISTORICAL_APPLY_TERMINAL_BYTES = 729
HISTORICAL_APPLY_JOB_ID = '1a1b1e474a3-fc05-7b5b'
HISTORICAL_DELTA_MANIFEST_NAME = 'native-source52-apply/input/delta-manifest.json'
HISTORICAL_DELTA_MANIFEST_SHA256 = '0e9d938287ebc74d89e2bcaf2a102e7a83c063aac5705009ebd2eeb327af571a'
HISTORICAL_DELTA_MANIFEST_BYTES = 1116
R29_WORKSPACE_BASELINE_INPUT_PINS = {'native-workspace-r29-tests.log': {'bytes': 2499408, 'sha256': '3a95dcc8f0c486594fe3ff41c50fcaaa363bf00533f3ab7d37330e1c757a8559'}, 'native-workspace-r29-test-results.json': {'bytes': 4586810, 'sha256': '2070a63e9b17a64f75f447c39bb3a7d00a91c0273810fdb86ded4656318b9930'}, 'native-workspace-r29-result-review.json': {'bytes': 1775, 'sha256': '6cd91d2003e8fcd5eb576b5db22559683dfa5a4f0259e7a545f07d4580cb9004'}, 'native-workspace-r29-metadata.json': {'bytes': 937659, 'sha256': 'b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d'}}

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def data_pin(raw):
    return {
        "bytes": len(raw), "sha256": sha(raw),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }

def safe_relative(value):
    require(isinstance(value, str) and bool(value), "missing relative path binding")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe evidence/source path")
    return path

def hex_digest(value, width):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(width) + r"}", value) is not None

def check_source_bindings():
    # Preparation and missing-input barriers are not removable with Python -O.
    require(FROZEN is True, "INERT PREPARATION: no gate may execute")
    require(sys.flags.optimize == 0, "optimized Python is not an approved executor")
    require(os.environ.get("PYTHONOPTIMIZE") in (None, "", "0"), "optimized child Python is not approved")
    require(hex_digest(EXPECTED_COMMIT, 40) and hex_digest(EXPECTED_TREE, 40), "actual source53 identity missing")
    require(EXPECTED_COMMIT not in (LOCK_SOURCE50_COMMIT, SOURCE51_COMMIT, SOURCE52_COMMIT)
            and EXPECTED_TREE not in (LOCK_SOURCE50_TREE, SOURCE51_TREE, SOURCE52_TREE),
            "new source53 identity was not bound")
    require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT == 197,
            "actual source53 changed count must be 197")
    for value in (
        SOURCE_MANIFEST_SHA256, CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256,
        LOCK_TERMINAL_SHA256, APPLY_COMPLETE_SHA256, APPLY_TERMINAL_SHA256,
        DELTA_MANIFEST_SHA256, BASELINE_SHA256,
    ):
        require(hex_digest(value, 64), "actual source/dual-lock/apply/terminal/baseline hash missing")
    for name in (
        SOURCE_MANIFEST_NAME, LOCK_TERMINAL_NAME, BASELINE_NAME,
        APPLY_COMPLETE_NAME, APPLY_TERMINAL_NAME, DELTA_MANIFEST_NAME,
    ):
        safe_relative(name)
        require(not name.startswith(PREFIX + "-"), "input name collides with create-only output prefix")
    for value in (LOCK_TERMINAL_BYTES, APPLY_COMPLETE_BYTES, APPLY_TERMINAL_BYTES,
                  DELTA_MANIFEST_BYTES, BASELINE_BYTES):
        require(type(value) is int and value > 0, "actual closure byte count missing")
    for value in (LOCK_JOB_ID, APPLY_JOB_ID):
        require(isinstance(value, str) and bool(value), "actual closed job ID missing")
    require(APPLY_JOB_ID not in (LOCK_JOB_ID, R24_JOB_ID, R26_JOB_ID, R29_JOB_ID),
            "apply job identity reused")
    require(isinstance(LOCK_INPUT_PINS, dict) and set(LOCK_INPUT_PINS) == set(LOCK_EVIDENCE_FILES),
            "seven source50 lock input pins required")
    for name, expected in LOCK_INPUT_PINS.items():
        require(type(expected["bytes"]) is int and expected["bytes"] >= 0, "lock input size missing: " + name)
        require(hex_digest(expected["sha256"], 64), "lock input hash missing: " + name)
    require(PACKAGES == ["codex-app-server"] and DIAGNOSTIC_ONLY is True,
            "this prepared runner is only the complete app-server diagnostic source gate")

def write_json(name, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    path = E / safe_relative(name)
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {"path": name, **data_pin(raw)}

def announce(value):
    try:
        print(json.dumps(value), flush=True)
    except OSError:
        pass

def git(*args):
    return subprocess.check_output(["git", *args], cwd=S)

def git_paths(*args):
    return [raw.decode() for raw in git(*args).split(b"\0") if raw]

def normalized_files(entries):
    require(isinstance(entries, list), "source files must be a list")
    result = {}
    for entry in entries:
        row = {key: entry[key] for key in FILE_KEYS}
        safe_relative(row["path"])
        require(row["mode"] in ("100644", "100755"), "unsupported source mode")
        require(row["path"] not in result, "duplicate source path")
        result[row["path"]] = row
    return result

def source_file_pin(path):
    relative = safe_relative(path)
    target = S / relative
    require(target.is_file() and not target.is_symlink(), "source is not a regular file: " + path)
    raw = target.read_bytes()
    record = git("ls-tree", "-z", EXPECTED_TREE, "--", path).rstrip(b"\0")
    header, actual_path = record.split(b"\t", 1)
    mode, kind, blob = header.decode().split()
    actual = data_pin(raw)
    actual_mode = "100755" if target.stat().st_mode & 0o111 else "100644"
    require(actual_path.decode() == path and kind == "blob", "tree path/type mismatch")
    require(mode == actual_mode and blob == actual["git_blob"], "worktree/index source identity mismatch")
    return {"path": path, **actual, "mode": mode}

def guard(files):
    result = {
        "expected_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "changed_file_count": len(files), "pass": False,
    }
    try:
        result["actual_tree"] = git("write-tree").decode().strip()
        result["native_head"] = git("rev-parse", "HEAD").decode().strip()
        result["unstaged_paths"] = git_paths("diff", "--name-only", "-z")
        result["untracked_paths"] = git_paths("ls-files", "--others", "--exclude-standard", "-z")
        actual_paths = git_paths("diff", "--no-renames", "--name-only", "-z", FRAMEWORK_PARENT, EXPECTED_TREE)
        result["changed_path_set_matches"] = set(actual_paths) == set(files) and len(actual_paths) == len(files)
        mismatches = []
        for path, expected in files.items():
            try:
                if source_file_pin(path) != expected:
                    mismatches.append({"path": path, "error": "raw/Git/mode mismatch"})
            except Exception as error:
                mismatches.append({"path": path, "error": repr(error)})
        result["file_mismatches"] = mismatches
        result["cargo_lock_sha256"] = sha((S / LOCK_FILES[0]).read_bytes())
        result["bazel_lock_sha256"] = sha((S / LOCK_FILES[1]).read_bytes())
        result["pass"] = (
            result["actual_tree"] == EXPECTED_TREE
            and result["native_head"] == FRAMEWORK_PARENT
            and not result["unstaged_paths"] and not result["untracked_paths"]
            and not mismatches and result["changed_path_set_matches"]
            and result["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and result["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
    except Exception as error:
        result["guard_error"] = repr(error)
    return result

def lock_prerequisite():
    originals = {}
    pins = []
    for name in LOCK_EVIDENCE_FILES:
        raw = (LOCK_DIRECTORY / name).read_bytes()
        expected = LOCK_INPUT_PINS[name]
        require(len(raw) == expected["bytes"] and sha(raw) == expected["sha256"], "lock original pin mismatch: " + name)
        originals[name] = raw
        pins.append({"path": "native-source50-lock-update/" + name, **data_pin(raw)})
    raw_result = json.loads(originals["lock-update-raw-process-result.json"])
    receipt = json.loads(originals["lock-update-receipt.json"])
    post = json.loads(originals["postguard.json"])
    complete = json.loads(originals["complete.json"])
    generated = json.loads(originals["generated-source.json"])
    require(raw_result["schema"] == "hepta.original-command-raw-result.v1", "lock raw schema mismatch")
    for value in (raw_result, receipt):
        require(value["exit_code"] == 0, "original lock command did not pass")
        require(value["command"] == ["just", "bazel-lock-update"] and value["cwd"] == str(S), "wrong original lock command")
    for key in ("command", "cwd", "source_tree_before_command", "exit_code", "started_unix", "ended_unix", "elapsed_seconds"):
        require(raw_result[key] == receipt[key], "lock raw/receipt mismatch: " + key)
    require(receipt["ended_unix"] >= receipt["started_unix"], "invalid lock time order")
    require(abs(receipt["elapsed_seconds"] - (receipt["ended_unix"] - receipt["started_unix"])) < 1e-6, "lock elapsed mismatch")
    require(receipt["log"] == data_pin(originals["lock-update.log"]), "lock log receipt mismatch")
    require(receipt["resources"] == data_pin(originals["lock-update.resources.txt"]), "lock resource receipt mismatch")
    require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", originals["lock-update.resources.txt"], re.M) == [b"0"], "lock resource exit mismatch")
    require(complete["status"] == "LOCK_UPDATE_PASSED_SOURCE_FREEZE_PENDING", "unexpected closed lock status")
    require(complete["receipt"] == receipt and complete["postguard"] == post, "closed lock embedded originals differ")
    require(post["schema"] == "hepta.source50-lock-postguard.v1" and post["guard_pass"] is True, "lock postguard failed")
    require(post["generated_source_tree"] == LOCK_SOURCE50_TREE, "historical source50 generated tree mismatch")
    require(post["actual_changed_file_count"] == LOCK_SOURCE50_CHANGED_COUNT, "actual generated count mismatch")
    require(set(post["working_tree_changed_paths"]) <= set(LOCK_FILES), "unexpected generated lock path")
    require(generated["schema"] == "hepta.source50-generated-lock-source.v1", "generated source schema mismatch")
    require(generated["source_tree"] == LOCK_SOURCE50_TREE and generated["source_commit"] is None, "generated original identity mismatch")
    require(generated["root_source_identity_freeze_pending"] is True, "original generated snapshot was rewritten")
    require(generated["provisional_before_lock_tree"] == raw_result["source_tree_before_command"], "lock before tree mismatch")
    require(post["source_tree_index_before_lock_stage"] == generated["provisional_before_lock_tree"], "lock index provenance mismatch")
    require(generated["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and generated["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "generated dual-lock mismatch")
    for path, expected_sha in zip(LOCK_FILES, (CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256)):
        require(post["locks"][path]["after"] == data_pin((S / path).read_bytes()), "lock postguard bytes mismatch")
        require(post["locks"][path]["after"]["sha256"] == expected_sha, "bound lock mismatch")
    for value in (post, complete):
        require(value["rust_tests_started"] is False and value["fix_fmt_executed"] is False, "lock snapshot phase confusion")
    terminal_raw = (E / safe_relative(LOCK_TERMINAL_NAME)).read_bytes()
    require(len(terminal_raw) == LOCK_TERMINAL_BYTES and sha(terminal_raw) == LOCK_TERMINAL_SHA256, "lock outer terminal pin mismatch")
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == LOCK_JOB_ID and terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "lock outer did not naturally succeed")
    for key in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[key] is False, "lock outer state invalid: " + key)
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "lock terminal output incomplete: " + key)
    require(terminal["at_unix_ms"] / 1000 >= receipt["ended_unix"], "lock terminal precedes command end")
    pins.append({"path": LOCK_TERMINAL_NAME, **data_pin(terminal_raw)})
    return generated, pins

def load_source(generated):
    old_raw = (E / SOURCE50_MANIFEST_NAME).read_bytes()
    require(len(old_raw) == SOURCE50_MANIFEST_BYTES and sha(old_raw) == SOURCE50_MANIFEST_SHA256,
            "historical source50 root manifest mismatch")
    old = json.loads(old_raw)
    require(old["source_tree"] == LOCK_SOURCE50_TREE and old["source_commit"] == LOCK_SOURCE50_COMMIT,
            "historical source50 root identity mismatch")
    require(old["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and old["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "source50 dual-lock mismatch")
    old_files = normalized_files(old["changed_files"])
    require(len(old_files) == LOCK_SOURCE50_CHANGED_COUNT, "historical source50 count mismatch")
    require(old_files == normalized_files(generated["changed_files"]),
            "source50 root manifest differs from original lock-generated source")

    prior_raw = (E / SOURCE51_MANIFEST_NAME).read_bytes()
    require(len(prior_raw) == SOURCE51_MANIFEST_BYTES and sha(prior_raw) == SOURCE51_MANIFEST_SHA256,
            "source51 historical manifest mismatch")
    prior = json.loads(prior_raw)
    require(prior["source_commit"] == SOURCE51_COMMIT and prior["source_tree"] == SOURCE51_TREE,
            "source51 historical identity mismatch")
    require(prior["source_parent_commit"] == LOCK_SOURCE50_COMMIT, "source51 historical parent mismatch")
    require(prior["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and prior["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "source51 historical dual-lock mismatch")
    prior_files = normalized_files(prior["changed_files"])
    require(len(prior_files) == SOURCE51_CHANGED_COUNT and set(prior_files) == set(old_files),
            "source50/source51 changed path set mismatch")
    require({path for path in prior_files if prior_files[path] != old_files[path]} == set(ALLOWED_SOURCE51_DELTA),
            "source50/source51 manifest delta mismatch")
    require(not (set(ALLOWED_SOURCE52_DELTA) & set(prior_files)), "runtime was already in source51 changed manifest")

    parent_raw = (E / SOURCE52_MANIFEST_NAME).read_bytes()
    require(len(parent_raw) == SOURCE52_MANIFEST_BYTES and sha(parent_raw) == SOURCE52_MANIFEST_SHA256,
            "source52 parent manifest mismatch")
    parent = json.loads(parent_raw)
    require(parent["source_commit"] == SOURCE52_COMMIT and parent["source_tree"] == SOURCE52_TREE
            and parent["source_parent_commit"] == SOURCE51_COMMIT, "source52 parent identity mismatch")
    require(parent["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and parent["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "source52 parent dual-lock mismatch")
    parent_files = normalized_files(parent["changed_files"])
    require(len(parent_files) == SOURCE52_CHANGED_COUNT == 195
            and set(parent_files) == set(prior_files) | set(ALLOWED_SOURCE52_DELTA),
            "source52 must retain source51 and add exactly the runtime leaf")
    require(all(parent_files[path] == row for path, row in prior_files.items()),
            "original source51 changed row differs in source52")
    require(not (set(ALLOWED_SOURCE53_DELTA) & set(parent_files)),
            "Bedrock leaves were already in source52 changed manifest")

    raw = (E / safe_relative(SOURCE_MANIFEST_NAME)).read_bytes()
    require(sha(raw) == SOURCE_MANIFEST_SHA256, "actual source53 manifest hash mismatch")
    source = json.loads(raw)
    require(source["source_tree"] == EXPECTED_TREE and source["source_commit"] == EXPECTED_COMMIT
            and source["source_parent_commit"] == SOURCE52_COMMIT, "root-frozen source53 identity mismatch")
    require(source["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and source["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "source53 dual-lock mismatch")
    require(source["diagnostic_only"] is True and source["behavior_repair_claimed"] is False,
            "diagnostic source cannot be relabeled as a behavior repair")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT == 197, "actual source53 file count mismatch")
    require(set(files) == set(parent_files) | set(ALLOWED_SOURCE53_DELTA),
            "source53 must add exactly two existing Bedrock leaves to changed paths")
    require(all(files[path] == row for path, row in parent_files.items()),
            "an original source52 changed entry differs")
    return (files, {"path": SOURCE_MANIFEST_NAME, **data_pin(raw)},
            old_files, {"path": SOURCE50_MANIFEST_NAME, **data_pin(old_raw)},
            prior_files, {"path": SOURCE51_MANIFEST_NAME, **data_pin(prior_raw)},
            parent_files, {"path": SOURCE52_MANIFEST_NAME, **data_pin(parent_raw)})

def read_fixed(name, byte_count, digest):
    raw = (E / safe_relative(name)).read_bytes()
    require(len(raw) == byte_count and sha(raw) == digest, "fixed original mismatch: " + name)
    return raw, {"path": name, **data_pin(raw)}

def read_pinned(pin):
    require(isinstance(pin, dict) and set(pin) == {"path", "bytes", "sha256", "git_blob"}, "incomplete evidence pin")
    require(type(pin["bytes"]) is int and pin["bytes"] >= 0, "invalid evidence length")
    require(hex_digest(pin["sha256"], 64) and hex_digest(pin["git_blob"], 40), "invalid evidence digest")
    raw, actual = read_fixed(pin["path"], pin["bytes"], pin["sha256"])
    require(actual == pin, "evidence Git blob mismatch")
    return raw

def closed_terminal(raw, job_id, state, exit_code):
    terminal = json.loads(raw)
    require(terminal["job_id"] == job_id and terminal["state"] == state and terminal["exit_code"] == exit_code, "wrong natural outer terminal")
    for key in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[key] is False, "outer state invalid: " + key)
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "outer evidence incomplete: " + key)
    require(all(value is False for value in terminal["log_truncated"].values()), "outer log truncated")
    require(all(value is None for value in terminal["log_errors"].values()), "outer log error")
    return terminal

def r24_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R24_FAILURE_PINS.items():
        raw, pin = read_fixed(name, expected["bytes"], expected["sha256"])
        originals[name] = raw
        pins.append(pin)
    terminal = closed_terminal(
        originals["native-source50-project-r24-terminal-process-status.json"], R24_JOB_ID, "failed", 100,
    )
    raw_result = json.loads(originals["native-source50-project-r24-tests-raw-process-result.json"])
    receipt = json.loads(originals["native-source50-project-r24-tests-receipt.json"])
    post = json.loads(originals["native-source50-project-r24-tests-source-post-verification.json"])
    args = [value for package in HISTORICAL_FOUR_PACKAGES for value in ("-p", package)]
    for value in (raw_result, receipt):
        require(value["phase"] == "tests" and value["exit_code"] == 100, "original r24 test failure changed")
        require(value["source_tree"] == LOCK_SOURCE50_TREE and value["source_commit"] == LOCK_SOURCE50_COMMIT, "r24 failure source mismatch")
        require(value["command"] == ["just", "test", "--locked", *args, "--retries", "0"], "r24 original command mismatch")
        require(value["cwd"] == str(S / "codex-rs"), "r24 cwd mismatch")
    for key in ("command", "cwd", "source_tree", "source_commit", "phase", "exit_code", "start_unix", "end_unix"):
        require(raw_result[key] == receipt[key], "r24 raw/receipt mismatch: " + key)
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False, "r24 failure qualification changed")
    require(receipt["raw_process_result"] == {"path": "native-source50-project-r24-tests-raw-process-result.json", **data_pin(originals["native-source50-project-r24-tests-raw-process-result.json"])}, "r24 raw receipt binding mismatch")
    require(receipt["source_postguard"] == {"path": "native-source50-project-r24-tests-source-post-verification.json", **data_pin(originals["native-source50-project-r24-tests-source-post-verification.json"])}, "r24 postguard binding mismatch")
    require(receipt["source_guards_pass"] is True and post["pass"] is True, "r24 source guard failed")
    require(post["actual_tree"] == post["expected_tree"] == LOCK_SOURCE50_TREE and post["source_commit"] == LOCK_SOURCE50_COMMIT, "r24 postguard source mismatch")
    require(post["changed_file_count"] == LOCK_SOURCE50_CHANGED_COUNT and post["gate_exit_code"] == 100, "r24 postguard count/exit mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r24 dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r24 outer terminal precedes test end")
    return pins

def r26_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R26_FAILURE_PINS.items():
        raw, pin = read_fixed(name, expected["bytes"], expected["sha256"])
        originals[name] = raw
        pins.append(pin)
    terminal = closed_terminal(
        originals["native-source51-project-r26-terminal-process-status.json"], R26_JOB_ID, "failed", 100,
    )
    raw_result = json.loads(originals["native-source51-project-r26-tests-raw-process-result.json"])
    receipt = json.loads(originals["native-source51-project-r26-tests-receipt.json"])
    post = json.loads(originals["native-source51-project-r26-tests-source-post-verification.json"])
    args = [value for package in HISTORICAL_FOUR_PACKAGES for value in ("-p", package)]
    for value in (raw_result, receipt):
        require(value["phase"] == "tests" and value["exit_code"] == 100, "original r26 test failure changed")
        require(value["source_tree"] == SOURCE51_TREE and value["source_commit"] == SOURCE51_COMMIT, "r26 failure source mismatch")
        require(value["command"] == ["just", "test", "--locked", *args, "--retries", "0"], "r26 original command mismatch")
        require(value["cwd"] == str(S / "codex-rs"), "r26 cwd mismatch")
    for key in ("command", "cwd", "source_tree", "source_commit", "phase", "exit_code", "start_unix", "end_unix"):
        require(raw_result[key] == receipt[key], "r26 raw/receipt mismatch: " + key)
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False, "r26 failure qualification changed")
    require(receipt["raw_process_result"] == {"path": "native-source51-project-r26-tests-raw-process-result.json", **data_pin(originals["native-source51-project-r26-tests-raw-process-result.json"])}, "r26 raw receipt binding mismatch")
    require(receipt["source_postguard"] == {"path": "native-source51-project-r26-tests-source-post-verification.json", **data_pin(originals["native-source51-project-r26-tests-source-post-verification.json"])}, "r26 postguard binding mismatch")
    require(receipt["source_guards_pass"] is True and post["pass"] is True, "r26 source guard failed")
    require(post["actual_tree"] == post["expected_tree"] == SOURCE51_TREE and post["source_commit"] == SOURCE51_COMMIT, "r26 postguard source mismatch")
    require(post["changed_file_count"] == SOURCE51_CHANGED_COUNT and post["gate_exit_code"] == 100, "r26 postguard count/exit mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r26 dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r26 outer terminal precedes test end")
    return pins

def tree_file_pin(tree, path):
    safe_relative(path)
    record = git("ls-tree", "-z", tree, "--", path).rstrip(b"\0")
    header, actual_path = record.split(b"\t", 1)
    mode, kind, object_id = header.decode().split()
    require(actual_path.decode() == path and kind == "blob" and mode in ("100644", "100755"),
            "missing/nonregular immutable tree leaf: " + path)
    raw = git("cat-file", "blob", object_id)
    require(data_pin(raw)["git_blob"] == object_id, "immutable blob byte identity mismatch")
    return {"path": path, **data_pin(raw), "mode": mode}

def r29_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R29_FAILURE_PINS.items():
        raw, pin = read_fixed(name, expected["bytes"], expected["sha256"])
        originals[name] = raw
        pins.append(pin)
    prefix = "native-workspace-r29"
    terminal = closed_terminal(originals[prefix + "-terminal-process-status.json"], R29_JOB_ID, "failed", 100)
    raw_result = json.loads(originals[prefix + "-tests-raw-process-result.json"])
    receipt = json.loads(originals[prefix + "-tests-receipt.json"])
    post = json.loads(originals[prefix + "-source-post-test-verification.json"])
    require(receipt["schema"] == "hepta.native-workspace-gate-receipt.v2", "r29 receipt schema mismatch")
    for value in (raw_result, receipt):
        require(value["phase"] == "workspace-tests" and value["exit_code"] == 100, "original r29 failure changed")
        require(value["source_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
                "r29 failure source mismatch")
        require(value["command"] == ["just", "test", "--locked", "--retries", "0"],
                "r29 original no-p command mismatch")
        require(value["cwd"] == str(S / "codex-rs"), "r29 cwd mismatch")
    for key in ("command", "cwd", "source_tree", "source_commit", "phase", "exit_code", "start_unix", "end_unix"):
        require(raw_result[key] == receipt[key], "r29 raw/receipt mismatch: " + key)
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False,
            "r29 failure qualification changed")
    require(receipt["raw_process_result"] == {
                "path": prefix + "-tests-raw-process-result.json",
                **data_pin(originals[prefix + "-tests-raw-process-result.json"])},
            "r29 raw receipt binding mismatch")
    require(receipt["source_postguard"] == {
                "path": prefix + "-source-post-test-verification.json",
                **data_pin(originals[prefix + "-source-post-test-verification.json"])},
            "r29 postguard binding mismatch")
    require(receipt["source_guards_pass"] is True and post["pass"] is True, "r29 source guard failed")
    require(post["actual_tree"] == post["expected_tree"] == SOURCE52_TREE
            and post["source_commit"] == SOURCE52_COMMIT and post["native_head"] == FRAMEWORK_PARENT,
            "r29 postguard source/HEAD mismatch")
    require(post["changed_file_count"] == SOURCE52_CHANGED_COUNT and post["gate_exit_code"] == 100,
            "r29 postguard count/exit mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r29 dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r29 terminal precedes test end")
    return pins

def inherited_dependency_check(old_files, prior_files, parent_files, files, delta):
    require(delta["schema"] == "hepta.source53-apply-delta.v1", "unexpected source53 delta schema")
    require(delta["source_before_tree"] == SOURCE52_TREE and delta["source_before_commit"] == SOURCE52_COMMIT,
            "delta source52 parent mismatch")
    require(delta["source_tree"] == EXPECTED_TREE and delta["source_commit"] == EXPECTED_COMMIT,
            "delta source53 identity mismatch")
    require(delta["diagnostic_only"] is True and delta["behavior_repair_claimed"] is False,
            "diagnostic delta classification changed")
    parent_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only",
                             "-z", SOURCE52_TREE, EXPECTED_TREE)
    require(len(parent_paths) == 2 and set(parent_paths) == set(ALLOWED_SOURCE53_DELTA),
            "source53 Git delta is not the two reviewed existing Bedrock leaves")
    source51_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only",
                               "-z", SOURCE51_TREE, SOURCE52_TREE)
    require(len(source51_paths) == 1 and set(source51_paths) == set(ALLOWED_SOURCE52_DELTA),
            "historical source51-to-source52 delta changed")
    actual_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only",
                             "-z", LOCK_SOURCE50_TREE, EXPECTED_TREE)
    require(len(actual_paths) == 5 and set(actual_paths) == set(LOCK_INHERITANCE_RUST_PATHS),
            "source50-to-source53 Git delta contains an unreviewed path")
    delta_rows = delta["files"]
    require(isinstance(delta_rows, list) and len(delta_rows) == 2, "wrong two-leaf delta row count")
    rows = {row["path"]: row for row in delta_rows}
    require(set(rows) == set(ALLOWED_SOURCE53_DELTA), "wrong diagnostic delta leaves")
    before_images = {}
    for path in ALLOWED_SOURCE53_DELTA:
        before_leaf = {"path": path, **rows[path]["before"]}
        after_leaf = {"path": path, **rows[path]["after"]}
        require(path not in parent_files and path not in prior_files and path not in old_files,
                "Bedrock leaf must be newly changed relative to the framework")
        require(after_leaf == files[path], "Bedrock after image differs from complete current manifest")
        require(before_leaf["mode"] == after_leaf["mode"] == "100644"
                and before_leaf["git_blob"] != after_leaf["git_blob"], "Bedrock mode or delta invalid")
        for tree in (LOCK_SOURCE50_TREE, SOURCE51_TREE, SOURCE52_TREE):
            require(tree_file_pin(tree, path) == before_leaf, "existing Bedrock before tree/raw identity mismatch")
        before_images[path] = before_leaf
    runtime_path = ALLOWED_SOURCE52_DELTA[0]
    before_images[runtime_path] = tree_file_pin(LOCK_SOURCE50_TREE, runtime_path)
    require(tree_file_pin(SOURCE51_TREE, runtime_path) == before_images[runtime_path],
            "runtime pre-source52 original tree entry differs")
    require(tree_file_pin(SOURCE52_TREE, runtime_path) == parent_files[runtime_path] == files[runtime_path],
            "source52 runtime change was not retained exactly")
    for path in LOCK_INHERITANCE_RUST_PATHS:
        require(PurePosixPath(path).suffix == ".rs" and PurePosixPath(path).name != "build.rs",
                "dependency/build input cannot inherit a lock result")
        before = old_files[path] if path in old_files else before_images[path]
        after = files[path]
        require(before["mode"] == after["mode"] and before["git_blob"] != after["git_blob"],
                "unexpected mode change or unchanged inherited delta")
        require(tree_file_pin(LOCK_SOURCE50_TREE, path) == before
                and tree_file_pin(EXPECTED_TREE, path) == after, "inheritance Git tree/raw identity mismatch")
    require(all(files[path] == row for path, row in parent_files.items()),
            "one of the195 source52 changed rows differs")
    for path in set(old_files) - set(ALLOWED_SOURCE51_DELTA):
        require(files[path] == old_files[path], "unreviewed source50 manifest path changed: " + path)
    for path, digest in zip(LOCK_FILES, (CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256)):
        raw_locks = [git("show", tree + ":" + path)
                     for tree in (LOCK_SOURCE50_TREE, SOURCE51_TREE, SOURCE52_TREE, EXPECTED_TREE)]
        require(all(raw == raw_locks[0] for raw in raw_locks) and sha(raw_locks[0]) == digest,
                "source50/source51/source52/source53 Git lock bytes differ")
    require(delta["patch"]["path"] == "candidate.patch", "unexpected delta patch member")
    resolved_patch_pin = {**delta["patch"],
                          "path": str(safe_relative(DELTA_MANIFEST_NAME).parent / "candidate.patch")}
    require(bool(read_pinned(resolved_patch_pin)), "reviewed two-leaf diagnostic patch is empty")
    return {
        "schema": "hepta.source53-source50-lock-inheritance.v1",
        "lock_executed_for_source_commit": LOCK_SOURCE50_COMMIT,
        "lock_executed_for_source_tree": LOCK_SOURCE50_TREE,
        "parent_source_commit": SOURCE52_COMMIT, "parent_source_tree": SOURCE52_TREE,
        "current_source_commit": EXPECTED_COMMIT, "current_source_tree": EXPECTED_TREE,
        "actual_git_tree_changed_paths_from_source50": actual_paths,
        "actual_git_tree_changed_paths_from_source52": parent_paths,
        "historical_git_tree_changed_paths_from_source51_to_source52": source51_paths,
        "all_other_git_tree_entries_unchanged": True,
        "prior_195_changed_entries_unchanged": True,
        "existing_bedrock_leaves_newly_in_changed_manifest": True,
        "dependency_inputs_changed_paths": [], "git_modes_unchanged": True,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "source53_bazel_lock_update_executed": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "inheritance_basis": "Exact five existing non-build Rust paths since source50; two leaves since source52; all other Git entries and both raw locks unchanged.",
        "reviewed_delta_patch": delta["patch"], "resolved_patch_evidence": resolved_patch_pin,
    }

def apply_prerequisite(files, source_pin, old_files, prior_files, parent_files):
    complete_raw, complete_pin = read_fixed(APPLY_COMPLETE_NAME, APPLY_COMPLETE_BYTES, APPLY_COMPLETE_SHA256)
    terminal_raw, terminal_pin = read_fixed(APPLY_TERMINAL_NAME, APPLY_TERMINAL_BYTES, APPLY_TERMINAL_SHA256)
    delta_raw, delta_pin = read_fixed(DELTA_MANIFEST_NAME, DELTA_MANIFEST_BYTES, DELTA_MANIFEST_SHA256)
    complete = json.loads(complete_raw)
    require(complete["schema"] == "hepta.source53-apply-complete.v1", "source53 apply complete schema mismatch")
    require(complete["source_before_tree"] == SOURCE52_TREE and complete["source_before_commit"] == SOURCE52_COMMIT,
            "apply source52 parent mismatch")
    require(complete["source_tree"] == EXPECTED_TREE and complete["source_commit"] == EXPECTED_COMMIT,
            "apply new identity mismatch")
    require(complete["source_manifest"] == source_pin and complete["delta_manifest"] == delta_pin,
            "apply manifests not bound to current originals")
    require(complete["source_guards_pass"] is True and complete["actual_changed_file_count"] == len(files) == 197,
            "apply source/count guard failed")
    require(complete["prior_changed_file_count"] == len(parent_files) == 195, "apply prior count mismatch")
    require(complete["before_existing_repo_leaves_not_in_prior_changed_manifest"] is True,
            "apply did not verify both pre-existing unchanged Bedrock leaves")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "apply dual-lock mismatch")
    require(complete["changed_from_source52_paths"] == list(ALLOWED_SOURCE53_DELTA), "apply changed leaves mismatch")
    require(complete["dependency_inputs_changed_paths"] == [], "apply changed dependency inputs")
    require(complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False,
            "apply diagnostic classification changed")
    for key in ("bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"):
        require(complete[key] is False, "apply-only phase scope changed: " + key)
    post_raw = read_pinned(complete["source_postguard"])
    post = json.loads(post_raw)
    require(post["schema"] == "hepta.source53-apply-postguard.v1" and post["pass"] is True, "apply postguard failed")
    require(post["actual_tree"] == EXPECTED_TREE and post["source_commit"] == EXPECTED_COMMIT,
            "apply postguard identity mismatch")
    require(post["actual_changed_file_count"] == len(files) and post["changed_path_set_matches"] is True,
            "apply postguard count/path mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "apply postguard lock mismatch")
    for key in ("unstaged_paths", "untracked_paths", "file_mismatches"):
        require(post[key] == [], "apply postguard contains a mismatch: " + key)
    terminal = closed_terminal(terminal_raw, APPLY_JOB_ID, "succeeded", 0)
    if "ended_unix" in complete:
        require(terminal["at_unix_ms"] / 1000 >= complete["ended_unix"], "apply terminal precedes completion")
    inheritance = inherited_dependency_check(old_files, prior_files, parent_files, files, json.loads(delta_raw))
    return {"complete": complete_pin, "terminal": terminal_pin,
            "source_postguard": complete["source_postguard"], "delta_manifest": delta_pin,
            "source50_lock_inheritance": inheritance}

def load_baseline():
    raw = (E / safe_relative(BASELINE_NAME)).read_bytes()
    require(len(raw) == BASELINE_BYTES and sha(raw) == BASELINE_SHA256, "1345-ID original r29 baseline pin mismatch")
    baseline = json.loads(raw)
    require(baseline["schema"] == "hepta.closed-app-server-r29-executed-baseline.v1", "baseline schema mismatch")
    require(baseline["source_commit"] == SOURCE52_COMMIT and baseline["source_tree"] == SOURCE52_TREE,
            "baseline is not the original source52 r29 execution")
    require(baseline["package"] == "codex-app-server" and baseline["identity_key"] == ["binary", "name"],
            "baseline owner/key mismatch")
    ids = {(row["binary"], row["name"]) for row in baseline["test_ids"]}
    require(len(ids) == len(baseline["test_ids"]) == baseline["count"] == BASELINE_COUNT == 1345,
            "baseline duplicate/count mismatch")
    require(all(row["binary"].split("::", 1)[0] == "codex-app-server" for row in baseline["test_ids"]),
            "baseline contains another owner")
    return ids, {"path": BASELINE_NAME, **data_pin(raw)}

def execution_environment():
    env = os.environ.copy()
    env.update({
        "PATH": str(T / "bin") + ":/home/alex/.cargo/bin:" + env.get("PATH", ""),
        "RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "2",
        "CARGO_TARGET_DIR": str(T / "target"), "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "NEXTEST_TEST_THREADS": "2", "PYTHONDONTWRITEBYTECODE": "1",
        "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
    })
    for key in ("CARGO_INCREMENTAL", "CARGO_BUILD_TARGET", "RUSTFLAGS"):
        env.pop(key, None)
    prerequisite_raw = (E / "agentd-prerequisite-env.json").read_bytes()
    for key, value in json.loads(prerequisite_raw).items():
        if key in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH", "PROTOC", "PROTOC_INCLUDE", "DOTSLASH_CACHE"):
            env[key] = value
    keys = (
        "RUSTUP_TOOLCHAIN", "CARGO_BUILD_JOBS", "CARGO_TARGET_DIR", "CARGO_NET_GIT_FETCH_WITH_CLI",
        "NEXTEST_TEST_THREADS", "NEXTEST_PROFILE", "HEPTA_NEXTTEST_FULL_METADATA",
        "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG", "CARGO_INCREMENTAL",
        "CARGO_BUILD_TARGET", "RUSTFLAGS", "DOTSLASH_CACHE", "PYTHONOPTIMIZE",
    )
    return env, {key: env.get(key) for key in keys}, data_pin(prerequisite_raw)

def clean_lines(raw):
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        yield number, offset, ANSI.sub(b"", line).decode("utf-8", "replace").rstrip("\r\n")
        offset += len(line)

def review_tests(raw, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [(n, o, text, m) for n, o, text, m in starts if m]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [(n, o, text, m) for n, o, text, m in summaries if m]
    require(len(starts) == len(summaries) == 1, "complete nextest Starting/Summary required")
    start, summary = starts[0], summaries[0]
    require(start[0] < summary[0], "invalid nextest event order")
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows = []
    footer_rows = []
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start[0] < number < summary[0]:
            rows.append(row)
        elif number > summary[0]:
            footer_rows.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    tail = summary[3][3]
    def summary_count(label):
        match = re.search(r"\b([0-9]+) " + label + r"\b", tail)
        return int(match[1]) if match else 0
    expected_counts = {"PASS": summary_count("passed"), "FAIL": summary_count("failed"), "TIMEOUT": summary_count("timed out")}
    reported_skipped = summary_count("skipped")
    missing = sorted(baseline - set(current))
    additional = sorted(set(current) - baseline)
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(PACKAGES))
    passed = (
        len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and bool(rows) and counts == expected_counts
        and counts["FAIL"] == counts["TIMEOUT"] == 0
        and not missing and not additional and not unsuccessful and not unexpected_packages
    )
    review = {
        "schema": "hepta.source53-app-server-closed-readback.v1",
        "log": data_pin(raw), "starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
        "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2], "seconds": float(summary[3][1])},
        "unique_test_count": len(current), "execution_rows": len(rows), "counts": counts,
        "summary_counts": expected_counts, "reported_skipped": reported_skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer_rows, "baseline_count": len(baseline),
        "baseline_is_source52_r29_actual_app_server_population": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in additional],
        "unexpected_packages": unexpected_packages,
        "per_package": {package: {status: sum(row["binary"].split("::", 1)[0] == package and row["status"] == status for row in rows)
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review

def pinned_read(name, expected):
    path = E / safe_relative(name)
    require(path.is_file() and not path.is_symlink(), "input is not a regular file: " + name)
    raw = path.read_bytes()
    require(len(raw) == expected["bytes"] and sha(raw) == expected["sha256"], "input pin mismatch: " + name)
    return raw

def verify_recorded_guard(value, label):
    require(value["pass"] is True and value["actual_tree"] == EXPECTED_TREE
            and value["expected_tree"] == EXPECTED_TREE and value["source_commit"] == EXPECTED_COMMIT,
            "recorded source guard identity failed: " + label)
    require(value["native_head"] == FRAMEWORK_PARENT, "recorded native HEAD mismatch: " + label)
    require(value["changed_file_count"] == EXPECTED_CHANGED_COUNT
            and value["changed_path_set_matches"] is True, "recorded source scope mismatch: " + label)
    require(not value["unstaged_paths"] and not value["untracked_paths"] and not value["file_mismatches"],
            "recorded source guard is not clean: " + label)
    require(value["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and value["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "recorded dual-lock mismatch: " + label)

def verify_pointer(pointer, name, originals):
    require(pointer == {"path": name, **data_pin(originals[name])}, "original evidence pointer mismatch: " + name)

def review_python(raw):
    lines = list(clean_lines(raw))
    summaries = [(n, o, text, re.fullmatch(r"\s*Ran ([0-9]+) tests? in ([0-9.]+)s\s*", text)) for n, o, text in lines]
    summaries = [(n, o, text, match) for n, o, text, match in summaries if match]
    ok = [(n, o, text) for n, o, text in lines if text.strip() == "OK"]
    skipped = [(n, o, text) for n, o, text in lines if re.search(r"\.\.\. skipped\b|^OK \(.*skipped=", text)]
    passed = len(summaries) == 1 and int(summaries[0][3][1]) == PYTHON_TEST_COUNT and len(ok) == 1 and not skipped
    return {
        "schema": "hepta.source51-python-runner-readback.v1",
        "log": data_pin(raw), "expected_test_count": PYTHON_TEST_COUNT,
        "reported_test_count": int(summaries[0][3][1]) if len(summaries) == 1 else None,
        "summary_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text, _ in summaries],
        "ok_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in ok],
        "skip_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in skipped],
        "reported_skipped": 0 if passed else None, "pass": passed,
    }

def verify_inherited_guard(value, label):
    require(value["pass"] is True and value["actual_tree"] == SOURCE52_TREE
            and value["expected_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
            "recorded source guard identity failed: " + label)
    require(value["native_head"] == FRAMEWORK_PARENT, "recorded native HEAD mismatch: " + label)
    require(value["changed_file_count"] == SOURCE52_CHANGED_COUNT
            and value["changed_path_set_matches"] is True, "recorded source scope mismatch: " + label)
    require(not value["unstaged_paths"] and not value["untracked_paths"] and not value["file_mismatches"],
            "recorded source guard is not clean: " + label)
    require(value["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and value["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "recorded dual-lock mismatch: " + label)

def review_inherited_tests(raw, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [(n, o, text, m) for n, o, text, m in starts if m]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [(n, o, text, m) for n, o, text, m in summaries if m]
    require(len(starts) == len(summaries) == 1, "complete nextest Starting/Summary required")
    start, summary = starts[0], summaries[0]
    require(start[0] < summary[0], "invalid nextest event order")
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows = []
    footer_rows = []
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start[0] < number < summary[0]:
            rows.append(row)
        elif number > summary[0]:
            footer_rows.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    tail = summary[3][3]
    def summary_count(label):
        match = re.search(r"\b([0-9]+) " + label + r"\b", tail)
        return int(match[1]) if match else 0
    expected_counts = {"PASS": summary_count("passed"), "FAIL": summary_count("failed"), "TIMEOUT": summary_count("timed out")}
    reported_skipped = summary_count("skipped")
    missing = sorted(baseline - set(current))
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(HISTORICAL_FOUR_PACKAGES))
    passed = (
        len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and bool(rows) and counts == expected_counts
        and counts["FAIL"] == counts["TIMEOUT"] == 0
        and not missing and not unsuccessful and not unexpected_packages
    )
    review = {
        "schema": "hepta.source52-four-package-closed-readback.v1",
        "log": data_pin(raw), "starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
        "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2], "seconds": float(summary[3][1])},
        "unique_test_count": len(current), "execution_rows": len(rows), "counts": counts,
        "summary_counts": expected_counts, "reported_skipped": reported_skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer_rows, "baseline_count": len(baseline),
        "baseline_is_source49_previous_failure_population_not_previous_pass": True,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in sorted(set(current) - baseline)],
        "unexpected_packages": unexpected_packages,
        "per_package": {package: {status: sum(row["binary"].split("::", 1)[0] == package and row["status"] == status for row in rows)
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in HISTORICAL_FOUR_PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review

def load_inherited_baseline():
    raw = (E / safe_relative(HISTORICAL_BASELINE_NAME)).read_bytes()
    require(len(raw) == HISTORICAL_BASELINE_BYTES and sha(raw) == HISTORICAL_BASELINE_SHA256, "1564-ID baseline pin mismatch")
    baseline = json.loads(raw)
    require(baseline["schema"] == "hepta.closed-four-package-executed-baseline.v1", "baseline schema mismatch")
    require(baseline["source_commit"] == PREVIOUS_SOURCE49_COMMIT and baseline["source_tree"] == PREVIOUS_SOURCE49_TREE, "baseline is not original source49")
    require(set(baseline["packages"]) == set(HISTORICAL_FOUR_PACKAGES) and baseline["identity_key"] == ["binary", "name"], "baseline owner/key mismatch")
    ids = {(row["binary"], row["name"]) for row in baseline["test_ids"]}
    require(len(ids) == len(baseline["test_ids"]) == baseline["count"] == HISTORICAL_BASELINE_COUNT, "baseline duplicate/count mismatch")
    require(all(row["package"] in HISTORICAL_FOUR_PACKAGES and row["binary"].split("::", 1)[0] == row["package"] for row in baseline["test_ids"]), "baseline package mismatch")
    return ids, {"path": HISTORICAL_BASELINE_NAME, **data_pin(raw)}

def r28_required_names():
    names = [
        R28_PREFIX + "-environment.json",
        R28_PREFIX + "-preconditions.json",
        R28_PREFIX + "-source-pre-verification.json",
        R28_PREFIX + "-source-final-verification.json",
        R28_PREFIX + "-complete.json",
    ]
    for phase in R28_PHASES:
        stem = R28_PREFIX + "-" + phase
        names.extend(stem + suffix for suffix in (
            ".log", "-resources.txt", "-raw-process-result.json",
            "-receipt.json", "-source-pre-verification.json", "-source-post-verification.json",
        ))
    names.extend((
        R28_PREFIX + "-python-runner-result-review.json",
        R28_PREFIX + "-tests-result-review.json",
        R28_PREFIX + "-tests-test-results.json",
    ))
    return names

def historical_source52_apply_prerequisite(source_pin):
    # Historical apply originals remain fixed to source52. The current source53
    # apply is checked independently by the unmodified r30 producer functions.
    complete_raw, complete_pin = read_fixed(HISTORICAL_APPLY_COMPLETE_NAME, HISTORICAL_APPLY_COMPLETE_BYTES,
                                            HISTORICAL_APPLY_COMPLETE_SHA256)
    terminal_raw, terminal_pin = read_fixed(HISTORICAL_APPLY_TERMINAL_NAME, HISTORICAL_APPLY_TERMINAL_BYTES,
                                            HISTORICAL_APPLY_TERMINAL_SHA256)
    delta_raw, delta_pin = read_fixed(HISTORICAL_DELTA_MANIFEST_NAME, HISTORICAL_DELTA_MANIFEST_BYTES,
                                     HISTORICAL_DELTA_MANIFEST_SHA256)
    complete, delta = json.loads(complete_raw), json.loads(delta_raw)
    require(complete["schema"] == "hepta.source52-apply-complete.v1"
            and delta["schema"] == "hepta.source52-apply-delta.v1", "historical source52 apply schema changed")
    for value in (complete, delta):
        require(value["source_before_tree"] == SOURCE51_TREE and value["source_before_commit"] == SOURCE51_COMMIT
                and value["source_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
                "historical source52 apply identity changed")
    require(complete["source_manifest"] == source_pin and complete["delta_manifest"] == delta_pin,
            "historical source52 apply inputs changed")
    require(complete["source_guards_pass"] is True and complete["actual_changed_file_count"] == 195
            and complete["prior_changed_file_count"] == 194
            and complete["before_existing_repo_leaf_not_in_prior_changed_manifest"] is True,
            "historical source52 apply guard changed")
    require(complete["changed_from_source51_paths"] == list(ALLOWED_SOURCE52_DELTA)
            and complete["dependency_inputs_changed_paths"] == [], "historical source52 apply scope changed")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "historical source52 apply dual locks changed")
    for key in ("bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"):
        require(complete[key] is False, "historical apply-only phase changed")
    post = json.loads(read_pinned(complete["source_postguard"]))
    require(post["schema"] == "hepta.source52-apply-postguard.v1" and post["pass"] is True
            and post["actual_tree"] == SOURCE52_TREE and post["source_commit"] == SOURCE52_COMMIT
            and post["actual_changed_file_count"] == 195 and post["changed_path_set_matches"] is True,
            "historical source52 postguard identity/scope changed")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
            and not post["unstaged_paths"] and not post["untracked_paths"] and not post["file_mismatches"],
            "historical source52 postguard bytes changed")
    terminal = closed_terminal(terminal_raw, HISTORICAL_APPLY_JOB_ID, "succeeded", 0)
    if "ended_unix" in complete:
        require(terminal["at_unix_ms"] / 1000 >= complete["ended_unix"], "historical apply terminal order changed")
    raw = pinned_read(R28_PREFIX + "-preconditions.json", R28_INPUT_PINS[R28_PREFIX + "-preconditions.json"])
    proof = json.loads(raw)["source52_apply"]
    require(proof["complete"] == complete_pin and proof["terminal"] == terminal_pin
            and proof["delta_manifest"] == delta_pin and proof["source_postguard"] == complete["source_postguard"],
            "fixed r28 historical apply pointers differ")
    inheritance = proof["source50_lock_inheritance"]
    require(inheritance["schema"] == "hepta.source52-source50-lock-inheritance.v1"
            and inheritance["lock_executed_for_source_commit"] == LOCK_SOURCE50_COMMIT
            and inheritance["lock_executed_for_source_tree"] == LOCK_SOURCE50_TREE
            and inheritance["parent_source_commit"] == SOURCE51_COMMIT
            and inheritance["parent_source_tree"] == SOURCE51_TREE
            and inheritance["current_source_commit"] == SOURCE52_COMMIT
            and inheritance["current_source_tree"] == SOURCE52_TREE,
            "historical r28 lock-inheritance source identity differs")
    require(set(inheritance["actual_git_tree_changed_paths_from_source50"])
            == set(ALLOWED_SOURCE51_DELTA + ALLOWED_SOURCE52_DELTA)
            and inheritance["actual_git_tree_changed_paths_from_source51"] == list(ALLOWED_SOURCE52_DELTA)
            and inheritance["dependency_inputs_changed_paths"] == []
            and inheritance["source52_bazel_lock_update_executed"] is False,
            "historical r28 lock-inheritance scope differs")
    require(inheritance["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and inheritance["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "historical r28 lock-inheritance raw locks differ")
    require(inheritance["reviewed_delta_patch"] == delta["patch"], "historical source52 patch pin differs")
    require(bool(read_pinned(inheritance["resolved_patch_evidence"])), "historical source52 patch missing")
    return proof

def r28_inherited_prerequisite(baseline, source_pin, baseline_pin, lock_pins, source50_pin, source51_pin,
                     apply_proof, r24_failed_pins, r26_failed_pins):
    originals = {name: pinned_read(name, R28_INPUT_PINS[name]) for name in r28_required_names()}
    records = {name: json.loads(raw) for name, raw in originals.items() if name.endswith(".json")}
    args = [value for package in HISTORICAL_FOUR_PACKAGES for value in ("-p", package)]
    commands = {
        "python-runner": ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_run_nextest*.py", "-v"],
        "strict": ["just", "clippy", "--locked", *args, "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", *args, "--retries", "0"],
    }
    receipts, previous_end = [], None
    for phase in R28_PHASES:
        stem = R28_PREFIX + "-" + phase
        raw_name, receipt_name = stem + "-raw-process-result.json", stem + "-receipt.json"
        pre_name, post_name = stem + "-source-pre-verification.json", stem + "-source-post-verification.json"
        raw, receipt = records[raw_name], records[receipt_name]
        require(raw["schema"] == "hepta.native-raw-process-result.v1", "r28 raw result schema mismatch")
        require(receipt["schema"] == "hepta.native-gate-receipt.v2", "r28 receipt schema mismatch")
        cwd = str(S if phase == "python-runner" else S / "codex-rs")
        for value in (raw, receipt):
            require(value["phase"] == phase and value["command"] == commands[phase] and value["cwd"] == cwd,
                    "wrong original r28 command: " + phase)
            require(value["source_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
                    "r28 original identity mismatch: " + phase)
            require(value["exit_code"] == 0, "r28 original command did not pass: " + phase)
        for key in ("source_tree", "source_commit", "phase", "command", "cwd", "start_unix", "end_unix", "exit_code"):
            require(raw[key] == receipt[key], "r28 raw/receipt mismatch: " + phase + "/" + key)
        require(receipt["end_unix"] >= receipt["start_unix"]
                and abs(receipt["elapsed_seconds"] - (receipt["end_unix"] - receipt["start_unix"])) < 1e-6,
                "invalid r28 phase timing: " + phase)
        require(previous_end is None or receipt["start_unix"] >= previous_end, "r28 phase ordering mismatch")
        previous_end = receipt["end_unix"]
        require(receipt["effective_exit_code"] == 0 and receipt["phase_pass"] is True
                and receipt["issues"] == [] and receipt["source_guards_pass"] is True,
                "r28 phase acceptance or guard failed: " + phase)
        require(receipt["source_manifest"] == SOURCE52_MANIFEST_NAME
                and receipt["source_manifest_sha256"] == SOURCE52_MANIFEST_SHA256, "r28 source manifest mismatch")
        require(receipt["environment_manifest"] == R28_PREFIX + "-environment.json", "r28 environment pointer mismatch")
        require(receipt["packages"] == ([] if phase == "python-runner" else HISTORICAL_FOUR_PACKAGES), "r28 package scope mismatch")
        require(receipt["retries"] == (0 if phase == "tests" else None)
                and receipt["filters"] == "no_additions" and receipt["features"] == "unchanged_defaults",
                "r28 selection changed")
        require(receipt["fix_fmt_executed"] is False and receipt["baseline_used_as_filter"] is False,
                "r28 phase semantics changed")
        verify_pointer(receipt["raw_process_result"], raw_name, originals)
        verify_pointer(receipt["source_postguard"], post_name, originals)
        verify_inherited_guard(records[pre_name], pre_name)
        verify_inherited_guard(records[post_name], post_name)
        require(records[post_name]["gate_exit_code"] == 0 and records[post_name]["phase"] == phase,
                "r28 postguard is not this successful phase")
        log_raw, resource_raw = originals[stem + ".log"], originals[stem + "-resources.txt"]
        require(receipt["log_sha256"] == sha(log_raw) and receipt["resources_sha256"] == sha(resource_raw),
                "r28 output receipt hash mismatch")
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M) == [b"0"],
                "r28 resource exit mismatch")
        if phase == "strict":
            require(receipt["acceptance_readback"] is None, "unexpected strict acceptance schema")
        else:
            review_name = stem + "-result-review.json"
            verify_pointer(receipt["acceptance_readback"], review_name, originals)
            if phase == "python-runner":
                computed = review_python(log_raw)
            else:
                rows, computed = review_inherited_tests(log_raw, baseline)
                require(records[stem + "-test-results.json"] == rows, "r28 unique test rows differ from full log")
            require(computed["pass"] is True and records[review_name] == computed,
                    "r28 original full-log acceptance cannot be reproduced: " + phase)
        receipts.append({"path": receipt_name, **data_pin(originals[receipt_name])})
    initial_name, final_name = R28_PREFIX + "-source-pre-verification.json", R28_PREFIX + "-source-final-verification.json"
    verify_inherited_guard(records[initial_name], initial_name)
    verify_inherited_guard(records[final_name], final_name)
    preconditions = records[R28_PREFIX + "-preconditions.json"]
    require(preconditions["schema"] == "hepta.source52-project-preconditions.v1", "r28 precondition schema mismatch")
    require(preconditions["source_tree"] == SOURCE52_TREE and preconditions["source_commit"] == SOURCE52_COMMIT
            and preconditions["actual_changed_file_count"] == SOURCE52_CHANGED_COUNT, "r28 precondition source mismatch")
    require(preconditions["source_manifest"] == source_pin and preconditions["baseline"] == baseline_pin,
            "r28 source/baseline exact inputs differ")
    require(preconditions["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and preconditions["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r28 precondition locks differ")
    require(preconditions["patch_application_performed_by_this_runner"] is False
            and preconditions["lock_update_performed_by_this_runner"] is False
            and preconditions["expected_python_tests"] == PYTHON_TEST_COUNT, "r28 precondition semantics differ")
    verify_pointer(preconditions["initial_source_guard"], initial_name, originals)
    # Recompute the same source52 apply and source50 inheritance proof from
    # their separately fixed originals. Historical pending/failed fields remain intact.
    require(preconditions["source50_lock_originals_and_outer_terminal"] == lock_pins,
            "r28 historical lock originals differ from independently verified closure")
    require(preconditions["source50_root_manifest"] == source50_pin,
            "r28 historical source50 manifest differs")
    require(preconditions["source51_parent_manifest"] == source51_pin,
            "r28 actual source51 parent manifest differs")
    require(preconditions["source52_apply"] == apply_proof,
            "r28 apply/inheritance proof differs from independently verified closure")
    require(preconditions["original_r24_failed_100_provenance"] == r24_failed_pins,
            "r28 original r24 failure provenance differs")
    require(preconditions["original_r26_failed_100_provenance"] == r26_failed_pins,
            "r28 original r26 failure provenance differs")
    require(preconditions["source50_lock_inherited_only_for_unchanged_dependency_inputs"] is True
            and preconditions["source52_bazel_lock_update_executed"] is False,
            "r28 historical lock inheritance was relabeled as a new lock execution")
    require(preconditions["baseline_use"] == "acceptance only after the full unfiltered gate",
            "r28 baseline is not post-gate acceptance")
    require(preconditions["previous_source49_workspace_result"]
            == "FAILED_100_20220_PASS_7_FAIL_1_TIMEOUT_130_REPORTED_SKIP"
            and preconditions["previous_source50_project_result"]
            == "FAILED_100_1561_PASS_3_FAIL_0_TIMEOUT_3_REPORTED_SKIP"
            and preconditions["previous_source51_project_result"]
            == "FAILED_100_1562_PASS_2_FAIL_0_TIMEOUT_3_REPORTED_SKIP",
            "r28 historical failure snapshots changed")
    environment = records[R28_PREFIX + "-environment.json"]
    require(environment["schema"] == "hepta.source52-project-environment.v1", "r28 environment schema mismatch")
    require(environment["source_tree"] == SOURCE52_TREE and environment["source_commit"] == SOURCE52_COMMIT
            and environment["source_manifest"] == SOURCE52_MANIFEST_NAME
            and environment["source_manifest_sha256"] == SOURCE52_MANIFEST_SHA256, "r28 environment identity mismatch")
    require(environment["source_environment_immutable_during_gates"] is True
            and environment["test_deadlines_features_filters_retries_unchanged"] is True
            and environment["sandbox_or_network_protection_environment_overridden"] is False,
            "r28 environment contract changed")
    complete = records[R28_PREFIX + "-complete.json"]
    require(complete["schema"] == "hepta.source52-project-gates-complete.v1", "r28 complete schema mismatch")
    require(complete["source_tree"] == SOURCE52_TREE and complete["source_commit"] == SOURCE52_COMMIT
            and complete["source_manifest"] == SOURCE52_MANIFEST_NAME
            and complete["source_manifest_sha256"] == SOURCE52_MANIFEST_SHA256, "r28 complete source mismatch")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r28 complete dual-lock mismatch")
    require(complete["python_exit"] == complete["strict_exit"] == complete["tests_exit"] == 0
            and complete["python_tests"] == PYTHON_TEST_COUNT and complete["python_skipped"] == 0,
            "r28 complete does not certify original three phases")
    require(complete["packages"] == HISTORICAL_FOUR_PACKAGES and complete["required_old_ids"] == HISTORICAL_BASELINE_COUNT
            and complete["all_old_ids_observed_pass"] is True, "r28 completed coverage differs")
    require(complete["phase_receipts"] == receipts and complete["source_guards_pass"] is True,
            "r28 complete receipts/guard differ")
    require(complete["workspace_not_started_by_this_runner"] is True and complete["fix_fmt_executed"] is False,
            "r28 completion phase confusion")
    require(complete["source50_lock_inherited_for_unchanged_dependency_inputs"] is True
            and complete["source52_bazel_lock_update_executed"] is False,
            "r28 completion lock inheritance differs")
    require(complete["source52_apply_complete"] == apply_proof["complete"],
            "r28 complete is not bound to the verified apply")
    require(complete["whole_workspace_qualification"] == "PENDING_SEPARATE_ORIGINAL_GATE",
            "r28 project completion was relabeled as a workspace result")
    terminal_raw = pinned_read(R28_TERMINAL_NAME, {"bytes": R28_TERMINAL_BYTES, "sha256": R28_TERMINAL_SHA256})
    terminal = closed_terminal(terminal_raw, R28_JOB_ID, "succeeded", 0)
    require(terminal["at_unix_ms"] / 1000 >= previous_end, "r28 terminal precedes tests completion")
    return {
        "schema": "hepta.r31-historical-source52-r28-readback.v1",
        "source_tree": SOURCE52_TREE, "source_commit": SOURCE52_COMMIT,
        "originals": [{"path": name, **data_pin(originals[name])} for name in r28_required_names()],
        "outer_terminal": {"path": R28_TERMINAL_NAME, **data_pin(terminal_raw)},
        "phase_receipts": receipts, "python_tests": PYTHON_TEST_COUNT, "python_skipped": 0,
        "old_four_package_ids_recomputed_from_full_log": HISTORICAL_BASELINE_COUNT,
        "historical_source52_all_three_phases_and_outer_pass": True,
        "source53_execution_claimed": False, "substitutes_for_r30": False,
        "source52_apply": apply_proof, "source50_lock_originals": lock_pins,
        "source50_root_manifest": source50_pin, "source51_parent_manifest": source51_pin,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "original_r26_failed_100_provenance": r26_failed_pins,
        "r25_remains_blocked_and_unexecuted": True,
        "r27_remains_blocked_and_unexecuted": True,
        "baseline_used_as_filter": False,
    }, environment

def r30_required_names():
    names = [R30_PREFIX + suffix for suffix in (
        "-environment.json", "-preconditions.json", "-source-pre-verification.json",
        "-source-final-verification.json", "-complete.json",
    )]
    for phase in R30_PHASES:
        stem = R30_PREFIX + "-" + phase
        names.extend(stem + suffix for suffix in (
            ".log", "-resources.txt", "-raw-process-result.json", "-receipt.json",
            "-source-pre-verification.json", "-source-post-verification.json",
        ))
    names.extend((R30_PREFIX + "-tests-result-review.json", R30_PREFIX + "-tests-test-results.json"))
    return names


def check_bindings():
    check_source_bindings()  # False/None/optimization barriers precede any writes or subprocesses.
    require(type(SOURCE_MANIFEST_BYTES) is int and SOURCE_MANIFEST_BYTES > 0,
            "actual source53 full-manifest byte count missing")
    require(isinstance(R30_JOB_ID, str) and bool(R30_JOB_ID), "actual naturally closed r30 job missing")
    require(R30_JOB_ID not in (APPLY_JOB_ID, LOCK_JOB_ID, R24_JOB_ID, R26_JOB_ID, R29_JOB_ID, R28_JOB_ID),
            "r30 job identity reused")
    require(R30_TERMINAL_NAME == R30_PREFIX + "-terminal-process-status.json", "wrong r30 terminal name")
    require(hex_digest(R30_TERMINAL_SHA256, 64), "r30 natural terminal hash missing")
    require(type(R30_TERMINAL_BYTES) is int and R30_TERMINAL_BYTES > 0, "r30 terminal byte count missing")
    require(isinstance(R30_INPUT_PINS, dict) and set(R30_INPUT_PINS) == set(r30_required_names())
            and len(R30_INPUT_PINS) == 19, "all nineteen successful r30 originals required")
    for name, expected in R30_INPUT_PINS.items():
        safe_relative(name)
        require(not name.startswith(PREFIX + "-"), "input collides with create-only workspace output")
        require(set(expected) == {"bytes", "sha256"}, "unexpected r30 original pin fields")
        require(type(expected["bytes"]) is int and expected["bytes"] >= 0
                and hex_digest(expected["sha256"], 64), "r30 original byte/hash binding missing")


def r30_prerequisite(baseline, source_pin, baseline_pin, lock_pins, source50_pin,
                     source51_pin, source52_pin, apply_proof, r24_failed_pins,
                     r26_failed_pins, r29_failed_pins):
    originals = {name: pinned_read(name, R30_INPUT_PINS[name]) for name in r30_required_names()}
    records = {name: json.loads(raw) for name, raw in originals.items() if name.endswith(".json")}
    commands = {
        "strict": ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"],
    }
    receipts, previous_end = [], None
    for phase in R30_PHASES:
        stem = R30_PREFIX + "-" + phase
        raw_name, receipt_name = stem + "-raw-process-result.json", stem + "-receipt.json"
        pre_name, post_name = stem + "-source-pre-verification.json", stem + "-source-post-verification.json"
        raw, receipt = records[raw_name], records[receipt_name]
        require(raw["schema"] == "hepta.native-raw-process-result.v1"
                and receipt["schema"] == "hepta.native-gate-receipt.v2", "r30 phase schema mismatch")
        for value in (raw, receipt):
            require(value["phase"] == phase and value["command"] == commands[phase]
                    and value["cwd"] == str(S / "codex-rs"), "wrong complete app-server command")
            require(value["source_tree"] == EXPECTED_TREE and value["source_commit"] == EXPECTED_COMMIT
                    and value["exit_code"] == 0, "same-source r30 original phase did not pass")
        for key in ("source_tree", "source_commit", "phase", "command", "cwd", "start_unix", "end_unix", "exit_code"):
            require(raw[key] == receipt[key], "r30 raw/receipt mismatch: " + phase + "/" + key)
        require(receipt["end_unix"] >= receipt["start_unix"]
                and abs(receipt["elapsed_seconds"] - (receipt["end_unix"] - receipt["start_unix"])) < 1e-6,
                "r30 phase timing mismatch")
        require(previous_end is None or receipt["start_unix"] >= previous_end, "r30 phase ordering mismatch")
        previous_end = receipt["end_unix"]
        require(receipt["effective_exit_code"] == 0 and receipt["phase_pass"] is True
                and receipt["issues"] == [] and receipt["source_guards_pass"] is True,
                "r30 acceptance/source guard failed")
        require(receipt["source_manifest"] == SOURCE_MANIFEST_NAME
                and receipt["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256
                and receipt["environment_manifest"] == R30_PREFIX + "-environment.json",
                "r30 manifest/environment binding mismatch")
        require(receipt["packages"] == PACKAGES == ["codex-app-server"]
                and receipt["retries"] == (0 if phase == "tests" else None)
                and receipt["filters"] == "no_additions" and receipt["features"] == "unchanged_defaults",
                "r30 selection changed")
        require(receipt["fix_fmt_executed"] is False and receipt["baseline_used_as_filter"] is False
                and receipt["diagnostic_only"] is True and receipt["behavior_repair_claimed"] is False,
                "r30 diagnostic/scope semantics changed")
        verify_pointer(receipt["raw_process_result"], raw_name, originals)
        verify_pointer(receipt["source_postguard"], post_name, originals)
        verify_recorded_guard(records[pre_name], pre_name)
        verify_recorded_guard(records[post_name], post_name)
        require(records[post_name]["gate_exit_code"] == 0 and records[post_name]["phase"] == phase,
                "r30 postguard is not the successful phase")
        log_raw, resource_raw = originals[stem + ".log"], originals[stem + "-resources.txt"]
        require(receipt["log_sha256"] == sha(log_raw) and receipt["resources_sha256"] == sha(resource_raw),
                "r30 original log/resource hash mismatch")
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M) == [b"0"],
                "r30 original resource exit mismatch")
        if phase == "strict":
            require(receipt["acceptance_readback"] is None, "unexpected strict acceptance schema")
        else:
            review_name = stem + "-result-review.json"
            verify_pointer(receipt["acceptance_readback"], review_name, originals)
            rows, computed = review_tests(log_raw, baseline)
            require(records[stem + "-test-results.json"] == rows, "r30 test rows differ from full original log")
            require(computed["pass"] is True and records[review_name] == computed,
                    "r30 exact1345 full-log acceptance cannot be reproduced")
        receipts.append({"path": receipt_name, **data_pin(originals[receipt_name])})
    initial_name, final_name = R30_PREFIX + "-source-pre-verification.json", R30_PREFIX + "-source-final-verification.json"
    verify_recorded_guard(records[initial_name], initial_name)
    verify_recorded_guard(records[final_name], final_name)
    pre = records[R30_PREFIX + "-preconditions.json"]
    require(pre["schema"] == "hepta.source53-project-preconditions.v1", "r30 precondition schema mismatch")
    require(pre["source_tree"] == EXPECTED_TREE and pre["source_commit"] == EXPECTED_COMMIT
            and pre["actual_changed_file_count"] == EXPECTED_CHANGED_COUNT == 197,
            "r30 precondition source mismatch")
    require(pre["source_manifest"] == source_pin and pre["baseline"] == baseline_pin,
            "r30 source/baseline original inputs differ")
    require(pre["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and pre["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r30 precondition dual locks differ")
    verify_pointer(pre["initial_source_guard"], initial_name, originals)
    for key, expected in (
        ("source50_lock_originals_and_outer_terminal", lock_pins),
        ("source50_root_manifest", source50_pin), ("source51_historical_manifest", source51_pin),
        ("source52_parent_manifest", source52_pin), ("source53_apply", apply_proof),
        ("original_r24_failed_100_provenance", r24_failed_pins),
        ("original_r26_failed_100_provenance", r26_failed_pins),
        ("original_r29_failed_100_provenance", r29_failed_pins),
    ):
        require(pre[key] == expected, "r30 producer/consumer prerequisite differs: " + key)
    require(pre["source50_lock_inherited_only_for_unchanged_dependency_inputs"] is True
            and pre["source53_bazel_lock_update_executed"] is False
            and pre["patch_application_performed_by_this_runner"] is False
            and pre["lock_update_performed_by_this_runner"] is False,
            "r30 source/lock provenance relabelled")
    require(pre["baseline_use"] == "acceptance only after the full unfiltered app-server gate"
            and pre["previous_source52_workspace_result"] == "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
            "r30 baseline or original r29 failure meaning changed")
    require(pre["python_runner_source_unchanged"] is True and pre["python_suite_reexecuted"] is False
            and pre["diagnostic_only"] is True and pre["behavior_repair_claimed"] is False,
            "r30 diagnostic/Python classification changed")
    environment = records[R30_PREFIX + "-environment.json"]
    require(environment["schema"] == "hepta.source53-project-environment.v1", "r30 environment schema mismatch")
    require(environment["source_tree"] == EXPECTED_TREE and environment["source_commit"] == EXPECTED_COMMIT
            and environment["source_manifest"] == SOURCE_MANIFEST_NAME
            and environment["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256,
            "r30 environment source binding mismatch")
    require(environment["source_environment_immutable_during_gates"] is True
            and environment["test_deadlines_features_filters_retries_unchanged"] is True
            and environment["sandbox_or_network_protection_environment_overridden"] is False
            and environment["diagnostic_only"] is True and environment["behavior_repair_claimed"] is False,
            "r30 environment contract changed")
    complete = records[R30_PREFIX + "-complete.json"]
    require(complete["schema"] == "hepta.source53-project-gates-complete.v1", "r30 complete schema mismatch")
    require(complete["source_tree"] == EXPECTED_TREE and complete["source_commit"] == EXPECTED_COMMIT
            and complete["source_manifest"] == SOURCE_MANIFEST_NAME
            and complete["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256,
            "r30 complete source mismatch")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r30 complete dual-lock mismatch")
    require(complete["strict_exit"] == complete["tests_exit"] == 0
            and complete["packages"] == PACKAGES and complete["required_old_ids"] == BASELINE_COUNT == 1345
            and complete["all_old_ids_observed_pass"] is True, "r30 complete coverage differs")
    require(complete["phase_receipts"] == receipts and complete["source_guards_pass"] is True,
            "r30 complete original receipts differ")
    require(complete["source50_lock_inherited_for_unchanged_dependency_inputs"] is True
            and complete["source53_bazel_lock_update_executed"] is False
            and complete["source53_apply_complete"] == apply_proof["complete"],
            "r30 completion lock/apply provenance differs")
    require(complete["workspace_not_started_by_this_runner"] is True and complete["fix_fmt_executed"] is False
            and complete["python_suite_reexecuted"] is False, "r30 completion phase confusion")
    require(complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False
            and complete["original_r29_failure_relabelled_as_pass"] is False
            and complete["whole_workspace_qualification"] == "PENDING_SEPARATE_ORIGINAL_GATE",
            "r30 diagnostic gate was relabelled as a repair/workspace result")
    terminal_raw = pinned_read(R30_TERMINAL_NAME, {"bytes": R30_TERMINAL_BYTES, "sha256": R30_TERMINAL_SHA256})
    terminal = closed_terminal(terminal_raw, R30_JOB_ID, "succeeded", 0)
    require(terminal["at_unix_ms"] / 1000 >= previous_end, "r30 terminal precedes completed tests")
    return {
        "schema": "hepta.r31-closed-r30-prerequisite-readback.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "originals": [{"path": name, **data_pin(originals[name])} for name in r30_required_names()],
        "outer_terminal": {"path": R30_TERMINAL_NAME, **data_pin(terminal_raw)},
        "phase_receipts": receipts, "old_app_server_ids_recomputed_from_full_log": BASELINE_COUNT,
        "same_source_strict_full_tests_and_outer_pass": True, "exact_old_test_id_set": True,
        "source53_apply": apply_proof, "source50_lock_originals": lock_pins,
        "source50_root_manifest": source50_pin, "source51_historical_manifest": source51_pin,
        "source52_parent_manifest": source52_pin,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "original_r26_failed_100_provenance": r26_failed_pins,
        "original_r29_failed_100_provenance": r29_failed_pins,
        "python_suite_reexecuted": False, "baseline_used_as_filter": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }, environment

def review_original_workspace(raw, workspace_names):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [item for item in starts if item[3]]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [item for item in summaries if item[3]]
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows, footer = [], []
    start = starts[0] if len(starts) == 1 else None
    summary = summaries[0] if len(summaries) == 1 else None
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start and number > start[0] and (summary is None or number < summary[0]):
            rows.append(row)
        elif summary and number > summary[0]:
            footer.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    observed_counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    summary_counts, skipped, summary_record = None, None, None
    if summary:
        def count(label):
            match = re.search(r"\b([0-9]+) " + label + r"\b", summary[3][3])
            return int(match[1]) if match else 0
        summary_counts = {"PASS": count("passed"), "FAIL": count("failed"), "TIMEOUT": count("timed out")}
        skipped = count("skipped")
        summary_record = {"line": summary[0], "byte_offset": summary[1], "text": summary[2],
                          "seconds": float(summary[3][1]), "tests_run": int(summary[3][2])}
    unknown_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(workspace_names))
    complete = (
        len(starts) == len(summaries) == 1 and start[0] < summary[0]
        and bool(rows) and len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and observed_counts == summary_counts and not unknown_packages
    )
    passed = complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0
    review = {
        "schema": "hepta.source52-workspace-closed-readback.v1",
        "source_tree": SOURCE52_TREE, "source_commit": SOURCE52_COMMIT, "log": data_pin(raw),
        "starting_lines": [{"line": n, "byte_offset": o, "text": text, "announced_tests": int(m[1])}
                           for n, o, text, m in starts],
        "summary": summary_record, "summary_line_count": len(summaries),
        "nextest_started": bool(starts), "complete_execution_accounting": complete,
        "execution_rows_observed": len(rows), "unique_binary_name_ids_observed": len(current),
        "terminal_unique_test_count": len(current) if complete else None,
        "terminal_counts": observed_counts if complete else None,
        "observed_counts_not_terminal_without_complete_summary": observed_counts,
        "summary_counts": summary_counts, "reported_skipped": skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer, "unknown_workspace_packages": unknown_packages,
        "no_execution_claim_from_compile_failure": True,
        "test_ids_used_as_filter": False, "pass": bool(passed),
    }
    return rows, review

def load_workspace_baseline():
    # Only old, fixed R29 bytes are parsed here. Fresh source53 metadata is a
    # separate later command. These old IDs never enter a test command/filter.
    originals = {name: pinned_read(name, expected) for name, expected in R29_WORKSPACE_BASELINE_INPUT_PINS.items()}
    old_prefix = "native-workspace-r29"
    metadata = json.loads(originals[old_prefix + "-metadata.json"])
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    require(metadata["workspace_root"] == str(S / "codex-rs")
            and metadata["target_directory"] == str(T / "target"), "original r29 metadata root/target differs")
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
            and set(members) == set(defaults), "original r29 default workspace scope differs")
    packages = {package["id"]: package for package in metadata["packages"]}
    require(len(packages) == len(metadata["packages"]) and set(members) <= set(packages),
            "original r29 metadata package identity ambiguity")
    names = {packages[identity]["name"] for identity in members}
    rows, computed = review_original_workspace(originals[old_prefix + "-tests.log"], names)
    require(rows == json.loads(originals[old_prefix + "-test-results.json"]),
            "original r29 rows differ from independently reparsed full log")
    require(computed == json.loads(originals[old_prefix + "-result-review.json"]),
            "original r29 full-log readback cannot be reproduced")
    require(computed["complete_execution_accounting"] is True and computed["pass"] is False
            and computed["terminal_unique_test_count"] == 20228
            and computed["terminal_counts"] == {"PASS": 20227, "FAIL": 1, "TIMEOUT": 0}
            and computed["reported_skipped"] == 130, "original r29 failure population was relabelled")
    identities = {(row["binary"], row["name"]) for row in rows}
    require(len(identities) == len(rows) == 20228, "original r29 binary/name identity count differs")
    receipt_raw, _ = read_fixed(old_prefix + "-tests-receipt.json",
                                R29_FAILURE_PINS[old_prefix + "-tests-receipt.json"]["bytes"],
                                R29_FAILURE_PINS[old_prefix + "-tests-receipt.json"]["sha256"])
    receipt = json.loads(receipt_raw)
    require(receipt["log_sha256"] == sha(originals[old_prefix + "-tests.log"]),
            "original r29 full log not bound to its failed receipt")
    verify_pointer(receipt["acceptance_readback"], old_prefix + "-result-review.json", originals)
    return identities, {
        "schema": "hepta.r31-original-r29-workspace-baseline.v1",
        "source_commit": SOURCE52_COMMIT, "source_tree": SOURCE52_TREE,
        "originals": [{"path": name, **data_pin(raw)} for name, raw in originals.items()],
        "identity_key": ["binary", "name"], "count": len(identities),
        "observed_original_counts": computed["terminal_counts"],
        "original_reported_skipped": computed["reported_skipped"],
        "original_failed_100_preserved": True, "test_ids_used_as_filter": False,
        "acceptance": "exact identity set only after the complete original unfiltered workspace gate",
        "old_metadata_reused_as_current": False,
    }

def capture_metadata(env, files):
    # This is a new metadata invocation on the frozen source53, never a copy of
    # the old source49 workspace metadata or a claim about all feature/platforms.
    stem = PREFIX + "-metadata"
    stdout_path, stderr_path = E / (stem + ".json"), E / (stem + "-stderr.log")
    started = time.time()
    with stdout_path.open("xb") as output, stderr_path.open("xb") as errors:
        process = subprocess.Popen(METADATA_COMMAND, cwd=S / "codex-rs", env=env, stdout=output, stderr=errors)
        try:
            rc = process.wait()
        finally:
            if process.poll() is None:
                rc = process.wait()
            else:
                rc = process.returncode
            ended = time.time()
            raw_pin = write_json(stem + "-raw-process-result.json", {
                "schema": "hepta.native-raw-process-result.v1", "phase": "workspace-metadata",
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "command": METADATA_COMMAND, "cwd": str(S / "codex-rs"),
                "start_unix": started, "end_unix": ended, "exit_code": rc,
                "log_and_resource_hashing_pending": True,
                "resources_not_collected_for_read_only_metadata": True,
            })
    post = guard(files)
    post_pin = write_json(stem + "-source-post-verification.json", post)
    metadata_raw, stderr_raw = stdout_path.read_bytes(), stderr_path.read_bytes()
    write_json(stem + "-receipt.json", {
        "schema": "hepta.native-metadata-receipt.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "command": METADATA_COMMAND, "cwd": str(S / "codex-rs"),
        "start_unix": started, "end_unix": ended, "elapsed_seconds": ended - started,
        "exit_code": rc, "raw_process_result": raw_pin,
        "stdout": data_pin(metadata_raw), "stderr": data_pin(stderr_raw),
        "source_postguard": post_pin, "source_guards_pass": post["pass"],
    })
    require(rc == 0 and post["pass"], "current metadata command or source postguard failed")
    metadata = json.loads(metadata_raw)
    require(metadata["workspace_root"] == str(S / "codex-rs"), "wrong metadata workspace root")
    require(metadata["target_directory"] == str(T / "target"), "metadata used a different task target")
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == EXPECTED_WORKSPACE_MEMBER_COUNT
            and set(members) == set(defaults), "actual default workspace is not all 193 members")
    packages = {package["id"]: package for package in metadata["packages"]}
    require(len(packages) == len(metadata["packages"]) and set(members) <= set(packages),
            "ambiguous or absent workspace package identities")
    scope = {
        "schema": "hepta.source53-current-default-workspace-scope.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "metadata_command": METADATA_COMMAND, "metadata": {"path": stem + ".json", **data_pin(metadata_raw)},
        "metadata_generated_on_current_source": True, "old_metadata_reused_as_current": False,
        "workspace_root": metadata["workspace_root"], "target_directory": metadata["target_directory"],
        "workspace_member_count": len(members), "workspace_default_member_count": len(defaults),
        "workspace_members": [{"id": identity, "name": packages[identity]["name"],
                               "manifest_path": packages[identity]["manifest_path"]} for identity in members],
        "workspace_default_members": [{"id": identity, "name": packages[identity]["name"]} for identity in defaults],
        "command": COMMAND, "features": "unchanged_defaults", "filters": "no_additions",
        "all_platforms_features_external_services_qualified": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }
    return scope, write_json(PREFIX + "-scope.json", scope)

def review_workspace(raw, workspace_names, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [item for item in starts if item[3]]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [item for item in summaries if item[3]]
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows, footer = [], []
    start = starts[0] if len(starts) == 1 else None
    summary = summaries[0] if len(summaries) == 1 else None
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start and number > start[0] and (summary is None or number < summary[0]):
            rows.append(row)
        elif summary and number > summary[0]:
            footer.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    observed_counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    summary_counts, skipped, summary_record = None, None, None
    if summary:
        def count(label):
            match = re.search(r"\b([0-9]+) " + label + r"\b", summary[3][3])
            return int(match[1]) if match else 0
        summary_counts = {"PASS": count("passed"), "FAIL": count("failed"), "TIMEOUT": count("timed out")}
        skipped = count("skipped")
        summary_record = {"line": summary[0], "byte_offset": summary[1], "text": summary[2],
                          "seconds": float(summary[3][1]), "tests_run": int(summary[3][2])}
    unknown_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(workspace_names))
    complete = (
        len(starts) == len(summaries) == 1 and start[0] < summary[0]
        and bool(rows) and len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and observed_counts == summary_counts and not unknown_packages
    )
    missing = sorted(baseline - set(current))
    additional = sorted(set(current) - baseline)
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    passed = (complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0
              and not missing and not additional and not unsuccessful)
    review = {
        "schema": "hepta.source53-workspace-closed-readback.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT, "log": data_pin(raw),
        "starting_lines": [{"line": n, "byte_offset": o, "text": text, "announced_tests": int(m[1])}
                           for n, o, text, m in starts],
        "summary": summary_record, "summary_line_count": len(summaries),
        "nextest_started": bool(starts), "complete_execution_accounting": complete,
        "execution_rows_observed": len(rows), "unique_binary_name_ids_observed": len(current),
        "terminal_unique_test_count": len(current) if complete else None,
        "terminal_counts": observed_counts if complete else None,
        "observed_counts_not_terminal_without_complete_summary": observed_counts,
        "summary_counts": summary_counts, "reported_skipped": skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer, "unknown_workspace_packages": unknown_packages,
        "no_execution_claim_from_compile_failure": True,
        "test_ids_used_as_filter": False, "pass": bool(passed),
        "original_r29_baseline_count": len(baseline),
        "original_r29_baseline_is_failed_population": True,
        "exact_old_test_id_set_required": True,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in additional],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }
    return rows, review

def run_workspace(env, files, scope, scope_pin, workspace_baseline, workspace_baseline_proof):
    pre = guard(files)
    pre_pin = write_json(PREFIX + "-tests-source-pre-verification.json", pre)
    require(pre["pass"], "workspace preguard failed")
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space before original workspace gate")
    log, resources = E / (PREFIX + "-tests.log"), E / (PREFIX + "-tests-resources.txt")
    started = time.time()
    announce({
        "phase": "original-default-workspace-start", "source_tree": EXPECTED_TREE,
        "source_commit": EXPECTED_COMMIT, "command": COMMAND, "cwd": str(S / "codex-rs"),
        "workspace_member_count": scope["workspace_member_count"],
        "workspace_default_member_count": scope["workspace_default_member_count"],
        "outer_timeout_seconds_contract": OUTER_TIMEOUT_SECONDS_CONTRACT,
    })
    with log.open("xb") as output:
        process = subprocess.Popen(
            ["/usr/bin/time", "-v", "-o", str(resources), *COMMAND],
            cwd=S / "codex-rs", env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            rc = process.wait()
        finally:
            if process.poll() is None:
                rc = process.wait()
            else:
                rc = process.returncode
            ended = time.time()
            raw_result = {
                "schema": "hepta.native-raw-process-result.v1", "phase": "workspace-tests",
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "command": COMMAND, "cwd": str(S / "codex-rs"),
                "start_unix": started, "end_unix": ended, "exit_code": rc,
                "log_and_resource_hashing_pending": True,
            }
            raw_pin = write_json(PREFIX + "-tests-raw-process-result.json", raw_result)
            announce({**raw_result, "event": "workspace-raw-process-return"})
    issues, log_raw, resource_raw = [], None, None
    try:
        log_raw, resource_raw = log.read_bytes(), resources.read_bytes()
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M) == [str(rc).encode()],
                "workspace resource/raw exit mismatch")
    except Exception as error:
        issues.append({"stage": "original_output_readback", "error": repr(error)})
    post = guard(files)
    post.update(phase="workspace-tests", gate_exit_code=rc)
    post_pin = write_json(PREFIX + "-source-post-test-verification.json", post)
    if not post["pass"]:
        issues.append({"stage": "source_postguard", "error": "source/dual-lock changed; source retained"})
    acceptance_pin, review = None, None
    if log_raw is not None:
        try:
            names = {package["name"] for package in scope["workspace_members"]}
            rows, review = review_workspace(log_raw, names, workspace_baseline)
            write_json(PREFIX + "-test-results.json", rows)
            acceptance_pin = write_json(PREFIX + "-result-review.json", review)
            if not review["pass"]:
                issues.append({"stage": "closed_log_acceptance", "error": "workspace did not complete with every executed result PASS"})
        except Exception as error:
            issues.append({"stage": "closed_log_parse", "error": repr(error)})
    effective = rc if rc else (1 if issues else 0)
    receipt = {
        "schema": "hepta.native-workspace-gate-receipt.v2", "phase": "workspace-tests",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "command": COMMAND, "cwd": str(S / "codex-rs"),
        "start_unix": started, "end_unix": ended, "elapsed_seconds": ended - started,
        "exit_code": rc, "effective_exit_code": effective, "raw_process_result": raw_pin,
        "log_sha256": sha(log_raw) if log_raw is not None else None,
        "resources_sha256": sha(resource_raw) if resource_raw is not None else None,
        "environment_manifest": PREFIX + "-environment.json",
        "source_preguard": pre_pin, "source_postguard": post_pin, "source_guards_pass": post["pass"],
        "test_scope": "original_default_workspace", "packages_argument": None,
        "workspace_member_count": scope["workspace_member_count"],
        "workspace_default_member_count": scope["workspace_default_member_count"],
        "scope": scope_pin, "retries": 0, "features": "unchanged_defaults", "filters": "no_additions",
        "acceptance_readback": acceptance_pin, "issues": issues, "phase_pass": effective == 0,
        "fix_fmt_executed": False, "outer_timeout_seconds_contract": OUTER_TIMEOUT_SECONDS_CONTRACT,
        "free_bytes_after": shutil.disk_usage(T).free,
        "free_space_is_shared_filesystem_sample_not_exclusive_gate_cost": True,
        "original_r29_workspace_baseline": workspace_baseline_proof,
        "test_ids_used_as_filter": False, "exact_old_test_id_set_required": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }
    receipt_pin = write_json(PREFIX + "-tests-receipt.json", receipt)
    announce(receipt)
    if effective == 0:
        require(review is not None and review["pass"], "successful workspace readback missing")
        write_json(PREFIX + "-complete.json", {
            "schema": "hepta.source53-default-workspace-complete.v1",
            "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
            "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
            "command": COMMAND, "workspace_exit": rc, "effective_exit_code": effective,
            "source_guards_pass": True, "workspace_member_count": scope["workspace_member_count"],
            "workspace_default_member_count": scope["workspace_default_member_count"],
            "unique_test_count": review["terminal_unique_test_count"], "counts": review["terminal_counts"],
            "reported_skipped": review["reported_skipped"], "receipt": receipt_pin,
            "readback": acceptance_pin, "scope": scope_pin, "fix_fmt_executed": False,
            "all_platforms_features_external_services_qualified": False,
            "original_r29_workspace_baseline": workspace_baseline_proof,
            "exact_old_test_id_set_observed_pass": True, "test_ids_used_as_filter": False,
            "diagnostic_only": True, "behavior_repair_claimed": False,
            "original_r29_failure_relabelled_as_pass": False,
            "free_bytes_after": shutil.disk_usage(T).free,
        })
    else:
        write_json(PREFIX + "-incomplete.json", {
            "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
            "original_exit_code": rc, "effective_exit_code": effective, "receipt": receipt_pin,
            "terminal_counts": review["terminal_counts"] if review else None,
            "nextest_started": review["nextest_started"] if review else None,
            "fix_fmt_executed": False, "no_automatic_retry": True, "source_retained": True,
            "diagnostic_only": True, "behavior_repair_claimed": False,
        })
    return effective

def run_frozen():
    require(not list(E.glob(PREFIX + "-*")), "this run prefix already has evidence; no automatic retry")
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space")
    generated, lock_pins = lock_prerequisite()
    (files, source_pin, source50_files, source50_pin, source51_files,
     source51_pin, source52_files, source52_pin) = load_source(generated)
    require(source_pin["bytes"] == SOURCE_MANIFEST_BYTES, "source53 full-manifest byte count differs")
    r24_failed_pins = r24_failed_prerequisite()
    r26_failed_pins = r26_failed_prerequisite()
    r29_failed_pins = r29_failed_prerequisite()
    apply_proof = apply_prerequisite(files, source_pin, source50_files, source51_files, source52_files)
    baseline, baseline_pin = load_baseline()
    prerequisites, prior_environment = r30_prerequisite(
        baseline, source_pin, baseline_pin, lock_pins, source50_pin, source51_pin,
        source52_pin, apply_proof, r24_failed_pins, r26_failed_pins, r29_failed_pins,
    )
    historical_baseline, historical_baseline_pin = load_inherited_baseline()
    historical_apply = historical_source52_apply_prerequisite(source52_pin)
    inherited, historical_environment = r28_inherited_prerequisite(
        historical_baseline, source52_pin, historical_baseline_pin, lock_pins,
        source50_pin, source51_pin, historical_apply, r24_failed_pins, r26_failed_pins,
    )
    workspace_baseline, workspace_baseline_proof = load_workspace_baseline()
    initial = guard(files)
    initial_pin = write_json(PREFIX + "-source-pre-verification.json", initial)
    require(initial["pass"], "same source53 is not clean/byte-identical")
    env, selection, prerequisite_env_pin = execution_environment()
    require(selection == prior_environment["selection"], "selection environment differs from successful r30")
    require(prerequisite_env_pin == prior_environment["approved_prerequisite_env_pin"],
            "approved external prerequisites differ from successful r30")
    require(selection == historical_environment["selection"]
            and prerequisite_env_pin == historical_environment["approved_prerequisite_env_pin"],
            "inherited r28 environment/prerequisite identity differs")
    write_json(PREFIX + "-environment.json", {
        "schema": "hepta.source53-workspace-environment.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "selection": selection, "approved_prerequisite_env_pin": prerequisite_env_pin,
        "free_bytes_before": shutil.disk_usage(T).free,
        "original_default_workspace_selection": True,
        "outer_timeout_seconds_contract": OUTER_TIMEOUT_SECONDS_CONTRACT,
        "test_deadlines_features_filters_retries_unchanged": True,
        "sandbox_or_network_protection_environment_overridden": False,
        "fresh_current_source_metadata_required": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    })
    write_json(PREFIX + "-preconditions.json", {
        "schema": "hepta.source53-workspace-preconditions.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "actual_changed_file_count": len(files), "source_manifest": source_pin,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "initial_source_guard": initial_pin, "r30_closed_gate_readback": prerequisites,
        "source52_r28_historical_project_gate": inherited,
        "historical_project_pass_substitutes_for_r30": False,
        "source50_lock_originals_and_outer_terminal": lock_pins,
        "source50_root_manifest": source50_pin, "source51_historical_manifest": source51_pin,
        "source52_parent_manifest": source52_pin, "source53_apply": apply_proof,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "original_r26_failed_100_provenance": r26_failed_pins,
        "original_r29_failed_100_provenance": r29_failed_pins,
        "source50_lock_inherited_only_for_unchanged_dependency_inputs": True,
        "source53_bazel_lock_update_executed": False,
        "original_r29_workspace_baseline": workspace_baseline_proof,
        "workspace_baseline_used_as_filter": False,
        "workspace_baseline_exact_set_required_after_complete_execution": True,
        "prior_source52_workspace": "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
        "r25_remains_blocked_and_unexecuted": True, "r27_remains_blocked_and_unexecuted": True,
        "older_source_results_are_not_qualification_for_this_source": True,
        "patch_application_performed": False, "lock_update_performed": False,
        "python_suite_reexecuted": False, "workspace_test_command": COMMAND, "fix_fmt_executed": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    })
    scope, scope_pin = capture_metadata(env, files)
    return run_workspace(env, files, scope, scope_pin, workspace_baseline, workspace_baseline_proof)

def main():
    check_bindings()  # False/None rejects before writes and subprocesses.
    try:
        return run_frozen()
    except BaseException as error:
        name = PREFIX + "-orchestration-error.json"
        if E.is_dir() and not (E / name).exists():
            write_json(name, {
                "schema": "hepta.source53-workspace-orchestration-error.v1",
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "error_type": type(error).__name__, "error": str(error),
                "no_automatic_retry": True, "source_retained": True, "fix_fmt_executed": False,
                "diagnostic_only": True, "behavior_repair_claimed": False,
            })
        raise


if __name__ == "__main__":
    sys.exit(main())
