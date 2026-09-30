#!/usr/bin/env python3
"""Verify ui.control navigation with the repository's canonical source rules."""

from pathlib import Path
import runpy

maps = runpy.run_path(str(Path(__file__).with_name("hepta-implementation-maps.py")))
row = maps["load"]("docs/modules/ui.control/IMPLEMENTATION_MAP.json")
candidate = maps["current_source_base"]()
module = next(
    item
    for item in maps["load"]("docs/modules/MODULES.json")["modules"]
    if item["id"] == "ui.control"
)
roots = maps["resolve_source_roots"](maps["ROOT"], module)
if row.get("resolvedRoots") != roots or row.get("module") != "ui.control":
    raise ValueError("ui.control module/root identity differs from the registry")
maps["validate_claim_types"](row)
maps["validate_closed_world_bindings"](row)
maps["verify_source_identity"](row, roots, candidate)
if row.get("mappingSourceIdentityMode") != "exact_blob":
    raise ValueError("ui.control requires exact mapped source blobs")
for operation in row["operations"]:
    path = operation["sourcePath"]
    if operation.get("sourceBlob") != maps["git"]("rev-parse", f"HEAD:{path}"):
        raise ValueError(f"ui.control mapped source blob drift: {path}")
if row.get("sourceObjects") != maps["current_source_objects"](row):
    raise ValueError("ui.control source object inventory is stale or incomplete")
callers = row.get("productCallers")
if not isinstance(callers, list) or not callers:
    raise ValueError("ui.control browser composition requires registered callers")
for caller in maps["canonical_product_callers"](callers):
    symbol = caller.get("nativeSymbol")
    path = maps["checked_source_path"](maps["ROOT"], caller["sourcePath"])
    if (
        not isinstance(symbol, str)
        or not symbol
        or symbol not in path.read_text(encoding="utf-8")
    ):
        raise ValueError("ui.control product caller symbol is missing")
print("ui.control canonical source identity and browser caller map passed")
