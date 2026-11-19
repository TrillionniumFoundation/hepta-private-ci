"""Majority reads, durable publication and explicit fixed-membership repair."""

from concurrent.futures import ThreadPoolExecutor

from authority_contract import SCHEMA, ZERO, digest, fields, name
from tls_wire import call, endpoint


class QuorumUnavailable(ValueError):
    pass


class QuorumClient:
    def __init__(self, membership, addresses, credentials, *, timeout=10, rpc=call):
        if set(addresses) != set(membership.member_keys) or len(
            set(addresses.values())
        ) != len(addresses):
            raise ValueError("every fixed replica needs a distinct endpoint")
        for address in addresses.values():
            endpoint(address)
        self.membership, self.addresses = membership, dict(addresses)
        self.credentials, self.timeout, self.rpc = credentials, timeout, rpc
        self.last_event = None

    def _all(self, request):
        successes, failures = {}, {}
        with ThreadPoolExecutor(max_workers=len(self.addresses)) as pool:
            futures = {
                member: pool.submit(
                    self.rpc, address, self.credentials, request, timeout=self.timeout
                )
                for member, address in self.addresses.items()
            }
            for member, future in futures.items():
                try:
                    result = future.result()
                    if result.get("member_id") != member:
                        raise ValueError(
                            "endpoint returned a different replica identity"
                        )
                    successes[member] = result
                except (ValueError, OSError) as error:
                    failures[member] = str(error)
        self.last_event = dict(
            operation=request["op"], successes=sorted(successes), failures=failures
        )
        return successes

    def read(self, scope):
        if not name(scope):
            raise ValueError("scope required")
        responses = self._all(dict(op="read", scope=scope))
        heads = []
        for result in responses.values():
            fields(result, ("member_id", "certificate"))
            certificate = result["certificate"]
            if certificate is not None:
                state = self.membership.verify_certificate(certificate)
                if state["scope"] != scope:
                    raise ValueError("quorum response has another scope")
                heads.append(certificate)
        if len(responses) < self.membership.quorum:
            raise QuorumUnavailable("authority read lacks a responding majority")
        if not heads:
            return None
        highest = max(heads, key=lambda c: c["proposal"]["state"]["sequence"])
        sequence = highest["proposal"]["state"]["sequence"]
        if any(
            c["proposal"]["state"]["sequence"] == sequence
            and digest(c["proposal"]) != digest(highest["proposal"])
            for c in heads
        ):
            raise ValueError("same-sequence committed authority fork")
        return highest

    def snapshot(self, scope, cell_id):
        if not name(cell_id):
            raise ValueError("cell identity required")
        certificate = self.read(scope)
        if certificate is None:
            raise QuorumUnavailable("scope has no committed authority state")
        state = certificate["proposal"]["state"]
        return dict(
            frontier=state["frontier"],
            placement=next(
                (p for p in state["placements"] if p["cell_id"] == cell_id), None
            ),
        )

    def proposal(self, scope, frontier, placements, private_key):
        head = self.read(scope)
        state = dict(
            schema=SCHEMA,
            authority_id=self.membership.authority_id,
            membership_sha256=self.membership.sha256,
            scope=scope,
            sequence=head["proposal"]["state"]["sequence"] + 1 if head else 1,
            previous_sha256=digest(head["proposal"]) if head else ZERO,
            frontier=frontier,
            placements=placements,
        )
        return self.membership.propose(state, private_key)

    def finish(self, certificate):
        self.membership.verify_certificate(certificate)
        committed = self._all(dict(op="commit", certificate=certificate))
        pin = digest(certificate["proposal"])
        sequence = certificate["proposal"]["state"]["sequence"]
        valid = [
            member
            for member, result in committed.items()
            if result.get("proposal_sha256") == pin
            and result.get("committed_sequence") == sequence
        ]
        if len(valid) < self.membership.quorum:
            raise QuorumUnavailable(
                "authority publication lacks durable majority acknowledgments; retain proposal and recover"
            )
        return dict(certificate=certificate, acknowledged=sorted(valid))

    def publish(self, proposal):
        self.membership.verify_proposal(proposal)
        votes = self._all(dict(op="prepare", proposal=proposal))
        if len(votes) < self.membership.quorum:
            raise QuorumUnavailable(
                "proposal lacks a durable vote majority; retain proposal and recover"
            )
        certificate = self.membership.certificate(proposal, list(votes.values()))
        return self.finish(certificate)

    def recover_pending(self, scope):
        responses = self._all(dict(op="pending", scope=scope))
        grouped = {}
        for result in responses.values():
            for pending in result["pending"]:
                proposal = pending["proposal"]
                state = self.membership.verify_proposal(proposal)
                if state["scope"] != scope:
                    raise ValueError("pending proposal scope mismatch")
                group = grouped.setdefault(
                    digest(proposal), dict(proposal=proposal, votes=[])
                )
                group["votes"].append(pending["vote"])
        candidates = [
            group
            for group in grouped.values()
            if len(group["votes"]) >= self.membership.quorum
        ]
        if len(candidates) != 1:
            raise QuorumUnavailable("no unique durable prepared majority to recover")
        group = candidates[0]
        return self.finish(
            self.membership.certificate(group["proposal"], group["votes"])
        )

    def repair(self, scope, member):
        if member not in self.addresses:
            raise ValueError("repair target is not a fixed member")
        head = self.read(scope)
        if head is None:
            raise QuorumUnavailable("no certified history to repair")
        target = self.rpc(
            self.addresses[member],
            self.credentials,
            dict(op="read", scope=scope),
            timeout=self.timeout,
        )
        if target.get("member_id") != member:
            raise ValueError("repair endpoint identity mismatch")
        current = target["certificate"]
        after = (
            self.membership.verify_certificate(current)["sequence"] if current else 0
        )
        goal = head["proposal"]["state"]["sequence"]
        transferred = []
        while after < goal:
            responses = self._all(dict(op="history", scope=scope, after=after))
            choices = [
                r["certificates"] for r in responses.values() if r["certificates"]
            ]
            if not choices:
                raise QuorumUnavailable("certified repair history unavailable")
            chain = max(
                choices, key=lambda rows: rows[-1]["proposal"]["state"]["sequence"]
            )
            for certificate in chain:
                state = self.membership.verify_certificate(certificate)
                if state["scope"] != scope or state["sequence"] != after + 1:
                    raise ValueError("repair history is discontinuous")
                result = self.rpc(
                    self.addresses[member],
                    self.credentials,
                    dict(op="commit", certificate=certificate),
                    timeout=self.timeout,
                )
                if result.get("member_id") != member or result.get(
                    "proposal_sha256"
                ) != digest(certificate["proposal"]):
                    raise ValueError("repair acknowledgment mismatch")
                after = state["sequence"]
                transferred.append(digest(certificate["proposal"]))
                if after == goal:
                    break
        return dict(member_id=member, sequence=after, transferred=transferred)
