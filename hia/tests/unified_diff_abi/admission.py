"""Source, fixed compiler and canonical native artifact admission."""
import hashlib
import json
from pathlib import Path
import sys

SOURCE_SHA = "36e347f329d061af2e6f45fbd7f0897b3c0a870a54b3d05090b335bfbce72ef5"
CONTRACT_SHA = "758ffca2ba472ba7e8cd0618a92b5867c611efcdbc633d00ecae9bbafea1045e"
COMPILER_SHA = "76fe758bc49499046169a5b4798c31d57366344c23530b35bc489e4008639273"
RAW_OBJECT_SHA = "c4c7b2930c2d4b4da1f7cde9338f0e29f817ae6e89547b7fda4abdc20776f96c"
NAMED_OBJECT_SHA = "f0e851f0b7fcaead0d249183e204fd1ade33e033ef14f56d701ecc7c20ab495e"
SYMBOL = "codex_hia_unified_diff"
PROFILE = "borrowed-buffers-u32-v1"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def validate_binding(record):
    path = Path(record["path"])
    require(binding(path) == record, "input binding changed: " + str(path))
    return path


def archive_member(path):
    data = Path(path).read_bytes()
    require(data[:8] == b"!<arch>\n", "native archive signature differs")
    at, found = 8, []
    while at < len(data):
        header = data[at:at + 60]
        require(len(header) == 60 and header[58:] == b"\x60\n",
                "native archive member header differs")
        name = header[:16].decode("ascii").strip()
        size = int(header[48:58].decode("ascii").strip())
        start, end = at + 60, at + 60 + size
        require(end <= len(data), "native archive member is truncated")
        if name != "/":
            require(name == "hia.o/", "unexpected native archive member: " + name)
            found.append(data[start:end])
        at = end + (size & 1)
    require(at == len(data) and len(found) == 1,
            "native archive must contain exactly one hia.o member")
    return found[0]


def admit(library_path, symbol, source_path, report_path, contract_path):
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    source_path, report_path, contract_path = (
        Path(value).resolve(strict=True)
        for value in (source_path, report_path, contract_path)
    )
    repo = source_path.parents[1]
    directory = report_path.parent
    require(source_path == repo / "hia/unified_diff.hepta" and
            contract_path == repo / "hia/unified_diff_buffer_contract.json",
            "source and contract must come from one producing checkout")
    require(Path(library_path).resolve(strict=True) ==
            directory / "libcodex_hia_unified_diff.so" and
            report_path.name == "build.json" and symbol == SYMBOL,
            "the canonical library/report/symbol identity differs")
    build = json.loads(report_path.read_text())
    require(build.get("schema") == "codex.hia.native-build.v1" and
            build.get("status") == "built" and
            build.get("build_mode") == "native-selfhost" and
            build.get("compiler_fixed_point") is True and
            build.get("compiler_sha256") == COMPILER_SHA,
            "a genuine complete fixed-point native build is required")
    lock_path = repo / "hia/toolchain.json"
    lock = json.loads(lock_path.read_text())
    require(build["toolchain"] == lock and
            build["toolchain_lock_sha256"] == sha256(lock_path) and
            set(build["modules"]) == set(lock["modules"]),
            "the complete build does not match the current toolchain lock")
    require(lock["revision"] == "0de5657a80f96b138525ac7ee9ce11712a83a10d" and
            lock.get("entry_profiles", {}).get("unified_diff", PROFILE) == PROFILE,
            "the unified entry requires the fixed buffer compiler profile")
    driver, helper = repo / "hia/build.py", repo / "hia/cargo_build.rs"
    require(build["build_driver_sha256"] == sha256(driver) and
            build["cargo_helper_sha256"] == sha256(helper),
            "the current driver/helper differs from the actual producer")
    require(sha256(source_path) == SOURCE_SHA and sha256(contract_path) == CONTRACT_SHA,
            "the source or normative contract differs from the frozen final candidate")
    contract = json.loads(contract_path.read_text())
    require(contract["schema"] == "codex.hia.unified-diff-buffer.v2" and
            contract["revision"] == 2 and contract["target"]["usize_bits"] == 64 and
            contract["input"]["descriptor_bytes"] == 64 and
            contract["output"]["header_bytes"] == 128 and
            contract["output"]["fragment_stride"] == 32,
            "the complete-owner contract dimensions differ")
    component = build["modules"]["unified_diff"]
    require(component["source_sha256"] == SOURCE_SHA and
            component["entry_profile"] == PROFILE,
            "the canonical component source/profile differs")
    abi = component["codex_link_abi"]
    require(abi["symbol"] == SYMBOL and abi["defined_symbols"] == [SYMBOL] and
            abi["undefined_symbols"] == [],
            "the canonical symbol inventory differs")
    artifacts = []
    for key, name in (
        ("library", "libcodex_hia_unified_diff.so"),
        ("archive", "libcodex_hia_unified_diff.a"),
        ("object", "unified_diff.namespaced.o"),
    ):
        path = directory / name
        require(abi[key] == name and abi[key + "_sha256"] == sha256(path),
                "stale canonical " + key + " binding")
        artifacts.append(path)
    raw = directory / "unified_diff.o"
    require(sha256(raw) == RAW_OBJECT_SHA and sha256(artifacts[2]) == NAMED_OBJECT_SHA,
            "the compiled machine objects differ from the frozen final source")
    require(abi["archive_member"] == "hia.o" and
            archive_member(artifacts[1]) == artifacts[2].read_bytes(),
            "the actual canonical archive does not contain its namespaced object")
    inventory = component["object_inventory"]
    require(inventory["object_sha256"] == sha256(raw) and
            inventory["exports"] == ["f0"] and inventory["undefined_symbols"] == [] and
            inventory["external_relocations"] == [] and inventory["entry_wrapper_bytes"] == 78,
            "the raw object differs from the admitted buffer ABI")
    compilation = component["compilation"]
    require(compilation["status"] == "returned" and compilation["abi_status"] == 0 and
            compilation["source_unchanged"] is True and
            compilation["forbidden_compiler_modules_loaded"] == [] and
            compilation["produced_sha256"] == sha256(raw) and
            compilation["image_sha256"] == compilation["artifact_sha256"] == COMPILER_SHA,
            "the actual native compilation receipt differs")
    generations = build["bootstrap_generations"]
    require([entry["case"] for entry in generations] == ["B1", "B2", "B3"],
            "all three compiler generations are required")
    images = []
    for entry in generations:
        image = directory / "bootstrap" / (entry["case"] + ".image.bin")
        require(entry["status"] == "returned" and entry["abi_status"] == 0 and
                entry["source_unchanged"] is True and
                entry["forbidden_compiler_modules_loaded"] == [] and
                entry["produced_sha256"] == sha256(image) == COMPILER_SHA,
                "a compiler generation does not reproduce the fixed point")
        images.append(image)
    return [binding(path) for path in (
        source_path, contract_path, report_path, lock_path, driver, helper,
        raw, *artifacts, *images, Path(__file__).resolve(),
    )]
