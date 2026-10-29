"""Independent canonical trust and typed fact reconstruction, then Ed25519.

These encodings follow the unchanged production.rs, causal_v2.rs,
signed_evidence.rs and trust_distribution.rs formats. Four-byte causal IDs and
eight-byte production IDs are deliberately distinct protocol representations.
"""

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def hashed(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).digest()


def number(value, width=8, *, signed=False):
    return int(value).to_bytes(width, "big", signed=signed)


def identifier(value, width=8):
    encoded = value.encode()
    return number(len(encoded), width) + encoded


class TrustReference:
    def __init__(self, fixture):
        self.fixture = fixture
        self.keys = {
            role: Ed25519PrivateKey.from_private_bytes(bytes(fixture[role + "_seed"]))
            .public_key()
            .public_bytes_raw()
            for role in ("root", "generator", "observer", "allocator")
        }
        self.scope = hashed(
            "user-authorized-local-research-credit:" + fixture["study_digest"]
        )
        self.objective = hashed("adaptive-credit-bridge.bernoulli-terminal-utility.v1")
        self.roles = {
            "generator": (0, "Generator"),
            "observer": (1, "Observer"),
            "allocator": (3, "CreditAllocator"),
        }
        encoded = (
            b"hepta.learning-ledger.evidence-trust.v1"
            + self.scope
            + self.objective
            + number(1)
            + number(3)
        )
        for role in sorted(self.roles):
            encoded += identifier("research-" + role) + identifier(
                "local-research-" + role + "-controller"
            )
            encoded += (
                self.credential(role) + self.keys[role] + number(10) + number(200)
            )
            encoded += number(1) + bytes([self.roles[role][0], 0])
        self.digest = hashed(encoded)
        self.distribution = (
            b"hepta.learning-ledger.trust-distribution-signature.v1"
            + identifier("local-research-root")
            + identifier("local-research-trust-distribution")
            + number(1)
            + number(20)
            + number(15)
            + number(90)
            + self.digest
            + self.scope
            + self.objective
            + number(1)
        )

    def credential(self, role):
        return hashed(f"{self.fixture['study_digest']}:{role}:ephemeral-credential")

    def principal(self, role, width=8):
        return (
            identifier("research-" + role, width)
            + self.credential(role)
            + hashed(self.keys[role])
            + self.scope
            + number(1)
            + number(10)
            + number(200)
        )

    def verify_trust(self, trust):
        expected = [
            {
                "principal": "research-" + role,
                "controller": "local-research-" + role + "-controller",
                "verifying_key": self.keys[role].hex(),
                "roles": "[" + self.roles[role][1] + "]",
            }
            for role in ("generator", "observer", "allocator")
        ]
        if (
            trust["signers"] != expected
            or bytes.fromhex(trust["distribution_signing_bytes"]) != self.distribution
            or trust["root_verifying_key"] != self.keys["root"].hex()
            or trust["scope_digest"] != self.scope.hex()
            or trust["objective_digest"] != self.objective.hex()
            or not trust["research_only"]
            or trust["organizational_independence_claimed"]
        ):
            raise AssertionError(
                "Presented trust differs from the independently encoded fixture distribution"
            )
        Ed25519PublicKey.from_public_bytes(self.keys["root"]).verify(
            bytes.fromhex(trust["distribution_signature"]), self.distribution
        )

    def signing_bytes(self, proof):
        role = proof["principal"].removeprefix("research-")
        tag, label = self.roles[role]
        payload_digest = hashed(bytes.fromhex(proof["payload_bytes"]))
        expected_id = "research-" + role + "-" + payload_digest.hex()
        if (
            proof["role"] != label
            or proof["evidence_id"] != expected_id
            or proof["payload_digest"] != payload_digest.hex()
            or proof["verifying_key"] != self.keys[role].hex()
        ):
            raise AssertionError(
                "Evidence metadata differs from the admitted signer and payload"
            )
        encoded = (
            b"hepta.learning-ledger.signed-evidence.v1"
            + identifier(expected_id)
            + identifier("research-" + role)
            + bytes([tag])
            + self.digest
            + self.scope
            + self.objective
            + number(1)
            + number(20)
            + number(90)
            + payload_digest
        )
        if encoded != bytes.fromhex(proof["signing_bytes"]):
            raise AssertionError(
                "Evidence signature scope, role, identity or validity binding differs"
            )
        return encoded, self.keys[role]

    def fact_payload(self, record):
        fact = record["fact"]
        case, record_id = fact["episode"], record["record_id"]
        support = bytes.fromhex(fact["support_digest"])
        if fact["kind"] == "AuthenticatedDecisionV2":
            candidates = ["abstain", "execute-trained-readout"]
            encoded_ids = number(2) + b"".join(
                identifier(value) for value in candidates
            )
            candidates_digest = hashed(
                b"hepta.learning-ledger.candidate-ids.v2" + encoded_ids
            )
            order_digest = hashed(
                b"hepta.learning-ledger.candidate-order.v2" + encoded_ids
            )
            completeness = (
                b"hepta.learning-ledger.candidate-completeness.v1"
                + identifier(case + ".admission-candidates", 4)
                + support
                + identifier("research-generator", 4)
                + hashed("adaptive-credit-bridge-explicit-admission-generator.v1")
                + hashed("abstain-or-execute-task.v1")
                + hashed("authorized-local-research-only.v1")
                + hashed("no-admission-candidate-truncation.v1")
                + candidates_digest
                + number(2, 4)
                + number(0, 4)
                + order_digest
                + b"\x01"
            )
            if (
                fact["generator"] != "research-generator"
                or fact["selected_candidate"] != "execute-trained-readout"
            ):
                raise AssertionError(
                    "Signed admission role or selected candidate differs"
                )
            return (
                b"hepta.learning-ledger.production-decision.v2"
                + identifier(record_id)
                + identifier(case)
                + bytes.fromhex(fact["run_snapshot_digest"])
                + self.objective
                + bytes.fromhex(fact["policy_digest"])
                + hashed(completeness)
                + encoded_ids
                + identifier(fact["selected_candidate"])
                + number(1 << 32)
                + support
            )
        if fact["kind"] == "AuthenticatedOutcomeV2":
            if fact["observer"] != "research-observer":
                raise AssertionError("Outcome observer differs")
            return (
                b"hepta.learning-ledger.production-outcome.v2"
                + identifier(record_id)
                + identifier(fact["outcome"])
                + identifier(case)
                + self.principal("observer")
                + b"\x01"
                + number(40)
                + b"\x01"
                + number(fact["value_q32"], signed=True)
                + hashed("bernoulli-terminal-reward-q32.v1")
                + support
                + number(45)
                + hashed("synthetic-outcome-observed-immediately.v1")
                + b"\x02\x00\x00\x01"
                + number(46)
            )
        if fact["kind"] == "CreditBatchV2":
            if fact["allocator"] != "research-allocator":
                raise AssertionError("Credit allocator differs")
            allocations = sorted(fact["allocations"], key=lambda item: item["organ"])
            encoded = (
                b"hepta.learning-ledger.credit-allocation-batch.v1"
                + identifier(record_id, 4)
                + identifier(case, 4)
                + identifier(fact["outcome"], 4)
                + self.principal("allocator", 4)
                + number(fact["value_q32"], signed=True)
                + number(len(allocations), 4)
                + b"".join(
                    identifier(item["organ"], 4)
                    + number(item["credit_q32"], signed=True)
                    for item in allocations
                )
                + number(fact["residual_q32"], signed=True)
                + support
                + b"\x01"
            )
            return (
                b"hepta.learning-ledger.production-credit-batch.v2"
                + hashed(encoded)
                + identifier(record_id)
                + identifier(case)
                + identifier(fact["outcome"])
                + self.principal("allocator")
            )
        raise AssertionError("Unexpected signed ledger fact type")


