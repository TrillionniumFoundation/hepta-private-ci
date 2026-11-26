"""Restore exact historical evidence from individually compressed containers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
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
INDEX_SHA256 = {
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
    NATIVE_NOTICE_BYTE_INDEX: "5a323dde4ec10fca217856d5ff319acd708db94e460eebb524025a0c4463316e",
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


def read_verified(repo, relative, expected_bytes, expected_sha256):
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_BYTES:
        raise ValueError("invalid original evidence byte bound")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise ValueError("invalid original evidence checksum")
    relative = relative_path(str(relative)).as_posix()
    path = repo / relative
    if path.exists() or path.is_symlink():
        data = read_regular(repo, relative, expected_bytes)
    else:
        entry = entries(repo)[relative]
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
