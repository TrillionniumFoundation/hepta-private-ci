"""Admit a primary-library publication alias only through its actual Cargo row."""
from pathlib import Path
import re

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