def verify_fact(record, proofs, reference):
    proof = proofs[record["fact"]["authentication_digest"]]
    if reference.fact_payload(record) != bytes.fromhex(proof["payload_bytes"]):
        raise AssertionError(
            "Typed ledger fact differs from its independently reconstructed signed payload"
        )


def cryptographic_proofs(rows, fixture):
    reference = TrustReference(fixture)
    verified, rejected, roots, authentications = 0, 0, 0, {}
    for row in rows:
        if not row["response"]["ok"]:
            continue
        response = row["response"]["result"]
        reference.verify_trust(response["trust_proof"])
        roots += 1
        for proof in response.get("signed_evidence", []):
            signing, key = reference.signing_bytes(proof)
            signature = bytes.fromhex(proof["signature"])
            try:
                Ed25519PublicKey.from_public_bytes(key).verify(signature, signing)
            except InvalidSignature:
                if not proof["deliberately_corrupted_fixture"]:
                    raise
                rejected += 1
            else:
                if proof["deliberately_corrupted_fixture"]:
                    raise AssertionError("Corrupted signature unexpectedly verified")
                verified += 1
                authentications[hashed(signing + signature).hex()] = proof
    return {
        "verified_evidence_signatures": verified,
        "rejected_corrupted_signatures": rejected,
        "verified_root_signatures": roots,
        "trust_and_evidence_canonical_bindings_reconstructed": True,
    }, authentications
