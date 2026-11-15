"""Admit a primary-library publication alias only through its actual Cargo row."""
import copy
from pathlib import Path
import re
import stat

from .common import binding, require, verify


def libraries(message, target_dir):
    paths = [Path(name) for name in message["filenames"] if Path(name).suffix in {".rlib", ".rmeta", ".so"}]
    for path in paths:
        require(path.is_absolute() and path.is_file() and not path.is_symlink()
                and path.resolve(strict=True) == path and path.is_relative_to(target_dir),
                "a Cargo library escaped its real target or is not a regular file")
    require(len(paths) == len(set(paths)), "duplicate Cargo artifact filenames")
    selected, aliases = [], []
    crate = message["target"]["name"]
    hashed = re.compile(r"lib" + re.escape(crate) + r"-([0-9a-f]{16})\.(rlib|rmeta|so)")
    for path in paths:
        if hashed.fullmatch(path.name):
            selected.append(path)
            continue
        require(path.name == "lib" + crate + ".rlib", "unsupported Cargo publication filename")
        metadata = [candidate for candidate in paths if candidate.suffix == ".rmeta"
                    and hashed.fullmatch(candidate.name)]
        require(len(metadata) == 1, "publication alias lacks a unique same-row hashed metadata peer")
        metadata = metadata[0]
        require(metadata.parent.name == "deps" and metadata.parent.parent == path.parent,
                "publication alias and metadata use different actual output directories")
        peer = metadata.with_suffix(".rlib")
        require(peer.is_file() and not peer.is_symlink() and peer.resolve(strict=True) == peer
                and peer.is_relative_to(target_dir), "missing actual same-row hashed rlib peer")
        alias_record, peer_record = binding(path), binding(peer)
        require(alias_record["bytes"] == peer_record["bytes"]
                and alias_record["sha256"] == peer_record["sha256"]
                and path.read_bytes() == peer.read_bytes(),
                "actual Cargo publication alias differs from its exact hashed peer")
        verify(alias_record)
        verify(peer_record)
        selected.append(peer)
        aliases.append({"cargo_reported_alias": alias_record, "same_row_metadata": binding(metadata),
                        "selected_hashed_rlib": peer_record, "full_bytes_equal_at_capture": True})
    require(len(selected) == len(set(selected)), "ambiguous ordinary library selection")
    return selected, aliases


def verify_final_aliases(graphs):
    # Successive default/native Cargo commands legitimately republish one path.
    # Retain each original observation and verify the last actual publication.
    last = {}
    for graph in graphs.values():
        for row in graph["publication_aliases"]:
            verify(row["selected_hashed_rlib"])
            verify(row["same_row_metadata"])
            record = row["cargo_reported_alias"]
            last[record["path"]] = record
    for record in last.values():
        verify(record)
    return list(last.values())


def _native_identity(path, *, directory=False):
    path = Path(path)
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    require(path.is_absolute() and path.resolve(strict=True) == path and kind(info.st_mode),
            "native linkage input is not a canonical regular file/directory")
    return {"path": str(path), **{name: getattr(info, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}}


def native_linkage(graph, target_dir, library_dir, build, native_inputs, modules):
    """Bind the actual Cargo OUT_DIR copies to the already admitted formal archives."""
    target_dir, library_dir = Path(target_dir), Path(library_dir)
    require(target_dir.is_dir() and target_dir.resolve(strict=True) == target_dir
            and library_dir.is_dir() and library_dir.resolve(strict=True) == library_dir,
            "native linkage roots are not canonical existing directories")
    modules = tuple(modules)
    require(len(modules) == len(set(modules))
            and all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in modules),
            "native archive module selection is invalid or duplicated")
    rows = graph["build_script_results"]
    require(len(rows) == 1, "native linkage lacks a unique admitted build-script result")
    row = rows[0]
    out_text = row.get("out_dir")
    require(isinstance(out_text, str) and str(Path(out_text)) == out_text,
            "Cargo build-script OUT_DIR is missing or noncanonical")
    out_dir = Path(out_text)
    require(out_dir != target_dir and out_dir.is_relative_to(target_dir),
            "actual Cargo OUT_DIR escaped the admitted target directory")
    out_identity = _native_identity(out_dir, directory=True)
    raw_paths = row.get("linked_paths")
    require(isinstance(raw_paths, list) and all(isinstance(value, str) for value in raw_paths),
            "Cargo native search directives are malformed")
    expected_paths = ["native=" + str(out_dir)] if modules else []
    require(graph["native_paths"] == sorted(set(raw_paths)) == expected_paths,
            "native search is outside the actual Cargo build-script OUT_DIR")
    require(row["linked_libs"] == ["static=codex_hia_" + name for name in modules],
            "actual Cargo static module selection differs from the admitted owners")
    archives = []
    for name in modules:
        symbol = "codex_hia_" + name
        archive_name = "lib" + symbol + ".a"
        abi = build["modules"][name]["codex_link_abi"]
        require(abi["archive"] == archive_name and abi["symbol"] == symbol,
                "formal build archive/symbol names do not match the selected module")
        formal, staged = library_dir / archive_name, out_dir / archive_name
        formal_identity, staged_identity = _native_identity(formal), _native_identity(staged)
        formal_record, staged_record = binding(formal), binding(staged)
        require(str(formal) in native_inputs
                and formal_record == {"path": str(formal), **native_inputs[str(formal)]}
                and formal_record["sha256"] == abi["archive_sha256"],
                "formal archive is not the exact previously admitted native input")
        require(staged_record["bytes"] == formal_record["bytes"]
                and staged_record["sha256"] == formal_record["sha256"]
                and staged.read_bytes() == formal.read_bytes(),
                "actual Cargo OUT_DIR archive differs from the admitted formal archive")
        verify(formal_record)
        verify(staged_record)
        require(_native_identity(formal) == formal_identity
                and _native_identity(staged) == staged_identity,
                "a native archive changed while its complete bytes were compared")
        archives.append({"module": name, "formal": formal_record, "staged": staged_record,
                         "formal_identity": formal_identity, "staged_identity": staged_identity,
                         "full_bytes_equal_at_admission": True})
    require(_native_identity(out_dir, directory=True) == out_identity,
            "Cargo OUT_DIR changed while native archives were admitted")
    return {"target_directory": str(target_dir), "formal_library_directory": str(library_dir),
            "out_dir": out_identity, "raw_build_script_result": copy.deepcopy(row),
            "distinct_native_paths": expected_paths, "modules": list(modules), "archives": archives}
