"""Admit the exact frozen owner16 bundle for new owner17 consumer binaries.

This candidate is not a Cargo rebuild environment. Compiler/sysroot/CRT/system
dynamic libraries remain platform inputs. It never compiles or runs a binary.
Publication is a separate, mandatory promotion record; the original bundle's
pending-final-source field is preserved.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct


MANIFEST_SHA = "62d7c78ddd44d8dbe3f0b79c37e338ffc4d964b60aa7074bd3b51cfa24252a5b"
PUBLIC_SHA = "eef2ce2356eeeee04d6d1fe59aeb62b83ec6890c7e7dce51f15df1d28ea49192"
LINK_PROOF_SHA = "685b2e9272b1993029a55c6de01a48ade5831bd518ec70e95dc9c7682037d3ef"
BUILD_SHA = "ee2fae74cbb9dcad2d380d9efc3d653351cde067f43e5d01ffde032128d9d36e"
OWNER_SHA = "b57b3c3fa0d4a2a562e2917f8cdb2e2de820fd655f490e35d654537c8b52ff3b"
DEPENDENCIES = ("serde", "serde_json", "anyhow", "multimap", "codex_utils_absolute_path")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError("frozen owner16: " + message)


def one(rows, description):
    rows = list(rows)
    require(len(rows) == 1, "expected one " + description)
    return rows[0]


def git_object(kind, contents):
    return hashlib.sha1(kind.encode() + b" " + str(len(contents)).encode() + b"\0" + contents).hexdigest()


def tree_identity(entries):
    """Recompute the complete published tree; a partial inventory cannot pass."""
    root, indexed = {}, {}
    for entry in entries:
        name = entry["path"]
        path = PurePosixPath(name)
        require(bool(path.parts) and not path.is_absolute() and path.as_posix() == name and ".." not in path.parts
                and "\0" not in name and name not in indexed, "invalid/duplicate Git inventory path")
        require(entry["mode"] in ("100644", "100755", "120000", "160000")
                and re.fullmatch(r"[0-9a-f]{40}", entry["object"]), "invalid Git leaf")
        node = root
        for part in path.parts[:-1]:
            node = node.setdefault(part, {})
            require(isinstance(node, dict), "Git file/directory collision")
        require(path.name not in node, "Git path collision")
        node[path.name] = (entry["mode"], entry["object"])
        indexed[name] = entry

    def encode(node):
        rows = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, oid = ("40000", encode(value)) if directory else value
            key = name.encode() + (b"/" if directory else b"")
            rows.append((key, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid)))
        return git_object("tree", b"".join(value for _, value in sorted(rows)))

    return encode(root), indexed


def options(argv, flag):
    values = []
    for index, value in enumerate(argv):
        if value == flag:
            require(index + 1 < len(argv), "incomplete compiler flag " + flag)
            values.append(argv[index + 1])
        elif value.startswith(flag + "="):
            values.append(value[len(flag) + 1:])
    return values


def externs(capture):
    values = [value.split("=", 1) for value in options(capture["argv"], "--extern")]
    require(all(len(value) == 2 for value in values), "malformed extern argument")
    result = dict(values)
    require(len(result) == len(values) and result == capture["externs"], "ambiguous extern capture")
    return result


def predecessor_output_guard(args, target, artifacts):
    """Reject overlap before the caller creates logs or runs rustc --version."""
    if args.predecessor_manifest is None:
        require(not args.require_predecessor, "required published owner16 descriptor is missing")
        return
    expected = args.predecessor_manifest_sha256
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "the promotion descriptor needs an explicit SHA256")
    path = args.predecessor_manifest.resolve(strict=True)
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, "promotion descriptor bytes differ")
    descriptor = json.loads(data)
    require(descriptor["schema"] == "codex.hia.published-owner16-consumer.v1", "wrong promotion schema")
    protected_roots = [Path(descriptor[key]).resolve(strict=True) for key in ("bundle_root", "original_outer")]
    for output in (target, artifacts, args.report):
        resolved = Path(output).resolve()
        require(all(not resolved.is_relative_to(root) and not root.is_relative_to(resolved)
                    for root in protected_roots), "output overlaps frozen owner: " + str(output))


def frozen_inventory(bundle):
    actual_files = set()
    for directory, subdirectories, files in os.walk(bundle / "files", followlinks=False):
        require(all(not (Path(directory) / name).is_symlink() for name in subdirectories),
                "symlink directory in frozen package")
        actual_files.update(str(Path(directory) / name) for name in files)
    return actual_files


def verify_predecessor16_inputs(report):
    """Repeat immutable inventory/identity checks after all consumer processes."""
    predecessor = report.get("predecessor")
    if predecessor is None:
        return
    require(all(sha(path) == digest for path, digest in report["predecessor_inputs"].items()),
            "input changed after consumer execution")
    manifest_path = Path(predecessor["manifest_path"])
    require(sha(manifest_path) == MANIFEST_SHA, "frozen manifest changed")
    manifest = json.loads(manifest_path.read_bytes())
    for row in manifest["files"]:
        path = Path(row["destination"])
        info = path.lstat()
        require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1 and info.st_size == row["bytes"]
                and stat.S_IMODE(info.st_mode) == (0o755 if row["original_mode"] & 0o111 else 0o644)
                and (info.st_dev, info.st_ino) == (row["copy_device"], row["copy_inode"]),
                "frozen filesystem identity changed: " + str(path))
    require(frozen_inventory(Path(predecessor["bundle_root"]))
            == {row["destination"] for row in manifest["files"]}, "frozen inventory changed")
    predecessor["inputs_unchanged_after_consumers"] = True


def link_file_shape(path, bundle, toolchain):
    """Reject indirect archive/script or absolute old-target loader references."""
    with path.open("rb") as stream:
        magic = stream.read(8)
    require(magic != b"!<thin>\n", "thin archive requires an explicitly materialized closure")
    if path.suffix in (".a", ".rlib"):
        require(magic == b"!<arch>\n", "archive is an unsupported linker script/input")
    if path.suffix != ".so":
        return []
    data = path.read_bytes()
    require(len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01", "unsupported shared-object format")
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_size, section_count = struct.unpack_from("<HH", data, 58)
    require(section_size >= 64 and section_count > 0
            and section_offset + section_count * section_size <= len(data), "invalid ELF sections")
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, section_offset + i * section_size)
                for i in range(section_count)]
    needed = []
    for section in sections:
        if section[1] != 6:
            continue
        require(section[6] < len(sections) and section[5] % 16 == 0, "invalid ELF dynamic table")
        strings = sections[section[6]]
        require(strings[4] + strings[5] <= len(data)
                and section[4] + section[5] <= len(data), "invalid ELF dynamic bounds")
        table = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], 16):
            tag, value = struct.unpack_from("<QQ", data, offset)
            if tag not in (1, 15, 29):
                continue
            require(value < len(table) and b"\0" in table[value:], "invalid ELF string")
            text = table[value:table.index(b"\0", value)].decode()
            if tag == 1:
                require("/" not in text, "path-qualified ELF dependency escapes the link plan")
                needed.append(text)
                continue
            for part in text.split(":"):
                require(bool(part), "empty implicit loader search directory")
                expanded = part.replace("${ORIGIN}", str(path.parent)).replace("$ORIGIN", str(path.parent))
                require("$" not in expanded and Path(expanded).is_absolute(), "unresolved ELF loader path")
                resolved = Path(expanded).resolve()
                require(resolved.is_relative_to(bundle) or resolved.is_relative_to(toolchain),
                        "ELF loader path leaves bundle and fixed compiler toolchain")
    return needed


def load_predecessor16(args, report, target, rustc, rustc_verbose):
    """Validate source, publication, exact Cargo units and every frozen input."""
    descriptor_path = args.predecessor_manifest
    if descriptor_path is None:
        require(not args.require_predecessor, "required published owner16 descriptor is missing")
        return None
    expected = args.predecessor_manifest_sha256
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "the promotion descriptor needs an explicit SHA256")
    protected = {}

    def reference(record, expected_digest=None, decode=True):
        path = Path(record["path"]).resolve(strict=True)
        digest = record["sha256"]
        require(expected_digest is None or digest == expected_digest, "unexpected evidence identity")
        require(path.is_file(), "evidence is not a file: " + str(path))
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, "evidence bytes differ: " + str(path))
        protected[str(path)] = digest
        return json.loads(data) if decode else data

    descriptor = reference({"path": str(descriptor_path), "sha256": expected})
    require(descriptor["schema"] == "codex.hia.published-owner16-consumer.v1", "wrong promotion schema")
    publication = descriptor["publication"]
    require(all(re.fullmatch(r"[0-9a-f]{40}", publication[key] or "")
                for key in ("revision", "tree")), "owner16 has not been published")
    commit = reference(publication["raw_commit"], decode=False)
    require(git_object("commit", commit) == publication["revision"]
            and commit.splitlines()[0] == ("tree " + publication["tree"]).encode(), "commit/tree mismatch")
    inventory = reference(publication["tree_inventory"])
    computed_tree, git_files = tree_identity(inventory["entries"])
    require(computed_tree == publication["tree"], "complete published tree does not match inventory")
    manifest = reference(descriptor["manifest"], MANIFEST_SHA)
    proof = reference(descriptor["link_proof"], LINK_PROOF_SHA)
    require(manifest["schema"] == "codex.hia.compiled-owner-consumer-link-bundle.v1"
            and manifest["source_public_report_sha256"] == PUBLIC_SHA, "wrong owner bundle")
    require(proof["schema"] == "codex.hia.compiled-owner-consumer-link-proof.v1"
            and proof["passed"] is True and proof["manifest"]["sha256"] == MANIFEST_SHA
            and proof["before_after_all_selected_hashes_equal"] is True, "historical link validation missing")
    bundle = Path(descriptor["bundle_root"]).resolve(strict=True)
    require(Path(descriptor["manifest"]["path"]).resolve().parent == bundle, "bundle location mismatch")
    original_outer = Path(descriptor["original_outer"])
    require(original_outer.is_absolute() and original_outer.resolve(strict=True) == original_outer,
            "original owner root is not canonical")
    source_root = original_outer / "codex"
    native_source = original_outer / "native-root-v1"
    current_target = Path(target).resolve()
    require(not current_target.is_relative_to(bundle) and not bundle.is_relative_to(current_target)
            and not current_target.is_relative_to(original_outer), "current target overlaps frozen owner")
    toolchain = Path(rustc).resolve(strict=True).parent.parent
    by_source, by_destination, dynamic_names = {}, {}, set()
    require(len(manifest["files"]) == manifest["files_count"] == proof["independent_files"] == 1306,
            "incomplete frozen inventory")
    require(sum(row["bytes"] for row in manifest["files"]) == manifest["bytes"]
            == proof["independent_bytes"] == 1311650382, "frozen byte count differs")
    for row in manifest["files"]:
        source, destination = Path(row["source"]), Path(row["destination"])
        require(source.is_relative_to(original_outer), "unexpected original input root")
        require(destination == bundle / "files" / source.relative_to(original_outer)
                and destination.resolve(strict=True) == destination, "noncanonical frozen destination")
        require(str(source) not in by_source and str(destination) not in by_destination, "duplicate frozen path")
        info = destination.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and row["symlink"] is None
                and row["independently_copied"] is True, "not a regular independent frozen copy")
        require((info.st_dev, info.st_ino) == (row["copy_device"], row["copy_inode"])
                and (info.st_dev, info.st_ino) != (row["original_device"], row["original_inode"]),
                "frozen copy identity differs")
        require(info.st_size == row["bytes"]
                and stat.S_IMODE(info.st_mode) == (0o755 if row["original_mode"] & 0o111 else 0o644)
                and sha(destination) == row["sha256"], "frozen file changed: " + str(destination))
        protected[str(destination)] = row["sha256"]
        by_source[str(source)], by_destination[str(destination)] = destination, row
        dynamic_names.update(link_file_shape(destination, bundle, toolchain))
    require(frozen_inventory(bundle) == set(by_destination), "frozen package has missing or extra inputs")

    def mapped(path, expected_digest=None):
        require(str(path) in by_source, "input absent from exact frozen inventory: " + str(path))
        result = by_source[str(path)]
        require(expected_digest is None or protected[str(result)] == expected_digest, "input hash disagreement")
        return result

    public = json.loads(mapped(original_outer / "command-dispatch-public-v3.json", PUBLIC_SHA).read_bytes())
    require(public["passed"] is True and public["three_baseline_performance_executed"] is True,
            "historical public qualification incomplete")
    require(public["rustc"] == manifest["rustc_verbose"] == rustc_verbose, "compiler identity differs")
    require(len(public["source_sha256"]) == 54, "compiled source inventory differs")
    for path, digest in public["source_sha256"].items():
        actual = mapped(source_root / path, digest)
        require(path in git_files and git_files[path]["mode"] in ("100644", "100755")
                and git_object("blob", actual.read_bytes()) == git_files[path]["object"],
                "compiled source is not in final published owner16 tree: " + path)
    build = public["builds"]["native"]
    captures = {kind: json.loads(mapped(row["path"], row["sha256"]).read_bytes())
                for kind, row in build["compiler_captures"].items()}
    require(set(captures) == {"lib", "bin"}, "missing exact compiler captures")
    require(all(Path(row["compiler"]).resolve(strict=True) == Path(rustc).resolve(strict=True)
                for row in captures.values()), "captured compiler path differs")
    require('feature="hia-native"' in captures["lib"]["argv"], "owner16 native feature was not compiled")
    calls = one((row for row in public["commands"] if row["label"] == "build-native"), "native Cargo build")
    require(calls["returncode"] == 0 and calls["timed_out"] is False, "native Cargo build did not finish")
    require(calls["command"] == [str(Path(rustc).resolve(strict=True).with_name("cargo")),
            "build", "--locked", "-p", "codex-execpolicy", "--bin", "codex-execpolicy",
            "--target-dir", str(original_outer / "target"), "--message-format=json", "--features", "hia-native"],
            "historical native Cargo invocation differs")
    for stream in ("stdout", "stderr"):
        row = calls[stream]
        require(mapped(row["path"], row["sha256"]).stat().st_size == row["bytes"], "Cargo stream size differs")
    cargo = [json.loads(line) for line in mapped(calls["stdout"]["path"]).read_text().splitlines() if line]
    require(one((row for row in cargo if row.get("reason") == "build-finished"), "Cargo completion")["success"] is True,
            "historical Cargo completion was not successful")
    units = [row for row in cargo if row.get("reason") == "compiler-artifact"]
    scripts = [{key: row[key] for key in ("package_id", "linked_libs", "linked_paths")}
               for row in cargo if row.get("reason") == "build-script-executed"]
    require(units == manifest["cargo_units"] and len(units) == 234
            and scripts == manifest["build_script_linkage"] and len(scripts) == 35, "Cargo closure differs")
    for unit in units:
        for filename in unit["filenames"]:
            mapped(filename)
    lib_extern, bin_extern = externs(captures["lib"]), externs(captures["bin"])
    for captured in (lib_extern, bin_extern):
        for path in captured.values():
            mapped(path)
            require(any(path in unit["filenames"] for unit in units), "captured extern is not an actual Cargo artifact")
    owner_record = build["dependencies"]["codex_execpolicy"]
    owner_unit = one((unit for unit in units if unit["target"]["name"] == "codex_execpolicy"
                     and owner_record["path"] in unit["filenames"]), "native owner Cargo unit")
    require(bin_extern["codex_execpolicy"] == owner_record["path"]
            and "hia-native" in owner_unit["features"], "binary did not consume native owner16")
    require(build["rlib_sha256"] == owner_record["sha256"] == OWNER_SHA, "wrong predecessor owner")
    mapped(owner_record["path"], OWNER_SHA)
    dependencies = {}
    require(set(build["dependencies"]) == {"codex_execpolicy", *DEPENDENCIES}, "unexpected direct dependencies")
    for name in DEPENDENCIES:
        record = build["dependencies"][name]
        metadata, linked = lib_extern[name], bin_extern[name]
        unit = one((unit for unit in units if unit["target"]["name"] == name
                    and metadata in unit["filenames"] and linked in unit["filenames"]), "dependency unit " + name)
        expected_unit = build["runtime_units"][name]
        require(all(unit[key] == expected_unit[key] for key in ("package_id", "features", "profile", "filenames"))
                and record["path"] == linked, "direct dependency capture/unit mismatch")
        mapped(metadata, expected_unit["metadata_sha256"])
        dependencies[name] = {"path": str(mapped(linked, record["sha256"])), "sha256": record["sha256"]}
    directories = {}
    for row in manifest["directory_mapping"]:
        source = Path(row["source"])
        require(row["kind"] in ("native", "dependency") and source.is_relative_to(original_outer), "invalid search root")
        destination = bundle / "files" / source.relative_to(original_outer)
        require(str(destination) == row["destination"] and destination.resolve(strict=True) == destination
                and destination.is_dir(), "search mapping differs")
        key = (row["kind"], str(source))
        require(key not in directories, "duplicate link-search mapping")
        directories[key] = str(destination)
    expected_directories = {("native", str(native_source))}
    linkage = []
    for kind, capture in captures.items():
        require(not any(arg.startswith("@") for arg in capture["argv"]), "unreviewed response file")
        require(not any(value.startswith(("link-arg", "linker=")) for value in options(capture["argv"], "-C")),
                "unreviewed explicit linker argument")
        expected_directories.update(tuple(value.split("=", 1)) for value in options(capture["argv"], "-L"))
        linkage.extend({"capture": kind, "flag": "-l", "value": value}
                       for value in options(capture["argv"], "-l"))
    for script in scripts:
        expected_directories.update(tuple(value.split("=", 1)) for value in script["linked_paths"])
    require(set(directories) == expected_directories and len(directories) == 4, "transitive search closure differs")
    require(linkage == manifest["capture_linkage"], "captured native library directives differ")
    native = json.loads(mapped(native_source / "build.json", BUILD_SHA).read_bytes())
    require(len(native["modules"]) == 16 and "command_dispatch" in native["modules"]
            and "network_host" not in native["modules"], "predecessor module set is not owner16")
    require(sum(Path(path).is_relative_to(native_source) for path in by_source) == 216,
            "incomplete native16 artifact inventory")
    for field, source in (("toolchain_lock_sha256", "hia/toolchain.json"),
                          ("build_driver_sha256", "hia/build.py"), ("cargo_helper_sha256", "hia/cargo_build.rs")):
        require(native[field] == public["source_sha256"][source], "native builder/source mismatch: " + field)
    for name, module in native["modules"].items():
        require(public["source_sha256"][f"hia/{name}.hepta"] == module["source_sha256"], "HIA source/build mismatch")
        link = module["codex_link_abi"]
        mapped(native_source / link["archive"], link["archive_sha256"])
    for path, digest in public["native_inputs"].items():
        mapped(native_source / path, digest)
    for row in linkage:
        value = row["value"]
        require(value.startswith("static=codex_hia_"), "unreviewed direct owner linkage")
        archive = "lib" + value.removeprefix("static=") + ".a"
        digest = public["native_inputs"][archive]
        copies = [Path(directory) / archive for (kind, _), directory in directories.items()
                  if kind == "native" and str(Path(directory) / archive) in by_destination]
        require(len(copies) == 2 and all(protected[str(path)] == digest for path in copies),
                "native search directories contain different archive copies")
    require(all(sha(path) == digest for path, digest in protected.items()), "input changed during admission")
    report["predecessor_inputs"] = protected
    report["predecessor"] = {"status": "validated_frozen_owner16_bundle", "rustc": rustc_verbose,
        "published_revision": publication["revision"], "published_tree": publication["tree"],
        "manifest_path": str(Path(descriptor["manifest"]["path"]).resolve()), "bundle_root": str(bundle),
        "manifest_sha256": MANIFEST_SHA, "public_report_sha256": PUBLIC_SHA,
        "original_manifest_pending_final_field": manifest["source_after_final_maintenance_pending"],
        "promotion_descriptor_sha256": expected, "compiled_source_files_bound_to_published_tree": len(public["source_sha256"]),
        "independent_files_verified": len(by_source), "native_module_count": 16,
        "copy_mode_contract": "original freeze operation normalized executable files to 0755 and other files to 0644",
        "owner_rlib": str(mapped(build["rlib"], OWNER_SHA)), "owner_rlib_sha256": OWNER_SHA,
        "runtime_units": build["runtime_units"], "compiler_captures": build["compiler_captures"],
        "owner_rebuilt_now": False, "compiled_now": False, "executed_now": False, "new_harness_processes": {},
        "compiled_now_scope": "new owner17 allocation and performance consumer harnesses; not a Cargo owner rebuild",
        "compiler_identity_scope": "exact captured executable path and complete verbose version; historical executable bytes were not pinned",
        "external_platform_dynamic_names": sorted(dynamic_names),
        "external_platform_scope": manifest["external_platform_dependencies"],
        "existing_performance_binary_reused": False}
    return ({"rlib": str(mapped(build["rlib"], OWNER_SHA)), "rlib_sha256": OWNER_SHA,
             "dependencies": dependencies, "link_search_paths": [
                 {"kind": kind, "path": destination} for (kind, _), destination in sorted(directories.items())]},
            Path(directories[("native", str(native_source))]))
