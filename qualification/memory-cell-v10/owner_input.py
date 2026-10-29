"""Normalize exported owner cuts without inventing or authenticating identities."""

import json
from pathlib import Path

from export_native import canonical, sha, valid_digest


def load_owner(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("owner snapshot exceeds the research import bound")
    value = json.loads(raw)
    pages = value if isinstance(value, list) else value.get("pages", [value])
    if not isinstance(pages, list) or not 1 <= len(pages) <= 128:
        raise ValueError("invalid bounded snapshot page sequence")
    if pages[-1].get("schema") == "hepta.memory.inventory-owner-snapshot-page.v1" and pages[-1].get("next_after") is not None:
        raise ValueError("owner snapshot pagination is incomplete")
    records, identity, seen, seen_sources = [], None, set(), set()
    for page in pages:
        schema = page.get("schema")
        if schema == "hepta.memory.v10.native-training-input.v1":
            cut = page["owner_cut_sha256"]
            owner = (page.get("owner_agent_id"), page.get("scope"), cut)
            entries = page["records"]
        elif schema == "hepta.memory.inventory-owner-snapshot-page.v1":
            cut = page["owner_cut_digest"]
            owner = (page["owner_agent_id"], page["scope"], cut)
            entries = []
            for row in page["records"]:
                record = row["record"]
                if record["schema"] != "hepta.memory.inventory-record.v1":
                    raise ValueError("unsupported inventory record schema")
                entries.append({**record, "source_id": row["source_id"],
                                "owner_memory_id": row["owner_memory_id"], "revision": row["revision"]})
        else:
            raise ValueError("unsupported owner snapshot schema")
        if not valid_digest(cut) or (identity is not None and owner != identity):
            raise ValueError("owner pages must have the same owner, scope and canonical cut")
        identity = owner
        for row in entries:
            marker = (row["kind"], row["key"], row.get("effective_at") if row["kind"] == "event" else None)
            if (marker in seen or row["source_id"] in seen_sources or row["kind"] not in ("semantic", "procedure", "event", "hold")
                    or not isinstance(row["key"], str) or not row["key"]
                    or not valid_digest(row["source_id"])):
                raise ValueError("invalid, duplicate or unbound inventory record")
            seen.add(marker)
            seen_sources.add(row["source_id"])
            records.append(dict(row))
    if identity is None or not 1 <= len(records) <= 4096:
        raise ValueError("empty or oversized owner snapshot")
    result = {"schema": "hepta.memory.v10.native-training-input.v1",
              "owner_agent_id": identity[0], "scope": identity[1], "owner_cut_sha256": identity[2],
              "records": records, "source_input_sha256": sha(raw), "input_pages": len(pages),
              "owner_authentication_claimed_by_importer": False}
    result["normalized_sha256"] = sha(canonical(result))
    return result
