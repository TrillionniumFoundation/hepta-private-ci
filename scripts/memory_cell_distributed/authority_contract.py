"""Signed, bounded authority states for a fixed, trusted replica membership.

This is a single-writer protocol with majority durable votes, not leader election
or Byzantine consensus. Canonical source values are deliberately absent.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ZERO = "0" * 64
MAX_STATE_BYTES = 4 * 1024 * 1024
SCHEMA = "hepta.memory.authority-state.v1"


def encode(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def decode(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite JSON value")

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if type(result) is not dict:
        raise ValueError("JSON object required")
    return result


def fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError("closed authority schema required")


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def name(value):
    return type(value) is str and 0 < len(value.encode()) <= 128 and "\0" not in value


def hex_value(value, length=64):
    return (
        type(value) is str
        and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None
    )


def roots(value):
    if (
        type(value) is not list
        or len(value) > 4096
        or any(not hex_value(v) for v in value)
        or value != sorted(set(value))
    ):
        raise ValueError("canonical bounded root list required")


def integer(value):
    return type(value) is int and 0 <= value < 2**63


def validate_state(state, previous=None):
    fields(
        state,
        (
            "schema",
            "authority_id",
            "membership_sha256",
            "scope",
            "sequence",
            "previous_sha256",
            "frontier",
            "placements",
        ),
    )
    if (
        state["schema"] != SCHEMA
        or not name(state["authority_id"])
        or not name(state["scope"])
        or not integer(state["sequence"])
        or state["sequence"] == 0
        or not hex_value(state["membership_sha256"])
        or not hex_value(state["previous_sha256"])
    ):
        raise ValueError("invalid authority state identity")
    if len(encode(state)) > MAX_STATE_BYTES:
        raise ValueError("authority state exceeds byte budget")
    view = state["frontier"]
    fields(view, ("scope", "epoch", "revoked"))
    if view["scope"] != state["scope"] or not integer(view["epoch"]):
        raise ValueError("invalid authority frontier")
    roots(view["revoked"])
    placements = state["placements"]
    if type(placements) is not list or len(placements) > 64:
        raise ValueError("bounded placement inventory required")
    old = {p["cell_id"]: p for p in previous["placements"]} if previous else {}
    ids = []
    for item in placements:
        fields(
            item,
            ("scope", "cell_id", "node_id", "generation", "manifest_sha256", "roots"),
        )
        if (
            item["scope"] != state["scope"]
            or not name(item["cell_id"])
            or not name(item["node_id"])
            or not integer(item["generation"])
            or not hex_value(item["manifest_sha256"])
        ):
            raise ValueError("invalid authority placement")
        roots(item["roots"])
        ids.append(item["cell_id"])
        prior = old.get(item["cell_id"])
        if previous is not None and prior is None and item["generation"] != 0:
            raise ValueError("new placement must start at generation zero")
        if (
            prior is not None
            and item != prior
            and item["generation"] != prior["generation"] + 1
        ):
            raise ValueError("placement must advance exactly once")
        if (
            previous is not None
            and item != prior
            and set(item["roots"]) & set(view["revoked"])
        ):
            raise ValueError("new placement includes a withdrawn ancestor")
    if ids != sorted(set(ids)) or not set(old) <= set(ids):
        raise ValueError(
            "placements must be sorted, unique and retain identity history"
        )
    if previous:
        if (
            any(
                state[key] != previous[key]
                for key in ("authority_id", "membership_sha256", "scope")
            )
            or state["sequence"] != previous["sequence"] + 1
        ):
            raise ValueError("authority identity or sequence changed")
        prior_view = previous["frontier"]
        if (
            view["epoch"] < prior_view["epoch"]
            or not set(prior_view["revoked"]) <= set(view["revoked"])
            or (view["epoch"] == prior_view["epoch"] and view != prior_view)
        ):
            raise ValueError("withdrawal frontier rollback or same-epoch fork")
    return state


def verify_signature(public_key, signature, message):
    if not hex_value(public_key) or not hex_value(signature, 128):
        raise ValueError("invalid Ed25519 key or signature encoding")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(signature), message
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("authority signature verification failed") from error


@dataclass(frozen=True)
class Membership:
    authority_id: str
    writer_key: str
    member_keys: dict

    def __post_init__(self):
        if (
            not name(self.authority_id)
            or not hex_value(self.writer_key)
            or type(self.member_keys) is not dict
            or not 3 <= len(self.member_keys) <= 7
            or any(not name(k) or not hex_value(v) for k, v in self.member_keys.items())
            or len(set(self.member_keys.values())) != len(self.member_keys)
        ):
            raise ValueError("fixed bounded authority membership required")
        object.__setattr__(
            self, "member_keys", MappingProxyType(dict(self.member_keys))
        )

    @property
    def quorum(self):
        return len(self.member_keys) // 2 + 1

    @property
    def sha256(self):
        return digest(
            dict(
                authority_id=self.authority_id,
                writer_key=self.writer_key,
                member_keys=dict(self.member_keys),
            )
        )

    def propose(self, state, private_key):
        if private_key.public_key().public_bytes_raw().hex() != self.writer_key:
            raise ValueError("writer key is not in the fixed membership")
        result = dict(
            state=state,
            signature=private_key.sign(
                b"hepta-memory-proposal-v1\0" + encode(state)
            ).hex(),
        )
        self.verify_proposal(result)
        return result

    def verify_proposal(self, proposal):
        fields(proposal, ("state", "signature"))
        state = proposal["state"]
        # History-dependent checks are additionally applied by the durable replica.
        validate_state(state)
        if (
            state["authority_id"] != self.authority_id
            or state["membership_sha256"] != self.sha256
            or len(encode(state)) > MAX_STATE_BYTES
        ):
            raise ValueError("proposal has a different authority or membership")
        verify_signature(
            self.writer_key,
            proposal["signature"],
            b"hepta-memory-proposal-v1\0" + encode(state),
        )
        return state

    def vote(self, proposal, member_id, private_key):
        self.verify_proposal(proposal)
        if (
            self.member_keys.get(member_id)
            != private_key.public_key().public_bytes_raw().hex()
        ):
            raise ValueError("replica key is not in the fixed membership")
        pin = digest(proposal)
        return dict(
            member_id=member_id,
            proposal_sha256=pin,
            signature=private_key.sign(
                b"hepta-memory-vote-v1\0" + bytes.fromhex(pin)
            ).hex(),
        )

    def certificate(self, proposal, votes):
        result = dict(
            proposal=proposal, votes=sorted(votes, key=lambda v: v["member_id"])
        )
        self.verify_certificate(result)
        return result

    def verify_certificate(self, certificate):
        fields(certificate, ("proposal", "votes"))
        state = self.verify_proposal(certificate["proposal"])
        votes = certificate["votes"]
        if type(votes) is not list or not self.quorum <= len(votes) <= len(
            self.member_keys
        ):
            raise ValueError("certificate lacks a bounded majority")
        seen, pin = set(), digest(certificate["proposal"])
        for vote in votes:
            fields(vote, ("member_id", "proposal_sha256", "signature"))
            member = vote["member_id"]
            if (
                member in seen
                or member not in self.member_keys
                or vote["proposal_sha256"] != pin
            ):
                raise ValueError("duplicate, unknown or mismatched replica vote")
            verify_signature(
                self.member_keys[member],
                vote["signature"],
                b"hepta-memory-vote-v1\0" + bytes.fromhex(pin),
            )
            seen.add(member)
        return state
