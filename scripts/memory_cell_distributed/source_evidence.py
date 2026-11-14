"""Read current canonical source bytes without sharing a source DB or path.

Transport grants authorize an exact source root. This adapter validates the
research SourceStore's live head and conflict state; native authorization is a
separate ingress contract and is not inferred from a local scope string.
"""

import base64
import hashlib
import json

from authority_contract import fields, hex_value
from service_types import canonical, digest


class SourceEvidence:
    def __init__(self, store):
        self.store = store
        self.completed_reads = 0

    def dispatch(self, request):
        if request.get("op") == "source_frontier":
            fields(request, ("op", "scope"))
            if request["scope"] != self.store.scope:
                raise ValueError("source frontier scope mismatch")
            snapshot = self.store.snapshot()
            conflict_roots = {
                r for item in snapshot["conflicts"] for r in item["roots"]
            }
            return dict(
                frontier=dict(
                    scope=self.store.scope,
                    epoch=snapshot["epoch"],
                    revoked=snapshot["revoked"],
                ),
                admissible_roots=sorted(set(snapshot["roots"]) - conflict_roots),
                snapshot_sha256=snapshot["digest"],
            )
        fields(request, ("op", "scope", "source_root", "expected_epoch"))
        if (
            request["op"] != "evidence"
            or request["scope"] != self.store.scope
            or not hex_value(request["source_root"])
            or type(request["expected_epoch"]) is not int
        ):
            raise ValueError("bound source-evidence request required")
        with self.store.transaction(write=False) as database:
            snapshot = self.store.snapshot_in(database)
            if snapshot["epoch"] != request["expected_epoch"]:
                raise ValueError("source epoch changed")
            root = request["source_root"]
            conflict_roots = {
                r for conflict in snapshot["conflicts"] for r in conflict["roots"]
            }
            if root in snapshot["revoked"] or root in conflict_roots:
                raise ValueError("withdrawn or conflicting source evidence")
            row = database.execute(
                "SELECT s.payload FROM sources s JOIN heads h ON s.source_id=h.source_id AND s.revision=h.revision WHERE s.root=? AND h.revoked=0",
                (root,),
            ).fetchone()
            if row is None:
                raise ValueError("source root is not a current admitted head")
            payload = json.loads(row[0])
            if digest(payload) != root:
                raise ValueError("source content digest changed")
            raw = canonical(payload)
        # Recheck after serialization. A caller must also revalidate before use.
        if self.store.snapshot()["digest"] != snapshot["digest"]:
            raise ValueError("source changed during evidence read")
        self.completed_reads += 1
        return dict(
            scope=self.store.scope,
            source_root=root,
            source_epoch=snapshot["epoch"],
            payload_base64=base64.b64encode(raw).decode(),
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
            origin="source_evidence",
            parameter_output=False,
        )
