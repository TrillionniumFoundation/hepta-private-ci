#!/usr/bin/env python3
"""Pure local scope derivation. Never invokes Cargo, Git, Rust, fix, or fmt."""
import ast
import gzip
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

FROZEN = True
R31_JOB_ID = '1a1b275ba33-fc05-7e17'
INPUT_PINS = {'input/ROOT-R31-EXECUTION-AUTHORIZATION.json': {'bytes': 2069, 'sha256': 'f97eda581ff5bb65797e2c483466305d8f881de51ac18256777e7f71ba0455ad', 'git_blob': 'e221e55c4679e39ae8a16bbb4d71d5c00342f9c9'}, 'input/hepta-cell-framework-native.yml': {'bytes': 9049, 'sha256': '4e722139be6383505c9c392a3682ca5a0f98cd9fc24427920e40595c64de9d77', 'git_blob': 'a3e915c33dd0fcbb9cc977b999b659e77bcdefe0'}, 'input/native-candidate-r30-source.json': {'bytes': 56747, 'sha256': '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda', 'git_blob': 'eea9da2308a920486e1bbfd613745d390cde61de'}, 'input/native-workspace-r31-metadata.json.gz': {'bytes': 38947, 'sha256': 'c728eb280c432f76e88dc52a661090be5811169de5d2b5372cf066b77ddf3b8d', 'git_blob': '7674123efb977318cf455db1ce86de6f101b2e29'}, 'input/native-workspace-r31-scope.json': {'bytes': 93425, 'sha256': 'bb3fd5a19ef48a929058d66430b09654d4ab3cf36924a223b4dc32cef7faf533', 'git_blob': '8f548a2747ff38fe2bd7494059f9e5c691f06c17'}, 'input/primary/original/AGENTS.md': {'bytes': 22519, 'sha256': 'c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480', 'git_blob': 'faa57cc0db48123e1011f1eb47692cd3bbbcfc3a'}, 'input/primary/original/codex-rs/Cargo.toml': {'bytes': 23125, 'sha256': 'de54aafbd8e041cdaec30705fb6c286bd308f2a03de1c598a778f20feaade34b', 'git_blob': '7e2ec509988e11cdf92130e385ffdf409bbcc15d'}, 'input/primary/original/codex-rs/app-server/Cargo.toml': {'bytes': 4997, 'sha256': '3ab26711af9a5e81fa51468507a9c893ea4b147530c180a0670a866a79623d9f', 'git_blob': 'd3f4b4ef949e5853060ad600d80ed58bc3b85fcf'}, 'input/primary/original/codex-rs/app-server-client/Cargo.toml': {'bytes': 1192, 'sha256': '44769e3a813312d09298e8f297a99d6cf0fa608b9f4fb1009141fcd64c942200', 'git_blob': 'cfe7a3d47f690470979c4386d5a89e640a4270d0'}, 'input/primary/original/codex-rs/cli/Cargo.toml': {'bytes': 4239, 'sha256': '967fd38c5e9fd05c50f19fbcbde5271e5a786f07436ab05310679fba736a947d', 'git_blob': 'd2360ef42c5a8c8a9ffe3231f85220597847f0ab'}, 'input/primary/original/codex-rs/codex-mcp/Cargo.toml': {'bytes': 1726, 'sha256': 'c14b473064600e0886d20b034fb07ab0a5f71d7120c0e6e585f3b93f88aec0ad', 'git_blob': '6134f2126db203999727d05f61921836dfed06b7'}, 'input/primary/original/codex-rs/core/Cargo.toml': {'bytes': 6185, 'sha256': '3a2576956d2844516f1e38554a207c50e44503dd0c49cd8612fb630d3c6eb5f4', 'git_blob': 'df43645d3ca5e18e4ba526479a4c59cb103d3a5d'}, 'input/primary/original/codex-rs/core/tests/common/Cargo.toml': {'bytes': 1677, 'sha256': 'f96f988488fa3b982ae33ab11365b534a1d4d542d5b0cb1140eb3a43e3d4e5ef', 'git_blob': 'a4851eb1d9ef3f9bc0d1535f84e937bfb82aaf93'}, 'input/primary/original/codex-rs/exec-server/Cargo.toml': {'bytes': 2741, 'sha256': 'c45429a966e8d087144085598cac8c63e6e9b285fad97a5700294b409665ee14', 'git_blob': '455df9eedc14b77ac3779899087cd8391b153b37'}, 'input/primary/original/codex-rs/ext/hepta-memory/Cargo.toml': {'bytes': 1184, 'sha256': '6b0cd713fab0d2038840dd6d18ad856bf59de3a34f936977e2fa1c2539da3f91', 'git_blob': '2d17c6481dbe0d75bd057e2edc9e3ee46de88c73'}, 'input/primary/original/codex-rs/external-agent-migration/Cargo.toml': {'bytes': 1325, 'sha256': '9d8bac37beeef7e70f85b273285b2b0bfc3d80fea758eafc69a51511b5f24997', 'git_blob': '3db739977ce9e94f66a3c4c9f22ce869610fa910'}, 'input/primary/original/codex-rs/hepta-agent-protocol/Cargo.toml': {'bytes': 496, 'sha256': '145110b17fd655a247a6c6a309c8fc1d23c36703edfadf0928a069f120167461', 'git_blob': 'ca7afd5c2905cdc02666b0cb20c1f6238a84dbba'}, 'input/primary/original/codex-rs/hepta-agentd/Cargo.toml': {'bytes': 4905, 'sha256': '3641050d95ed757d30d0848ed7b04584f8bafdbf664341fbc462f0b44966c417', 'git_blob': 'a32f7eb893fd529692fd2005ca02ac9e8f853b95'}, 'input/primary/original/codex-rs/hepta-automation/Cargo.toml': {'bytes': 1324, 'sha256': 'e8e39e69d52921298a29ed75a12ae46790298fae8d031625c502258f0b12c78d', 'git_blob': '4a5f0fa0db6a0f27d685012c89f87d0406f2f41b'}, 'input/primary/original/codex-rs/hepta-context-compiler/Cargo.toml': {'bytes': 498, 'sha256': '848d0613ee522fbf4059b6807c07ecd489e46fb81287c5c8382e08a80b51f19e', 'git_blob': '2ce0fb9520b8440a9b20a441d2c7bcbc4529dba0'}, 'input/primary/original/codex-rs/hepta-infer-worker-host/Cargo.toml': {'bytes': 1220, 'sha256': 'e20f4e783adcfa8d82d3394a827e6f4c6d8e5e8e10e9c3be3b20e1c4824aef74', 'git_blob': 'bffa8bfcb7abffd460886a27b2f63a6a0ecb21df'}, 'input/primary/original/codex-rs/hepta-intelligence/Cargo.toml': {'bytes': 1486, 'sha256': '65121f9be6609bb7613d917348875b6b24b33c25545b4d895f6eeb7733dc3dc9', 'git_blob': '162205d6bc62834e1b04fed33dd67f5955f218d1'}, 'input/primary/original/codex-rs/hepta-learning-artifacts/Cargo.toml': {'bytes': 412, 'sha256': 'e66cea514a732f5ddab6ec5eb35a435f46f7becb8a49a4b5b736c89fc37a880a', 'git_blob': '725a63c9f2475ad632c7c189fd9ca271702a8899'}, 'input/primary/original/codex-rs/hepta-memory/Cargo.toml': {'bytes': 1587, 'sha256': '614b0409fd09e39e6bb3d11c488b9fe2fc1ccd18fa29d059b40143a0dcfc2b34', 'git_blob': 'd7c49d539977550a28c9d20f5ac5aa718a9ed0ae'}, 'input/primary/original/codex-rs/hepta-neuron/Cargo.toml': {'bytes': 495, 'sha256': '1ebe7dcf2b82b8143aa298059afff3ea17ee76f7c6140aae41d099bed5031c48', 'git_blob': 'dbd650a75e7ebe47d2642bc653468355d42cd2e3'}, 'input/primary/original/codex-rs/hepta-plasticity/Cargo.toml': {'bytes': 298, 'sha256': '18c15cb8ba6c9a1be619230aa7bd275bb986fb7debd617b23ee8db37e7c9728e', 'git_blob': '07cb9e40d44990874991620f89af8c0078575de1'}, 'input/primary/original/codex-rs/hepta-runtime/Cargo.toml': {'bytes': 1108, 'sha256': '959da171fccbe0748e859753310c19e2c49aa683f8d623f036e503f6e06b5fec', 'git_blob': '83f681ba2fc42402c78aa8ef33889b2b7191bf33'}, 'input/primary/original/codex-rs/hepta-supervisor/Cargo.toml': {'bytes': 2755, 'sha256': '16c8f5bb4a0f8681198c35a14970f918a716f48d89d305d0dade7d0496df0a5c', 'git_blob': '3a5c9f790aca3e0ee660d69d6d8f592b28e76abc'}, 'input/primary/original/codex-rs/linux-sandbox/Cargo.toml': {'bytes': 1187, 'sha256': '7af47b8ac3dbc0cf590f9b4e50a51f4e214d6946aa6581991f267450a0ec31f6', 'git_blob': '0f7c68a152a75cfc2f0369dc098dcf2b996185f2'}, 'input/primary/original/codex-rs/model-provider-info/Cargo.toml': {'bytes': 674, 'sha256': '0491e26d931688444482529ebbccaaca6e8ce118faea389384b763a1686c91ec', 'git_blob': '827dd8744b54ffcaa98673c0c262f5265b717ebf'}, 'input/primary/original/codex-rs/network-proxy/Cargo.toml': {'bytes': 2060, 'sha256': '2b813a781ec8c19a293f3eee3d5ba477780da239b50e3bfc8edc4e785876ef06', 'git_blob': 'a7a9fb38b83ee02823cb56d04def6763f5dff709'}, 'input/primary/original/codex-rs/rust-toolchain.toml': {'bytes': 78, 'sha256': 'e8b379eaa492bf59d35187de269afd1c4f55d85e0322f6fea32803a3fec1a380', 'git_blob': '917d2492264a35bc9c0feaef41878d8825870866'}, 'input/primary/original/codex-rs/rustfmt.toml': {'bytes': 164, 'sha256': '384d5d8a1366a86cd6fc01aecde2b0a5806a9e77073ff53abd97b4f6cad94d1c', 'git_blob': 'f9686f9732d3d48311c41c4fd06b40781928b8ec'}, 'input/primary/original/codex-rs/shell-escalation/Cargo.toml': {'bytes': 976, 'sha256': '154cd9240a02ee6c9075d5ab9543ff98a54768babb91d00e190c590ad3237dc2', 'git_blob': '92ae8b033f3c38edb1609e6347084be6dd9fdc47'}, 'input/primary/original/codex-rs/utils/pty/Cargo.toml': {'bytes': 860, 'sha256': '3333e26a50a65111ea1c961fa0eec59661196a88e1b2bf51ab647b8cc50ab08f', 'git_blob': '2a27ab72ea290862887abfc857c86efe6fad12c1'}, 'input/primary/original/justfile': {'bytes': 7838, 'sha256': '74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124', 'git_blob': 'a215a76cf407ace9715bca39c20497014e7dd4dc'}, 'input/primary/original/scripts/format.py': {'bytes': 16599, 'sha256': '8d93d7a6261bbe5f2b9fceea228154f0be29f721015d05b4f538c30076dd80b3', 'git_blob': 'd4eabe70b68605933240e9129245f7f4cccbde5d'}, 'input/primary/original/scripts/pyproject.toml': {'bytes': 177, 'sha256': '0b6799e50e7d0e58834615ccd885e23a78acd7b89f43f37b315cdb355cd05fc0', 'git_blob': '4340b6b78e83971e0032a7c90852f02791d3acbf'}, 'input/primary/original/scripts/uv.lock': {'bytes': 6220, 'sha256': '6b8e7a82d1a4f4c5d59ce57cf8be472ea031c6fb0a905506258d434132b3c99c', 'git_blob': '6c0c3bd0810badf5f901317b61d642d1dc84e026'}, 'input/r31-start/LOCAL-READBACK.json': {'bytes': 6536, 'sha256': '6817099cb5d8b752798dbc4bc2b7fdef431e574a0d8bdf8b61fe54d2bded9fb8', 'git_blob': 'ff14d5f2bb114045df4ef92aadc32e61a24e1d76'}, 'input/r31-start/controller/initial-stderr.log': {'bytes': 0, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'git_blob': 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'}, 'input/r31-start/controller/initial-stdout.log': {'bytes': 407, 'sha256': '93ad03048cf81ea51a6442e1f03077b40eb1d4628c3391fbb144ba6012664310', 'git_blob': '191f49594bb5ed9bd1f1a9421e9c6b423ceeebd7'}, 'input/r31-start/controller/launch-original.json': {'bytes': 1058, 'sha256': '90eb27fff124b1035577ea44ee327270bf3d9fd4c3a70e00446cb81bfa63b705', 'git_blob': '1e6c823a69296b0da1e45397e0a904fc09b15de0'}, 'input/r31-start/controller/launch_args-original.json': {'bytes': 296, 'sha256': 'ec846de9852a4503f91682a1301e1f5f12603bd381a7a65d1b99bcdb2b65a052', 'git_blob': '20dffb43ff1a267c18d7fd2174eb069473b72bb8'}, 'input/r31-start/controller/read-original.json': {'bytes': 1577, 'sha256': '02fbb9a816cd8aa1fd9a588c7081b3b3c5b7e067e43d39bd59dad96e9de3c8b0', 'git_blob': 'a03241d21a27a0280497d967e5e0aa4942e589a1'}, 'input/r31-start/controller/status-original.json': {'bytes': 471, 'sha256': '72cfd37b36ff27cb7e6e88492d6a88ea0f576501221cbb6c29e26ea1ff775e1f', 'git_blob': 'a7c8130f77b421b67ef890416c840dc060acff8e'}, 'input/r31-start/evidence/native-workspace-r31-environment.json': {'bytes': 1493, 'sha256': 'c95a310e566e1a5c8f3e0e9e9e5608c0484978e962a003ca46faa0ab4238f901', 'git_blob': 'bc1f578ebe22bf6367d955bac0dc4fa795c0a2ef'}, 'input/r31-start/evidence/native-workspace-r31-metadata-raw-process-result.json': {'bytes': 588, 'sha256': 'a2d7440520b8625bc3bbbdcc829d582247018f8abd3e25be1f9687ccabf795f8', 'git_blob': 'b3b6a5ade688a61379b7191e1e4e714f88653c42'}, 'input/r31-start/evidence/native-workspace-r31-metadata-receipt.json': {'bytes': 1401, 'sha256': 'ef6ce09448f4e22c5bb2450e45963e863cbe909de2151c6ebea3cb9bbb7f78b5', 'git_blob': '6cbc897c78f72811c15b731177c7be7439b14aa0'}, 'input/r31-start/evidence/native-workspace-r31-metadata-source-post-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5', 'git_blob': 'fa3b9dd96c693c690b97f346ddaeb79776b316e9'}, 'input/r31-start/evidence/native-workspace-r31-metadata-stderr.log': {'bytes': 0, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'git_blob': 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'}, 'input/r31-start/evidence/native-workspace-r31-preconditions.json': {'bytes': 45776, 'sha256': '2fe2bd1b8587a614616684281334847ee35aedfdb0193b0a745a032c8e3be58c', 'git_blob': '827685b80d380dbd707c043f39a96de2cc6e3040'}, 'input/r31-start/evidence/native-workspace-r31-source-pre-verification.json': {'bytes': 588, 'sha256': 'c2063342dd1ec7d4e8662c886448dbc83e8a8b2a4ab335a149ac409a6f13a3c5', 'git_blob': 'fa3b9dd96c693c690b97f346ddaeb79776b316e9'}, 'input/r31-start/transport/batch-original.json': {'bytes': 56518, 'sha256': '67e434b76533e0d13aa6c819144895700e6360c0b1ea1042079578ab10a5b50f', 'git_blob': 'b5806d1a779b83c6c8396ba99ffa7b2d1abd8e28'}, 'input/r31-start/transport/metadata_info-original.json': {'bytes': 479, 'sha256': 'a8a025faa53a79c17bb92caf942302fb0ca19cd6f3cac13a3b5e3057d207343e', 'git_blob': '884885adbea5f9b321a4de500bd97ac179d7c277'}, 'input/r31-start/transport/runner_info-original.json': {'bytes': 453, 'sha256': 'ce4ed1fb9e9b2b4851c10ce6c9ce48e323f3c9a784d1ba923d466f3f740977a3', 'git_blob': 'e143f6fb0197dcab3794596f33071189f2f2c6ac'}, 'input/r31-start/transport/scope_info-original.json': {'bytes': 474, 'sha256': '1bda630474415c7a7f778b07553c007ad300b88ee7c1b5552f10d97bb7b29868', 'git_blob': 'f03653d77f98dcdacefa91736b9b9f9a28c9645a'}, 'input/r31-start/transport/upload-original.json': {'bytes': 193, 'sha256': '5a1b63a8d5e6462959065dbc3ade88ad4b9fe966818f59a8e1b3fb9766400c10', 'git_blob': '9c3d5a76fced4abaea4a9de7191b2baa813a975d'}, 'input/source52-parent-manifest.json': {'bytes': 55209, 'sha256': '3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898', 'git_blob': 'f057b526bf2ba492d6bb5810222f69ac0cc3bdd2'}, 'input/unchanged-PRIMARY-SOURCE-PINS.json': {'bytes': 13098, 'sha256': 'afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3', 'git_blob': 'e8c6c477bba521b82c900a4545a6cf56f5591a07'}, 'references/PRODUCER-CONSUMER-FUNCTIONS.json': {'bytes': 16317, 'sha256': '3dd4b4b89eb510ca9efef4786d9aebe214508790cdda9cd42188c82dbe6170db', 'git_blob': 'cec5d6961895259a2795b5bbb26feea18b04134b'}, 'transport/scope-chunk-0-original.json': {'bytes': 87709, 'sha256': '41d7a092383b1f3cfe0bf8b44cd0b698fd5a3c1a6b0690b1985f6c863b51159a', 'git_blob': '442249c2d21afa74c31f15fe045f9d5e74850845'}, 'transport/scope-chunk-1-original.json': {'bytes': 37516, 'sha256': '59cda86170a8bdc9ec256a620817a576b022747c9a8176d8a0896b201a4f424e', 'git_blob': 'ea79116409984f698a3fb25b368384643d722d88'}, 'transport/scope-file-info-original.json': {'bytes': 474, 'sha256': '1bda630474415c7a7f778b07553c007ad300b88ee7c1b5552f10d97bb7b29868', 'git_blob': 'f03653d77f98dcdacefa91736b9b9f9a28c9645a'}, 'TRANSFER-READBACK.json': {'bytes': 3282, 'sha256': '51d60be7dd73a3004c9ae00781b8298e72db97dfb3c12580c777e8b0c6784fe2', 'git_blob': '1de21a4581f6f9b4451410da42d1b1bd5fbf7e53'}}

