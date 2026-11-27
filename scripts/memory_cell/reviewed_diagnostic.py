"""Pinned review-to-reader execution; no reviewer, optimizer or acceptance issuer.

Claimed necessity is consumed as an experimental hypothesis. Model-assisted and
published judgments never become independent human admission. The complete
capability census, including unavailable reviews, stays in every report.
"""

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from bundle_trial import decode_bundle, run_reader, write
from native import digest
from reviewed_bundle import MAX_REVIEW_BYTES, augment, strict_read


class DiagnosticInputs:
    """Externally supplied file identities, not hashes learned from file contents."""

    def __init__(self, paths, pins):
        names = {"plan", "reviews", "withdrawals", "labels", "inventory"}
        if set(paths) != names or set(pins) != names:
            raise ValueError("all five external file pins are required")
        self.paths = {k: Path(v) for k, v in paths.items()}
        self.pins = dict(pins)

    def read(self, name, bound):
        return strict_read(self.paths[name], self.pins[name], bound)

    def withdrawals(self):
        value = self.read("withdrawals", MAX_REVIEW_BYTES)
        if (
            not isinstance(value, list)
            or any(not isinstance(x, str) or not x for x in value)
            or len(set(value)) != len(value)
        ):
            raise ValueError("unique explicit current withdrawal list required")
        return set(value)

    def verify_label_bytes(self):
        # Hash-only preflight: do not parse or expose QA annotations to a reader.
        path = self.paths["labels"]
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("non-symlink label source required")
        with path.open("rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if (
            len(raw) > 64 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != self.pins["labels"]
        ):
            raise ValueError("original QA label byte pin mismatch")


class CurrentReviewReader:
    """Guard every legacy runner call with the externally pinned current view."""

    def __init__(self, reader, withdrawals):
        self.reader = reader
        self.identity = reader.identity
        self.withdrawals = withdrawals

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        current = self.withdrawals()
        bundle.validate(query, originals, frontier=frontier, revoked=current)
        answer, receipt = self.reader.answer(
            query,
            bundle,
            originals,
            frontier=frontier,
            revoked=current,
            token_limit=token_limit,
        )
        bundle.validate(query, originals, frontier=frontier, revoked=self.withdrawals())
        if receipt.get("reader_identity") != self.identity:
            raise ValueError("answer reader differs from declared reader")
        return answer, receipt

    def verify_frozen(self):
        self.reader.verify_frozen()


def capability_plan(plan, package, revoked):
    """Preserve ordinary controls; unavailable reviews are not filtered away."""
    projected = augment(plan, package, revoked=revoked)
    for old, new in zip(plan["cases"], projected["cases"], strict=True):
        if any(new["conditions"].get(k) != v for k, v in old["conditions"].items()):
            raise ValueError("review changed an ordinary retrieval control")
        if any(d["root"] in revoked for d in old["originals"]):
            raise ValueError("withdrawn original view")
    cases = [c for c in projected["cases"] if c["phase"] == "capability"]
    ids = [c["question"]["identity"] for c in cases]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("unique nonempty capability census required")
    declared = plan.get("frozen_counts", {}).get("capability", len(ids))
    if type(declared) is not int or declared != len(ids):
        raise ValueError("capability cohort differs from original frozen horizon")
    by_id = {c["question"]["identity"]: c for c in plan["cases"]}
    for case in cases:
        original = by_id[case["question"]["identity"]]
        # Match the already registered empty/control budget, not a new larger
        # context budget that would confound evidence and reader comparisons.
        empty = original["conditions"].get("empty")
        if not empty or empty.get("status") == "unavailable":
            raise ValueError("original empty-evidence control is required")
        budget = empty.get("token_limit")
        if budget not in (1024, 2048, 4096) or type(budget) is not int:
            raise ValueError("unregistered control budget")
        for name, condition in case["conditions"].items():
            if name not in original["conditions"] and "bundle" in condition:
                condition["token_limit"] = budget
        full = case["conditions"].setdefault(
            "reviewed_minimal",
            dict(status="unavailable", reason="no_external_minimality_claim"),
        )
        if full.get("status") == "unavailable":
            case["conditions"]["reviewed_reversed"] = dict(full)
        else:
            b = decode_bundle(full)
            reversed_bundle = replace(b, selected=tuple(reversed(b.selected)))
            case["conditions"]["reviewed_reversed"] = full | dict(
                bundle=asdict(reversed_bundle),
                bundle_digest=reversed_bundle.seal(),
                delivered_evidence=reversed_bundle.delivered(),
            )
    projected["cases"] = cases
    return projected


