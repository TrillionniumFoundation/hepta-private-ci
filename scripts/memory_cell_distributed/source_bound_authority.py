"""Certified placement plus live source admission, checked on every invocation.

The source is a single writer and an online availability dependency. Its writes
do not become safe merely because a cached frontier has a majority certificate.
No source values are returned by this path; evidence uses a separate root grant.
"""

from authority_contract import SCHEMA, ZERO, digest, fields, hex_value, roots
from tls_wire import call, endpoint


class SourceBoundAuthority:
    def __init__(self, quorum, source_endpoint, credentials, *, rpc=call, timeout=10):
        endpoint(source_endpoint)
        self.quorum, self.source_endpoint = quorum, source_endpoint
        self.credentials, self.rpc, self.timeout = credentials, rpc, timeout

    def live(self, scope):
        result = self.rpc(
            self.source_endpoint,
            self.credentials,
            dict(op="source_frontier", scope=scope),
            timeout=self.timeout,
        )
        fields(result, ("frontier", "admissible_roots", "snapshot_sha256"))
        fields(result["frontier"], ("scope", "epoch", "revoked"))
        if (
            result["frontier"]["scope"] != scope
            or type(result["frontier"]["epoch"]) is not int
            or result["frontier"]["epoch"] < 0
            or not hex_value(result["snapshot_sha256"])
        ):
            raise ValueError("live source identity or epoch invalid")
        roots(result["admissible_roots"])
        roots(result["frontier"]["revoked"])
        return result

    def snapshot(self, scope, cell_id):
        snapshot = self.quorum.snapshot(scope, cell_id)
        source = self.live(scope)
        if snapshot["frontier"] != source["frontier"]:
            raise ValueError("source and committed authority frontier differ")
        assigned = snapshot["placement"]
        if assigned and not set(assigned["roots"]) <= set(source["admissible_roots"]):
            raise ValueError("placement contains a noncurrent or conflicting source")
        return snapshot

    def publish(self, candidate, expected_generation, writer_key):
        scope = candidate["scope"]
        head = self.quorum.read(scope)
        current = head["proposal"]["state"]["placements"] if head else []
        previous = next(
            (item for item in current if item["cell_id"] == candidate["cell_id"]), None
        )
        if (previous["generation"] if previous else None) != expected_generation:
            raise ValueError("placement compare-and-swap failed")
        source = self.live(scope)
        if not set(candidate["roots"]) <= set(source["admissible_roots"]):
            raise ValueError("candidate includes noncurrent source")
        placements = sorted(
            [item for item in current if item["cell_id"] != candidate["cell_id"]]
            + [candidate],
            key=lambda item: item["cell_id"],
        )
        state = dict(
            schema=SCHEMA,
            authority_id=self.quorum.membership.authority_id,
            membership_sha256=self.quorum.membership.sha256,
            scope=scope,
            sequence=head["proposal"]["state"]["sequence"] + 1 if head else 1,
            previous_sha256=digest(head["proposal"]) if head else ZERO,
            frontier=source["frontier"],
            placements=placements,
        )
        proposal = self.quorum.membership.propose(state, writer_key)
        self.quorum.publish(proposal)
        if self.live(scope) != source:
            raise ValueError(
                "source changed during placement publication; candidate remains fenced"
            )
        return candidate