HERE = Path(__file__).resolve().parent
T = PurePosixPath("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
CARGO_SHA = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_SHA = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
META_COMMAND = ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
WORKSPACE_COMMAND = ["just", "test", "--locked", "--retries", "0"]
PREFIX = "native-workspace-r31"
OWNER_NAMES = sorted([
    "codex-app-server", "codex-app-server-client", "codex-cli", "codex-core", "codex-exec-server",
    "codex-external-agent-migration", "codex-hepta-agent-protocol", "codex-hepta-agentd",
    "codex-hepta-automation", "codex-hepta-context-compiler", "codex-hepta-infer-worker-host",
    "codex-hepta-intelligence", "codex-hepta-learning-artifacts", "codex-hepta-memory",
    "codex-hepta-memory-extension", "codex-hepta-neuron", "codex-hepta-plasticity",
    "codex-hepta-runtime", "codex-hepta-supervisor", "codex-linux-sandbox", "codex-mcp",
    "codex-model-provider-info", "codex-network-proxy", "codex-shell-escalation", "codex-utils-pty",
    "core_test_support",
])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(name):
    require(name in INPUT_PINS, "unbound input: " + name)
    path = HERE / name
    require(path.is_file() and not path.is_symlink(), "not a regular input: " + name)
    raw = path.read_bytes()
    require(pin(raw) == INPUT_PINS[name], "input bytes changed: " + name)
    return raw


def load(name):
    return json.loads(read(name))


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()


def write(name, raw):
    with (HERE / name).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": name, **pin(raw)}


def record_pin(name, raw):
    return {"path": name, **pin(raw)}


def source_identity(value):
    require(value["source_commit"] == COMMIT and value["source_tree"] == TREE, "source identity differs")


def guard(value):
    require(value["source_commit"] == COMMIT and value["expected_tree"] == value["actual_tree"] == TREE,
            "source guard identity differs")
    require(value["pass"] is True and value["changed_file_count"] == 197 and value["native_head"] == HEAD,
            "source guard count/HEAD/failure")
    require(value["changed_path_set_matches"] is True and value["unstaged_paths"] == []
            and value["untracked_paths"] == [] and value["file_mismatches"] == [], "source guard mismatch")
    require(value["cargo_lock_sha256"] == CARGO_SHA and value["bazel_lock_sha256"] == BAZEL_SHA,
            "source guard dual locks differ")


def verify_fresh_metadata(source_raw):
    root = "input/r31-start/"
    evidence = root + "evidence/" + PREFIX
    metadata_raw = gzip.decompress(read("input/native-workspace-r31-metadata.json.gz"))
    metadata = json.loads(metadata_raw)
    scope_raw = read("input/native-workspace-r31-scope.json")
    scope = json.loads(scope_raw)
    raw_bytes = read(evidence + "-metadata-raw-process-result.json")
    post_bytes = read(evidence + "-metadata-source-post-verification.json")
    receipt_bytes = read(evidence + "-metadata-receipt.json")
    stderr = read(evidence + "-metadata-stderr.log")
    raw, post, receipt = map(json.loads, (raw_bytes, post_bytes, receipt_bytes))
    environment = load(evidence + "-environment.json")
    pre = load(evidence + "-preconditions.json")
    pre_bytes = read(evidence + "-source-pre-verification.json")
    initial_guard = json.loads(pre_bytes)
    for item in (receipt, raw, environment, pre, scope):
        source_identity(item)
    guard(post)
    guard(initial_guard)
    require(raw["schema"] == "hepta.native-raw-process-result.v1" and raw["phase"] == "workspace-metadata",
            "unexpected metadata raw schema/phase")
    require(receipt["schema"] == "hepta.native-metadata-receipt.v1", "unexpected metadata receipt")
    for item in (raw, receipt):
        require(item["command"] == META_COMMAND and item["cwd"] == str(S / "codex-rs")
                and item["exit_code"] == 0, "actual metadata invocation failed or differs")
    require(raw["start_unix"] == receipt["start_unix"] and raw["end_unix"] == receipt["end_unix"]
            and receipt["elapsed_seconds"] == raw["end_unix"] - raw["start_unix"], "metadata times differ")
    require(receipt["raw_process_result"] == record_pin(PREFIX + "-metadata-raw-process-result.json", raw_bytes)
            and receipt["source_postguard"] == record_pin(PREFIX + "-metadata-source-post-verification.json", post_bytes)
            and receipt["source_guards_pass"] is True, "receipt does not bind raw/postguard")
    require(receipt["stdout"] == pin(metadata_raw) and receipt["stderr"] == pin(stderr) and stderr == b"",
            "metadata stdout/stderr differs")
    require(raw["resources_not_collected_for_read_only_metadata"] is True,
            "metadata must not fabricate a time/resource receipt")
    require(pre["actual_changed_file_count"] == 197
            and pre["source_manifest"] == record_pin("native-candidate-r30-source.json", source_raw)
            and pre["initial_source_guard"] == record_pin(PREFIX + "-source-pre-verification.json", pre_bytes),
            "current preconditions do not bind source/guard")
    require(pre["workspace_test_command"] == WORKSPACE_COMMAND and pre["fix_fmt_executed"] is False
            and pre["historical_project_pass_substitutes_for_r30"] is False
            and pre["diagnostic_only"] is True and pre["behavior_repair_claimed"] is False,
            "precondition scope/diagnostic boundary changed")
    require(environment["source_manifest_sha256"] == pin(source_raw)["sha256"]
            and environment["fresh_current_source_metadata_required"] is True
            and environment["original_default_workspace_selection"] is True,
            "environment current source differs")

    mi = load(root + "transport/metadata_info-original.json")
    si = load(root + "transport/scope_info-original.json")
    for info, payload, name in ((mi, metadata_raw, "metadata"), (si, scope_raw, "scope")):
        require(info["path"] == str(T / "evidence" / (PREFIX + "-" + name + ".json"))
                and info["size"] == len(payload) and info["sha256"] == pin(payload)["sha256"]
                and bool(info["version"]), "actual native file_info mismatch: " + name)
    require(load("transport/scope-file-info-original.json") == si, "scope pinned version changed")
    transfer = load("TRANSFER-READBACK.json")
    require(transfer["scope_file_info"] == si and transfer["metadata_fresh_file_info"] == mi
            and transfer["metadata_uncompressed"] == pin(metadata_raw)
            and transfer["metadata_new_native_invocation_preserved"] is True
            and transfer["metadata_byte_cache_reuse_only"] is True
            and transfer["old_r29_invocation_not_relabelled"] is True, "transfer provenance differs")

    auth = load("input/ROOT-R31-EXECUTION-AUTHORIZATION.json")
    source_identity(auth)
    require(auth["fresh_current_metadata_command"] == META_COMMAND
            and auth["workspace_command"] == WORKSPACE_COMMAND and auth["fix_fmt_authorized"] is False,
            "root authorization differs")
    launch = load(root + "controller/launch-original.json")
    job = launch["job"]
    require(job["id"] == R31_JOB_ID and job["host"] == "pocket4"
            and job["idempotency_key"] == auth["unique_launch_key"]
            and job["executable"] == "/usr/bin/python3" and job["args"] == [auth["runner"]["native_path"]]
            and job["cwd"] == str(T) and launch["launch"]["ok"] is True,
            "actual launch does not match root authorization")
    runner_info = load(root + "transport/runner_info-original.json")
    require(runner_info["path"] == auth["runner"]["native_path"]
            and runner_info["size"] == auth["runner"]["bytes"]
            and runner_info["sha256"] == auth["runner"]["sha256"], "actual runner file_info differs")
    require(raw["start_unix"] * 1000 >= job["created_unix_ms"], "metadata predates current job")

    packages = {row["id"]: row for row in metadata["packages"]}
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    require(len(packages) == len(metadata["packages"]) == len(members) == len(defaults) == 193
            and len(set(members)) == len(set(defaults)) == 193 and set(packages) == set(members) == set(defaults),
            "actual 193 member/default identity set differs")
    expected_scope = {
        "schema": "hepta.source53-current-default-workspace-scope.v1", "source_tree": TREE, "source_commit": COMMIT,
        "metadata_command": META_COMMAND, "metadata": record_pin(PREFIX + "-metadata.json", metadata_raw),
        "metadata_generated_on_current_source": True, "old_metadata_reused_as_current": False,
        "workspace_root": metadata["workspace_root"], "target_directory": metadata["target_directory"],
        "workspace_member_count": 193, "workspace_default_member_count": 193,
        "workspace_members": [{"id": pid, "name": packages[pid]["name"], "manifest_path": packages[pid]["manifest_path"]} for pid in members],
        "workspace_default_members": [{"id": pid, "name": packages[pid]["name"]} for pid in defaults],
        "command": WORKSPACE_COMMAND, "features": "unchanged_defaults", "filters": "no_additions",
        "all_platforms_features_external_services_qualified": False, "diagnostic_only": True,
        "behavior_repair_claimed": False,
    }
    require(scope == expected_scope, "scope does not exactly match actual metadata producer, including original ordering")
    require(metadata["workspace_root"] == str(S / "codex-rs") and metadata["target_directory"] == str(T / "target"),
            "actual metadata paths differ")
    return metadata, metadata_raw, {"job_id": R31_JOB_ID, "metadata_exit_code": 0,
        "metadata_elapsed_seconds": receipt["elapsed_seconds"], "metadata": pin(metadata_raw),
        "scope": pin(scope_raw), "metadata_file_info": mi, "scope_file_info": si,
        "new_native_invocation_verified": True, "local_bytes_reused_from_equal_hash_cache": True,
        "workspace_terminal_status": None, "workspace_pass_claimed": False,
        "fix_fmt_authorized": False, "all_other_gate_claims_excluded": True}


def main():
    require(__debug__, "optimized Python is not allowed")
    require(FROZEN is True and R31_JOB_ID is not None and INPUT_PINS is not None,
            "inert template: actual closed input bindings are required")
    for name in INPUT_PINS:
        read(name)
    source_raw = read("input/native-candidate-r30-source.json")
    source = json.loads(source_raw)
    source_identity(source)
    rows = {row["path"]: row for row in source["changed_files"]}
    require(len(rows) == len(source["changed_files"]) == 197, "source row count or duplicate")
    require(source["cargo_lock_sha256"] == CARGO_SHA and source["bazel_lock_sha256"] == BAZEL_SHA,
            "manifest dual locks differ")
    previous = load("input/source52-parent-manifest.json")
    previous_rows = {row["path"]: row for row in previous["changed_files"]}
    require(len(previous_rows) == 195 and all(rows[path] == row for path, row in previous_rows.items()),
            "original 195 rows changed")
    require(set(rows) - set(previous_rows) == {
        "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
        "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"}, "source53 addition differs")
    metadata, metadata_raw, invocation = verify_fresh_metadata(source_raw)
    paths = sorted(rows)
    rust_paths = [path for path in paths if path.endswith(".rs")]
    require(len(rust_paths) == 183, "Rust count differs")
    python_paths = ["./" + path for path in paths if path.startswith(("scripts/", ".github/")) and path.endswith((".py", ".pyi"))]
    require(python_paths == ["./scripts/run-nextest.py", "./scripts/test_run_nextest_helpers.py"], "Python selection differs")
    require(not any(PurePosixPath(path).name in {"rustfmt.toml", ".rustfmt.toml", "pyproject.toml", "ruff.toml", ".ruff.toml"} for path in paths),
            "formatter configuration changed")
    require("justfile" not in rows and not any(
        PurePosixPath(path).name in {"BUILD", "WORKSPACE", "MODULE.bazel"}
        or PurePosixPath(path).name.startswith(("BUILD.", "WORKSPACE."))
        or path.endswith((".BUILD.bazel", ".MODULE.bazel", ".bzl", ".sky"))
        or ".bzl." in PurePosixPath(path).name or ".sky." in PurePosixPath(path).name for path in paths),
        "another default formatter group is selected")
    roots = {}
    defaults = set(metadata["workspace_default_members"])
    for package in metadata["packages"]:
        manifest = PurePosixPath(package["manifest_path"]).relative_to(S).as_posix()
        directory = PurePosixPath(manifest).parent.as_posix()
        require(directory not in roots and manifest.endswith("/Cargo.toml"), "ambiguous owning package")
        roots[directory] = {"package": package["name"], "package_id": package["id"],
            "package_directory": directory, "manifest_path": manifest, "edition": package["edition"],
            "default_workspace_member": package["id"] in defaults}
    owners = {}
    for path in rust_paths:
        matches = [root for root in roots if path.startswith(root + "/")]
        require(bool(matches), "missing owner: " + path)
        root = max(matches, key=lambda value: len(PurePosixPath(value).parts))
        package = roots[root]
        entry = owners.setdefault(package["package"], {**package, "rust_paths": []})
        require(entry["package_directory"] == root, "owner name collision")
        entry["rust_paths"].append(path)
    require(sorted(owners) == OWNER_NAMES and len(owners) == 26, "owner set differs")
    primary_raw = read("input/unchanged-PRIMARY-SOURCE-PINS.json")
    require(len(primary_raw) == 13098 and pin(primary_raw)["sha256"] == "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3",
            "primary source pin bytes changed")
    primary = json.loads(primary_raw)
    primary_by_path = {row["path"][len("original/"):]: row for row in primary}
    require(len(primary) == len(primary_by_path) == 34, "primary pin cardinality differs")
    for path, row in primary_by_path.items():
        actual = read("input/primary/original/" + path)
        require(pin(actual) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "primary input changed: " + path)
        if path in rows:
            require(pin(actual) == {key: rows[path][key] for key in ("bytes", "sha256", "git_blob")},
                    "primary input does not match current changed manifest: " + path)
    workspace_toml = tomllib.loads(read("input/primary/original/codex-rs/Cargo.toml").decode())
    for owner in owners.values():
        owner["rust_path_count"] = len(owner["rust_paths"])
        require(owner["edition"] == "2024" and owner["default_workspace_member"] is True,
                "owner edition/default scope differs")
        require(owner["manifest_path"] in primary_by_path, "owner not explicitly pinned")
        cargo = tomllib.loads(read("input/primary/original/" + owner["manifest_path"]).decode())
        require(cargo["package"]["name"] == owner["package"], "owner name differs from original TOML")
        edition = cargo["package"]["edition"]
        if isinstance(edition, dict):
            require(edition == {"workspace": True}, "unsupported inherited edition")
            edition = workspace_toml["workspace"]["package"]["edition"]
        require(str(edition) == owner["edition"], "original TOML edition differs from fresh metadata")
    workflow = read("input/hepta-cell-framework-native.yml")
    require(pin(workflow) == {key: rows[".github/workflows/hepta-cell-framework-native.yml"][key] for key in ("bytes", "sha256", "git_blob")},
            "workflow differs from source53")
    selectors = re.findall(r"(?<!\S)-p\s+([A-Za-z0-9_-]+)", workflow.decode())
    require(len(selectors) == len(set(selectors)) == 27
            and set(selectors) == set(owners) | {"codex-hepta-control-plane"}, "actual CI selector scope differs")
    formatter = read("input/primary/original/scripts/format.py").decode()
    functions = {node.name: ast.get_source_segment(formatter, node) for node in ast.parse(formatter).body if isinstance(node, ast.FunctionDef)}
    require('revision = "HEAD"' in functions["changed_paths"]
            and '"--no-renames"' in functions["changed_paths"] and '"--diff-filter=ACDMRT"' in functions["changed_paths"]
            and 'changed_paths(args.base)' in functions["main"], "original default formatter algorithm changed")
    require('imports_granularity=Item,skip_children=true' in functions["rust_file_command"]
            and '"uv"' in functions["python_scripts_formatter_group"]
            and '"--frozen"' in functions["python_scripts_formatter_group"], "formatter commands changed")
    justfile = read("input/primary/original/justfile").decode()
    require('fix *args:\n    cargo clippy --fix --tests --allow-dirty {args}' in justfile
            and 'fmt *args:\n    @{{ python }} ../scripts/format.py {args}' in justfile,
            "original just recipes changed")

    names = sorted(owners)
    args = [value for name in names for value in ("-p", name)]
    source_pin = record_pin("input/native-candidate-r30-source.json", source_raw)
    proposed = {"schema": "hepta.source53-final-fix-packages.v1",
        "status": "SCOPE_PREPARATION_ONLY_SAME_SOURCE_R31_TERMINAL_AND_TOOL_INVENTORY_PENDING",
        "source_commit": COMMIT, "source_tree": TREE, "source_manifest": source_pin,
        "fresh_metadata": pin(metadata_raw), "owners": names, "package_args": args,
        "command": ["just", "fix", "--locked", *args],
        "recipe_expansion": ["cargo", "clippy", "--fix", "--tests", "--allow-dirty", "--locked", *args],
        "cwd": str(S / "codex-rs"), "fix_executed": False, "same_source_workspace_pass_bound": False,
        "diagnostic_only": True, "behavior_repair_claimed": False}
    expected = {"schema": "hepta.source53-final-formatter-selection.v1", "status": "NOT_EXECUTED_PREPARATION_ONLY",
        "source_commit": COMMIT, "source_tree": TREE, "native_HEAD": HEAD,
        "native_created_commit_checkout_claimed": False, "source_manifest": source_pin,
        "changed_path_count": 197, "changed_paths": paths, "rust_count": 183, "rust_paths": rust_paths,
        "python_count": 2, "python_paths": python_paths, "formatting_configuration_changed_paths": [],
        "owner_count": 26, "owners": [owners[name] for name in names], "ci_selector_count": 27,
        "ci_selectors": selectors, "extra_ci_only_owner": ["codex-hepta-control-plane"],
        "workspace_members": 193, "workspace_default_members": 193,
        "fresh_source53_r31_metadata_verified": True, "default_formatter_command": ["just", "fmt"],
        "all_flag_used": False, "python_formatter_command": ["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", *python_paths],
        "unselected_by_default_formatter": sorted(set(paths) - set(rust_paths) - {path[2:] for path in python_paths}),
        "final_scope_execution_authorized": False, "post_fix_selection_must_be_revalidated_before_fmt": True,
        "unexpected_scope_or_dependency_change_requires_stop_without_reset_or_test_rerun": True,
        "workspace_result": None, "diagnostic_only": True, "behavior_repair_claimed": False}
    commands = []
    for path in rust_paths:
        owner = next(row for row in owners.values() if path in row["rust_paths"])
        commands.append({"path": path, "owning_package": owner["package"], "manifest_path": owner["manifest_path"],
            "cwd": str(S / owner["package_directory"]), "command": ["rustfmt", "--edition", "2024", "--config",
                "imports_granularity=Item,skip_children=true", "--", str(S / path)]})
    require(len(expected["unselected_by_default_formatter"]) == 12 and len(commands) == 183, "remaining formatter counts differ")
    artifacts = {"EXPECTED-SELECTION.json": encode(expected), "PACKAGE-ARGS.json": encode(proposed),
                 "RUST-FILE-COMMANDS.json": encode(commands), "PRIMARY-SOURCE-PINS.json": primary_raw}
    require(not any((HERE / name).exists() for name in [*artifacts, "READ-ONLY-AUDIT.json"]), "create-only outputs already exist")
    outputs = [write(name, data) for name, data in artifacts.items()]
    report = {"schema": "hepta.source53-fresh-r31-final-scope-readback.v1",
        "result": "READ_ONLY_SCOPE_CLEAR_NOT_EXECUTION_AUTHORIZATION", "source_commit": COMMIT, "source_tree": TREE,
        "counts": {"changed": 197, "rust": 183, "other": 14, "python_formatter": 2, "owners": 26, "ci_selectors": 27,
                   "workspace_members": 193, "workspace_default_members": 193, "unselected_default_formatter": 12},
        "fresh_invocation": invocation, "outputs": outputs, "primary_source_pin_bytes_unchanged": True,
        "owner_algorithm": "Longest Cargo manifest parent from actual fresh R31 metadata; exact original TOML edition readback.",
        "formatter_algorithm": "Unchanged format.py default HEAD selection, no config widening; 183 Rust and 2 Python scripts.",
        "native_HEAD": HEAD, "HEAD_changed": False, "created_commit_checkout_claimed": False,
        "consumer": "source53-finalize-preparation/native-finalize-source53-template.py",
        "consumer_sha256": "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d",
        "consumer_not_imported_or_executed": True, "source_manifest_historical_fields_preserved": True,
        "workspace_terminal_status": None, "workspace_result": None, "workspace_PASS_claimed": False,
        "fresh_tool_inventory_bound": False, "fix_executed": False, "fmt_executed": False,
        "native_or_cargo_or_rust_commands_executed_by_generator": False,
        "required_before_finalizer": "Actual complete same-source R31 PASS and R30 PASS with independent source guards, fresh tool inventory, explicit finalizer authorization; recheck default HEAD selection before fmt.",
        "diagnostic_only": True, "behavior_repair_claimed": False}
    audit = write("READ-ONLY-AUDIT.json", encode(report))
    print(json.dumps({"audit": audit, "outputs": outputs, "counts": report["counts"]}))


if __name__ == "__main__":
    main()