def outcome(plan, package, records):
    """Compute a numeric screen only; even perfect scores cannot mint review."""
    from composition_policy import GATE

    wanted = {
        (c["question"]["identity"], a) for c in plan["cases"] for a in c["conditions"]
    }
    keys = [(r["question_id"], r["arm"]) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != wanted:
        raise ValueError("incomplete or duplicate reviewed-reader census")
    profiles = set()
    for row in records:
        if row["status"] not in ("succeeded", "failed", "unavailable"):
            raise ValueError("unknown execution state")
        value = row.get("f1")
        if row["status"] == "succeeded":
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError("successful capability answer lacks a finite score")
            profiles.add(
                (row["receipt"]["reader_identity"], row["receipt"]["reader_profile"])
            )
        elif value is not None:
            raise ValueError("unexecuted answer cannot have a score")
    if len(profiles) > 1:
        raise ValueError("mixed reader or decoding profile")
    means = {}
    for arm in ("reviewed_minimal", "reviewed_reversed", "empty"):
        rows = [r for r in records if r["arm"] == arm]
        means[arm] = sum(r.get("f1") or 0 for r in rows) / len(plan["cases"])
    bases = {}
    for c in plan["cases"]:
        basis = (
            package["reviews"]
            .get(c["question"]["identity"], {})
            .get("review_basis", "missing")
        )
        bases[basis] = bases.get(basis, 0) + 1
    all_succeeded = all(r["status"] == "succeeded" for r in records)
    numeric = (
        len(plan["cases"]) == GATE["cases_required"]
        and all_succeeded
        and means["reviewed_minimal"] >= GATE["full_f1_minimum"]
        and means["reviewed_reversed"] >= GATE["reversed_f1_minimum"]
        and means["reviewed_minimal"] - means["empty"] >= GATE["evidence_gain_minimum"]
    )
    return dict(
        schema="hepta.memory.reviewed-reader.outcome.v1",
        original_quality_thresholds=dict(GATE),
        means_with_unavailable_zero=means,
        planned=len(records),
        succeeded=sum(r["status"] == "succeeded" for r in records),
        unavailable=sum(r["status"] == "unavailable" for r in records),
        failed=sum(r["status"] == "failed" for r in records),
        review_bases=bases,
        numeric_screen_passed=numeric,
        review_identity_authenticated=False,
        independent_sufficiency_certified=False,
        training_permitted=False,
        optimizer_executed=False,
        production_accepted=False,
        next_action="independent_review_required"
        if numeric
        else "repair_evidence_or_reader_before_learning",
    )


def execute(inputs, model_path, output, *, reader_factory=None):
    plan = inputs.read("plan", 64 * 1024 * 1024)
    package = inputs.read("reviews", MAX_REVIEW_BYTES)
    projected = capability_plan(plan, package, inputs.withdrawals())
    inputs.verify_label_bytes()
    inventory = inputs.read("inventory", 1024 * 1024)
    if not isinstance(inventory, dict) or "inventory_digest" not in inventory:
        raise ValueError("pinned model inventory required")
    if reader_factory is None:
        from bundle_reader import FrozenBundleReader

        reader_factory = FrozenBundleReader
    reader = reader_factory(
        model_path, expected_inventory=inventory["inventory_digest"]
    )
    output = Path(output)
    output.mkdir()
    write(output / "reviewed-plan.json", projected)
    write(output / "input-pins.json", inputs.pins)
    raw = (output / "reviewed-plan.json").read_bytes()
    run_reader(
        output / "reviewed-plan.json",
        inputs.paths["labels"],
        CurrentReviewReader(reader, inputs.withdrawals),
        output / "execution",
        plan_sha=hashlib.sha256(raw).hexdigest(),
        labels_sha=inputs.pins["labels"],
    )
    import json

    records = json.loads((output / "execution/scored-answers.json").read_text())
    result = outcome(projected, package, records)
    result["input_pins"] = inputs.pins
    result["projected_plan_digest"] = digest(projected)
    write(output / "reviewed-diagnostic.json", result)
    return result
