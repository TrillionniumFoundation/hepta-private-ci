"""Selector evidence checks using only invented completed-prefix metadata."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import canonical, decode, digest
from structure_evidence import selection
from structure_selection import select


class SelectionWireTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-selection-wire-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        records = []
        entities = [f"entity:wire-development-{index}" for index in range(9)]
        for index, entity in enumerate(entities):
            for kind, value in (("event", index), ("semantic", {"factor": 2, "label": "development"}),
                                ("procedure", {"opcode": "identity", "bias": 0, "limit": 10})):
                record = {"schema": "hepta.memory.cell-record.v1", "entity": entity,
                          "kind": kind, "effective_at": 10, "value": value}
                records.append({"source_id": digest(canonical(record)), "revision": 1,
                                "owner_memory_id": f"memory:wire-{index}:{kind}", "record": record})
        self.export = {"schema": "hepta.memory.owner-snapshot.v1", "owner_agent_id": "agent:development",
                       "scope": "scope:development", "owner_cut_digest": digest(canonical(records)),
                       "observed_at_unix_seconds": 20, "records": records, "withdrawn_addresses": [],
                       "current_source_ids": [row["source_id"] for row in records]}
        self.prefix = {"records": [{"request_digest": digest(f"request-{index}".encode()),
                                    "readout_digest": digest(f"readout-{index}".encode()),
                                    "requests": [{"entity": entity} for entity in entities[index % 3::3]]}
                                   for index in range(9)]}
        observations = [{"sequence": index + 1, "request_digest": row["request_digest"],
                         "readout_digest": row["readout_digest"],
                         "addresses": sorted(digest(query["entity"].encode()) for query in row["requests"])}
                        for index, row in enumerate(self.prefix["records"])]
        frame = {"schema": "hepta.memory.v9.structure-selection.v1",
                 "source_cut_digest": self.export["owner_cut_digest"],
                 "addresses": sorted(digest(entity.encode()) for entity in entities),
                 "observations": observations, "resident_budget_bytes": 16384}
        self.code = {"digest": digest(b"development-wire-evidence"), "files": {}}
        self.request = canonical(frame)
        (self.root / "FIT_REQUEST.json").write_bytes(canonical({
            "request_json": self.request.decode(), "request_sha256": digest(self.request), "code_identity": self.code}))
        selected = select(frame)
        self.assertTrue(all(type(key) is int for candidate in selected["candidates"]
                            for key in candidate["proxy"]["per_shard_proxy_bytes"]))
        selected["request_digest"] = digest(self.request)
        self.result = decode(canonical(selected))

    def save_response(self, value):
        raw = canonical(value) + b"\n"
        (self.root / "FIT_RESPONSE.json").write_bytes(canonical({
            "response_json": raw.decode(), "response_bytes": len(raw), "request_bytes": len(self.request),
            "exit_code": 0, "stderr": "", "stderr_bytes": 0, "whole_worker_wall_ns": 1, "code_identity": self.code}))

    def test_json_wire_proxy_keys_preserve_reproducible_selection(self):
        self.save_response(self.result)
        checked, cost = selection(self.root, self.code, self.export, self.prefix, self.result)
        self.assertEqual(checked, self.result)
        self.assertEqual(cost, {"whole_worker_wall_ns": 1, "request_bytes": len(self.request),
                               "response_bytes": len(canonical(self.result)) + 1})

    def test_changed_proxy_route_or_selected_count_is_rejected(self):
        for field in ("proxy", "route", "selected"):
            with self.subTest(field=field):
                changed = deepcopy(self.result)
                candidate = changed["candidates"][0]
                if field == "proxy":
                    proxy = candidate["proxy"]["per_shard_proxy_bytes"]
                    proxy[next(iter(proxy))] += 1
                elif field == "route":
                    candidate["routes"][next(iter(candidate["routes"]))] += 1
                else:
                    changed["selected"]["learned"] = changed["selected"]["learned"] % 8 + 1
                self.save_response(changed)
                with self.assertRaisesRegex(ValueError, "prefix-only selection cannot be reproduced"):
                    selection(self.root, self.code, self.export, self.prefix, changed)


if __name__ == "__main__":
    unittest.main()
