#!/usr/bin/env python3
"""Verify exact archived bytes before excluding them from spelling checks.

This grants no execution or scientific qualification to the preserved sources.
The CI workflow validates again after Codespell to detect worktree drift.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

MANIFEST = ".github/codespell-custody.json"
SCHEMA = "hepta.codespell-custody.v1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
BINARY_ARCHIVE_PATHS = frozenset(
    {
        "qualification/memory-cell-mem6/run-001/raw-transfer/"
        "complete-20261111-ed353/missing-000049879392.part",
        "qualification/memory-cell-mem6/run-001/raw-transfer/"
        "complete-20261111-ed353/missing-000046379392.part",
        "qa/repository-consolidation/20261118/round-03/evidence.tar.gz.part-0004",
        "qa/repository-consolidation/20261118/round-03/evidence.tar.gz.part-0009",
        "qa/repository-consolidation/20261118/round-03/evidence.tar.gz.part-0020",
    }
)

# These retained qualification inputs admit only their registered original bytes.
QUALIFICATION_SOURCE_SHA256 = {
    # The archived GPU pilot embeds opaque base64 checkpoint bytes.
    "qualification/hcsn_research_20261127/feedback/rog_pilot.json": (
        "d17b48c0d9c227fffb32000ae2284df652027a69b20cd4af06ed721bb3af4141"
    ),
    # Preserve the original HCSN CI diagnosis and the three transport-v2 shards
    # reported by Codespell 2.4.3. Only these exact bytes receive spelling custody.
    (
        "qualification/hcsn_adaptive/evidence/20261120-1d88/CI_FOLLOWUP.md"
    ): "a1fd4746646cb21d3e287efa0c01716affc61b05a430acd2dc8c7959517885a3",
    (
        "qualification/hcsn_adaptive/evidence/20261120-1d88/"
        "ci-followup-v1.tar.gz.part-02"
    ): "ef91bc155c41c5d657fa7f1d9ea112566e2cb0319613fac066b3c3fdef483a7f",
    (
        "qualification/hcsn_adaptive/evidence/20261120-1d88/"
        "runtime-evidence-v1.tar.gz.part-04"
    ): "beea6be67039d7f1c7638089a6afe19f14d3930e07909b51048e9a311aa8a9e4",
    (
        "qualification/hcsn_adaptive/evidence/20261120-1d88/"
        "runtime-evidence-v1.tar.gz.part-06"
    ): "7ce22734110efe605c385e46c41496cb02594455d2afbfe2fdde7f08703a7e74",
    (
        "qualification/hcsn_differentiable/evidence/p0p5-20261110/review/"
        "baseline36-c1-native-v1/v2/bootstrap/"
        "6e1c204a063b39f1fff14c405c09d153fe3ca57f.json"
    ): "1511fe97bec17637deef2dd336b97f8bb04dbc6421708d55909896e9f6bba6e6",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-ci-launch-closure-20261110/codespell-fix/original-red.stdout"
    ): "bb3963bb62ee320e71703f057b98c1e71ceae250421f0b076e838ed7704ddd13",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-persistence-validation-20261111/native-first/COMMAND.sh"
    ): "21487e097fbdef884fe979b8a2fcdfc59ebeed79fcc42fefea21f45e10135607",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-persistence-validation-20261111/native-first/LAUNCH-RECEIPT.json"
    ): "a8e1c389662c60f512127826f927aba894793721276f62445ffa8746c58cac32",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-terminal-numerics-20261110/numerical-audit/collector-launch/"
        "git-response.json"
    ): "7aa48d5cc91d125540591b852b64ec4255e8a4002b5c890d18d515bb9a6c4121",
    "qualification/hcsn_initial_vjp/evidence/native001/COMMAND.sh": "79d8d7bec29c774aeb094eb2ccceb02a5d6b44ebc1a239b33f26500758260945",
    (
        "qualification/hcsn_joint_dde/evidence/all-visits-attempt002/"
        "review_visited_l8_raw.py"
    ): "d2397d0b3e2dfaea8f32e7ec12a580650131dc428ac4d6a117110045489d1450",
    # Frozen source inputs and observations reviewed in the ordinary-branch
    # consolidation. These pins grant spelling custody only; changed source
    # bytes, neighboring paths and execution qualification are not exempt.
    (
        "AUDIT/2026-10-20-agent-continuation/p1_p4_audit/canonical_owner_dag.json"
    ): "b6f2fb819ce728e58bfb309e17746ec57d635e11eca5341ea8265eec7f4a4971",
    (
        "AUDIT/2026-10-20-agent-continuation/p5_inventory/REPORT.md"
    ): "4476a5e915aba756c46052ec10626cb8dac3d28b4be5324a8377327ec4db8f85",
    (
        "AUDIT/2026-10-20-agent-continuation/p5_inventory/organ/source/libs/os-control/"
        "API_CONTRACT.md"
    ): "68689e929de4a7709d7107a2991704e3c6e268d5855d48962c290f2acc0d0f54",
    (
        "experiments/hcsn_free_boundary_v1/data/FSDD_UPSTREAM_README.md"
    ): "eb948c7b23e0c77bb82ce34d692e7f132aa4dfd4abcdb22013fcb73bb49dc55a",
    (
        "qa/repository-consolidation/20261119/round-02/rust-conflict-decisions.json"
    ): "28d1905aeacdaf0403c9231c171a48a3377827a063ede3a88dae8522ff073f94",
    (
        "qa/repository-consolidation/20261119/round-07-75cf/evidence/joint-h3-review/"
        "protected-composition/clusters-composition.json"
    ): "cc97cf47f751f39c02445505170468d234a0fd5b615fe9e0f5c6eb545fe589f5",
    (
        "qa/repository-consolidation/20261119/round-07-75cf/evidence/joint-h3-review/"
        "protected-composition/clusters-conflict-regions.json"
    ): "9e13cda7f8feb0d5a2c906305ac80d6ec8c8a34a927c12342ec4ddcdbe55ff07",
    (
        "qa/repository-consolidation/20261119/round-07-75cf/evidence/root-review/"
        "remote-five-commit-deltas.json"
    ): "b791017524abeace5ed6c5151398dde77a7c454376ad0a81a90152fc4535c6a6",
    (
        "qa/repository-consolidation/20261119/windows-c52-cmd-entry-7246/"
        "codespell-baseline-comparison.json"
    ): "3aa784685450876595489e7cbd80a6a1427c097b4e09d97a7d73bccf1b44d7b5",
    (
        "qa/repository-consolidation/20261119/windows-c52-cmd-entry-7246/"
        "root-source-review.json"
    ): "5cf0439b71255c31fc5dd9dda9e36e56dcd2211f73e26a7fd8824bba0f1d12e8",
    (
        "qualification/continuation-20261021/inventory/OWNER_CANDIDATES.json"
    ): "58d6c1173770ed5934eb3eb42d507fdc3302bb565b7657854fd0588a5bf3d1cf",
    (
        "qualification/continuation-20261021/inventory/pull_requests/part-012.json"
    ): "34f1ed0bfb0db415aa512446d24f7c1c055c9ec542824ad1541540105b650795",
    (
        "qualification/continuation-20261021/os/pull_requests.json"
    ): "7e4900244f8e2538f4da3a52791dc17f433f3feac7c7adeefeaede2d60c6fe34",
    (
        "qualification/ctrl-metacontrol-20261109/DEPENDENCY_SYN_REPAIR.md"
    ): "b0d8156d670e0d86f78ef1791cbcf25f78a24fc8099cd1228bffec713202dcb7",
    (
        "qualification/joint-generation/color-spatial-source-training/PLAN.md"
    ): "ebdd572dcfc4bf779b89ed145855f9cf96085f30ab8b743991eb2cd7d14a81f0",
    (
        "qualification/joint-generation/color-spatial-source/PLAN.md"
    ): "e1aadd63f99c4d5a9c41b6918c4795d72d1d0dcc0d5136ebc2dbb524f507bd1f",
    (
        "qualification/joint-generation/coupled-prefix-numerics/PLAN.md"
    ): "57ec642f5424e22bec1a3be25c8a9d7deac1479cd101b37e93edd11bbb4a4611",
    (
        "qualification/joint-generation/coupling-reward-consistency/PLAN.md"
    ): "2002c38e837925b2213f604784fe366cb5556122c835a8fa0d9bd60445b77225",
    (
        "qualification/joint-generation/coupling-reward-consistency/PROOF.md"
    ): "2e7cf5e4dde8372b7f1f26f5724ea667bb79305298b8035693fdc741f1d7ffc3",
    (
        "qualification/joint-generation/coupling-reward-consistency/RUN_PLAN.md"
    ): "f40ced6955662f66c6e54c263a23e5d9f25e4ff0f171065a3100d65365412948",
    (
        "qualification/joint-generation/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/fixed-temperature-chain/PLAN.md"
    ): "96650b2b06513095f16217e3c19162052debc31c2b19f9fbad1c2ea15d3e953f",
    (
        "qualification/joint-generation/fixed-temperature-fit-direction/PLAN.md"
    ): "6f5725ddb84cd62d2d80c53abc46ee21f94d0fc12ce5505abbd9f60b017ed89d",
    (
        "qualification/joint-generation/fresh-fit-view-training/fresh_views.py"
    ): "d2f7aa4b5567b88fd5f34daa56d1bb3057168542d8745e924bb0957dbd3ae0ca",
    (
        "qualification/joint-generation/historical-session-reference-v1/"
        "content-shared-lease-publication-assessment-v1/runtime/fashion_research/"
        "model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/independent-fit-calibration-view/PLAN.md"
    ): "b20eaee8682568f6f5cfd53c68d4454e4b16b7cb66ad80635b311c5116131a6f",
    (
        "qualification/joint-generation/joint-policy-live-context-source-release-v1/"
        "runtime/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-policy-replay-receipt-source-release-v1/"
        "runtime/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-active-channel-fault-candidate-v1/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-deferred-deadline-candidate-v1/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-delivery-candidate-v2/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-live-control-candidate-v1/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-output-budget-outcome-candidate-v2/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/joint-product-six-capsule-candidate-v1/files/"
        "joint-policy-reconnect-candidate-v1/fashion_research/model.py"
    ): "503180f85d37ce39c735489cd08c7cf7b734480dcfe6b8e4852543f63291831f",
    (
        "qualification/joint-generation/ndu_training/fashion_controls/bound/model.py"
    ): "a81dc4f3d10533333c18bc3239febcf08095a53f0b0f1d596ffde3bae7702c53",
    (
        "qualification/joint-generation/research/fashion-mnist-candidate-20261023/"
        "plan.json"
    ): "3b022e38985a89cf4855b0717053724f4a6cdc08932903a145bd9945c0907ea1",
    (
        "qualification/joint-generation/runs/"
        "accounting-cache-development-diagnostic-20261023-c1/worker.py"
    ): "c61e82e3b37d17ff84ab07f3605b1655313c553d5fc576de4db318f9d423dd19",
    (
        "qualification/joint-generation/semantic-temperature-replication/PLAN.md"
    ): "4b54e16b095e429f09397444cbd24d6a4206a4c5dfd139ede9b9a697c24317e3",
    (
        "qualification/joint-generation/semantic-temperature/PLAN.md"
    ): "b9bd429e575f856c636445ff3fe45a8ad2ce1b358b4881c49a52c3c02653db05",
    (
        "qualification/joint-generation/semantic-temperature/RUN_PLAN.md"
    ): "16fa4221626edaeaa55f6842580b48b995fe2b52d4899da1dc36c6d4e67b1aeb",
    (
        "qualification/joint-generation/source-supervision-posthoc/decompose.py"
    ): "3d6918539af5d48091681a7bcb8101929f1c5e981e173d0e8e2dc1f469353249",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/root-readback/"
        "mem-envelope-1.json"
    ): "85bf51c1d57a06acfab134444764018ab48c3a3d5b1c3250759798dffe1a69d8",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/root-readback/"
        "mem-envelope-2.json"
    ): "167a4e21ec90c0e4eca7df8e1883937afb8316d910f416ed0999225ef102c469",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/root-readback/"
        "mem-envelope-3.json"
    ): "ae3eb322cb68bfda0b27177d70e9c9abec2cfa877828ed6aefdf43de8b694deb",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/root-readback/"
        "mem-envelope-4.json"
    ): "e1dcd8902bc6f79eec597ff419dccdb5f2e3246d11d29f319c61b7abf8eece5a",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/root-readback/"
        "mem-envelope-5.json"
    ): "b758498884d2633f93cfd0c3db8a8664eb1ebb88dffbe4dadffe147f09dfee67",
    (
        "qualification/memory-cell-mem8-ci-followup/v17/blocking-d0f-recovered/raw/"
        "job-130668671376.log.utf8.part-005"
    ): "05cb0e4d3e850f67e8a5989ae431f3fec7322aabdbd279cdc1d80b80dbcad077",
    (
        "qualification/memory-cell-mem8-ci-followup/v17/windows-current-c895/"
        "verify_original.py"
    ): "448170083601485e5721f0e79f8d50f72e0758709f4dfbaff0992aaae98039fe",
    (
        "qualification/memory-cell-mem8-ci-followup/v17/windows-current-d0f/"
        "verify_original.py"
    ): "e141e5bccfba7a66602a548585d69cce4f8df34816a09c285931cf5625b54550",
    (
        "qualification/neuron-learning-closure-v13/evidence/20261106-cpu/real-campaign/"
        "cold-readback.stdout.json"
    ): "431999ab204a8279a66c1a736b1b9b627bdeaf577aca2cdbed02b7d6e0eb9202",
    (
        "experiments/hcsn_distributional_v2/artifacts/content002_runs_004.tar.xz.par"
        "t0018"
    ): "40a50fae4c000c2627b4a5dd912848b7b6ed386c25318d8eda6cfd1fd69a0a42",
    (
        "experiments/hcsn_distributional_v2/artifacts/lif_supplement001_evidence.tar"
        ".xz.part0008"
    ): "c3ede18d48e2434d05ef7d0234327328d0cbdde2dbdf0617b7886132a36202e5",
    (
        "experiments/hcsn_distributional_v2/artifacts/lif_supplement001_evidence.tar"
        ".xz.part0015"
    ): "1dcc999c959f6231bb930357655fe2b4ab25a94bc99fd0ac763f560984e38000",
    (
        "experiments/hcsn_distributional_v2/artifacts/lif_supplement001_evidence.tar"
        ".xz.part0020"
    ): "b20801d5f2fda0d7af03b93ea8bead7e7374b63edf015a4b88daca8617868619",
    (
        "experiments/hcsn_distributional_v2/results/figures002/task_reward_and_cost.pdf"
    ): "effb4d192e6fa3deebc248b1cac7cda305bbace9091d8be6a76edcdfa489ead9",
    (
        "experiments/hcsn_free_boundary_v1/artifacts/auxiliary_evidence.tar.xz.part0009"
    ): "7b965e11dd34e8792342a5f36434c68f0705d2ab9e29e2a9f31ce9dff86994af",
    (
        "experiments/hcsn_free_boundary_v1/artifacts/original_data.tar.xz.part0009"
    ): "1f9b4bff6174ccab1f63669118f11bdd217ed36e2c842c2994156426d9646504",
    (
        "experiments/hcsn_p2_memory/TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json."
        "gz.b64"
    ): "5f3ea3afaa9f29a6af5237effce8ab13f157da4edf1bc07ccf1df5cc02a39153",
    (
        "qualification/hcsn_c2_continuation_20261119/evidence/archive-parts/archive."
        "part0026"
    ): "6eab7cabf891459bafa29cdc79cf842dc966cb29a56c33504ba47cce6a1e14a6",
    (
        "qualification/hcsn_currentstate_n128_secondcycle_cold/evidence/source-7883e"
        "ac/attempt001/originals.zip.part013"
    ): "7a0ee26be69321eb861e842a2cd1e414b32f4d578148a49f8012c0052697f8fa",
    (
        "qualification/hcsn_currentstate_n128_secondcycle_warm/evidence/source-1bf14"
        "20/attempt001/originals.zip.part003"
    ): "1fbdc7a4093d2c98ddc1f21d63131c701b311b926b49a58e1ab244920a4284da",
    (
        "qualification/hcsn_currentstate_n128_thirdcycle_serializer/evidence/source-"
        "49d392f/attempt001/originals.zip.part003"
    ): "34765edc95889ade05a38d186dc4b24e98e2b7488e6873c05b71c54f8ae6099a",
    (
        "qualification/hcsn_n256_multistep/evidence/archive-20261119/part-002.tar.xz"
        ".part"
    ): "5ecd377595fba711824926d55f10e0448b69762553f95ca91e762f362c4856e9",
    (
        "qualification/hcsn_n256_multistep/evidence/archive-20261119/part-006.tar.xz"
        ".part"
    ): "87202461d68163f0e03c8a1de3f51cbc640a235346d6bedc8f9098fa729f694e",
    (
        "qualification/hcsn_replay_artifact_transfer/parts/part-004.bin"
    ): "7f7148217f470f65a3fe997a955d41e0b19fe16c1d42f8026538f6d24bbbc8a5",
    (
        "qualification/hcsn_replay_artifact_transfer/parts/part-046.bin"
    ): "8311a434d03af330644aed00d1edbd2b5ffb64138bce351eabf3b431ca055d72",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/bazel-ci-v5/part-03.bin"
    ): "7a3291c350a3e9462086370e70bfe496e34ec799d5f6a31ddfd524f96666694c",
    (
        "qualification/memory-cell-mem8-ci-followup/v14/source-ci-v5/part-04.bin"
    ): "c9a2735224e5051d03a776c0321b89fcbc65726aebf3b86ae6e01d557bcae443",
    (
        "qualification/memory-cell-mem8-ci-followup/v17/source-v10/V10_COMPLETE_ORIG"
        "INAL_SOURCE_GATE.part-005.xz.part"
    ): "3475496bb2dc2eba35ef32237888210c384b3f44fa9d07eca69e884b65b5f296",
    (
        "qualification/memory-cell-mem8-ci-followup/v17/source-v11/V11_COMPLETE_ORIG"
        "INAL_SOURCE_GATE.part-008.xz.part"
    ): "a8b47d593a19d3f03086856ab1b33f9035598a91f56d7ae521b76dfe0d6b036c",
    (
        "research_evidence/hepta_callput_recovery_20261029/Hepta_Complete_Research_R"
        "eport.html"
    ): "f497509da8f6242def88a013ab888de13f62a84337ae218df7d07b43d4f5bc04",
    (
        "research_evidence/hepta_callput_recovery_20261029/Hepta_Next_Step_Blocker_R"
        "eport.html"
    ): "cd51c1d85cc55f6dfd9addb6f92b56c5b063f7b3e39496c079edd5f1354257d7",
    (
        "research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_202610"
        "30/hepta_recovery_evidence_20261030.tar.gz.part-003"
    ): "86eeeedbca71ea93e290a6ee502ac1baeb94c63c08f77e7d580bc40cf403a855",
    (
        "research_evidence/hepta_stable_flow_20261029/report002/Hepta_New_Scientific"
        "_Report_20261029.html"
    ): "1c712e7fa11dd67c95b0fb5a373962d057a92b96fe6cb8f08a948c7358c67fa5",
    (
        "research_evidence/hepta_stable_flow_20261029/report003_recovery/Hepta_Recov"
        "ery_Scientific_Report_20261030.html"
    ): "fee305a08fa030f21bdd68f9672d28892a15a0df206a7c098cc41dd2d66c5184",
    (
        "qa/repository-consolidation/20261119/round-03/local-time-compatibility/evid"
        "ence.tar.gz.part-001"
    ): "84c771075dc220affd16c3c1599e266547507368b984aafcf697fe7d332308a9",
    (
        "qa/repository-consolidation/20261119/round-03/local-time-compatibility/evid"
        "ence.tar.gz.part-002"
    ): "44c491b8c00e1230bd372bde1192202f00511eaebf6717846cb15d6198a6b118",
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def file_identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def read_regular(root, relative, limit):
    path = root / relative
    for part in PurePosixPath(relative).parents:
        if (root / part).is_symlink():
            raise ValueError("symbolic link in archive path")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("archive input must be a regular single-link file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        if file_identity(before) != file_identity(opened):
            raise ValueError("archive input changed before reading")
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if len(data) > limit:
        raise ValueError("archive input exceeds the byte limit")
    if file_identity(opened) != file_identity(after):
        raise ValueError("archive input changed while reading")
    if file_identity(after) != file_identity(path.lstat()):
        raise ValueError("archive path changed while reading")
    return data


def parse_manifest(raw):
    document = json.loads(raw, object_pairs_hook=unique_object)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "files"}
        or document["schema"] != SCHEMA
        or not isinstance(document["files"], dict)
        or not document["files"]
    ):
        raise ValueError("invalid Codespell custody manifest")
    entries = document["files"]
    for path, expected in entries.items():
        if (
            not isinstance(path, str)
            or not (
                re.fullmatch(r"library-recovery/[A-Za-z0-9._/-]+", path)
                or path in BINARY_ARCHIVE_PATHS
                or path in QUALIFICATION_SOURCE_SHA256
            )
            or str(PurePosixPath(path)) != path
            or any(part in {".", ".."} for part in path.split("/"))
            or len(PurePosixPath(path).parts) < 3
        ):
            raise ValueError("archive exemption must be an exact repository path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("archive exemption requires an exact SHA-256")
        if (
            path in QUALIFICATION_SOURCE_SHA256
            and expected != QUALIFICATION_SOURCE_SHA256[path]
        ):
            raise ValueError("qualification exemption requires its registered SHA-256")
    return entries


def verified_skip(root):
    entries = parse_manifest(read_regular(root, MANIFEST, MAX_MANIFEST_BYTES))
    for path, expected in entries.items():
        actual = hashlib.sha256(read_regular(root, path, MAX_SOURCE_BYTES)).hexdigest()
        if actual != expected:
            raise ValueError(f"archived source digest mismatch: {path}")
    return ",".join(f"./{path}" for path in sorted(entries))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        exclusions = verified_skip(root)
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"skip={exclusions}\n")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Codespell custody validation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Verified {len(exclusions.split(','))} exact archived paths for spelling only."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
