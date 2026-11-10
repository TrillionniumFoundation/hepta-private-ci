"""Separate bounded replay strata and a conflicting-workflow diagnostic.

These are supervised synthetic sequences, not factual truth, skill compression
or native ACT outcomes. Replay reuses observed training labels. The caller's
scope/version map is an offline contract, not a signature or owner grant.
"""

from dataclasses import dataclass
from pathlib import Path
import time
import numpy as np

try:
    from .credit import Model, copy_episode, make_model, gradient, propose, forward
    from .learning_clocks import model_payload
    from .protocol import canonical_digest, source_inventory
except ImportError:
    from credit import Model, copy_episode, make_model, gradient, propose, forward
    from learning_clocks import model_payload
    from protocol import canonical_digest, source_inventory


KINDS = ("fact", "episode", "procedure", "error")
POLICIES = ("none", "uniform", *KINDS, "error_prioritized")
RULE = "hepta.memory-replay.fp64.v1"
SOURCE_DIGEST = source_inventory(
    Path(__file__).parent,
    ("memory_replay.py", "learning_clocks.py", "credit.py", "protocol.py"),
)["digest"]


@dataclass(frozen=True)
class ReplayItem:
    item_id: str
    scope: str
    source: str
    task_id: str
    version: str
    split: str
    kind: str
    priority: float
    episode: tuple

    def __post_init__(self):
        if any(
            not isinstance(v, str) or not v or len(v) > 160
            for v in (
                self.item_id,
                self.scope,
                self.source,
                self.task_id,
                self.version,
                self.split,
            )
        ):
            raise ValueError("bounded nonempty provenance fields required")
        if (
            self.kind not in KINDS
            or not np.isfinite(self.priority)
            or self.priority < 0
        ):
            raise ValueError("invalid replay stratum or observed loss")
        arrays = [np.array(v, dtype=float, copy=True) for v in self.episode]
        if len(arrays) != 4 or not 1 <= len(arrays[0]) <= 32:
            raise ValueError("bounded complete episode required")
        n = len(arrays[0])
        if [a.shape for a in arrays] != [(n, 2), (n, 1), (n,), (n, 7)]:
            raise ValueError("replay episode shape mismatch")
        if any(not np.isfinite(a).all() or np.max(np.abs(a)) > 8 for a in arrays):
            raise ValueError("replay values outside bounds")
        if np.any(arrays[2] < 0) or not np.isclose(
            arrays[2].sum(), 1, rtol=0, atol=1e-12
        ):
            raise ValueError("replay objective must have unit mass")
        frozen = tuple(
            tuple(tuple(row) for row in a) if a.ndim == 2 else tuple(a) for a in arrays
        )
        object.__setattr__(self, "episode", frozen)

    def arrays(self):
        return tuple(np.array(a, dtype=float) for a in self.episode)

    def payload(self):
        return {
            **{
                k: getattr(self, k)
                for k in (
                    "item_id",
                    "scope",
                    "source",
                    "task_id",
                    "version",
                    "split",
                    "kind",
                )
            },
            "priority": float(self.priority),
            "episode": [a.tolist() for a in self.arrays()],
        }


class ReplayPool:
    """FIFO capacity, current-source checks, deterministic bounded selection."""

    def __init__(self, scope, versions, seed=0, capacity=32):
        if not isinstance(scope, str) or not scope or len(scope) > 160:
            raise ValueError("scope required")
        if type(capacity) is not int or not 1 <= capacity <= 256:
            raise ValueError("capacity must be 1..256")
        if not 1 <= len(versions) <= 64 or any(
            not isinstance(v, str) or not v or len(v) > 160
            for pair in versions.items()
            for v in pair
        ):
            raise ValueError("bounded source versions required")
        self.scope, self.versions, self.capacity = scope, dict(versions), capacity
        self.items, self.calls, self.presentations, self.timesteps = [], 0, 0, 0
        self.numeric_payload_bytes = 0
        self.distinct = set()
        self.rng = np.random.default_rng(seed)

    def add(self, item):
        if item.scope != self.scope or item.split != "train":
            raise ValueError("replay refuses cross-scope and non-training records")
        if self.versions.get(item.source) != item.version:
            raise ValueError("replay source version is stale or unknown")
        for existing in self.items:
            if existing.item_id == item.item_id:
                if existing.payload() != item.payload():
                    raise ValueError("replay identity reused with different content")
                return
        self.items = (self.items + [item])[-self.capacity :]

    def update_version(self, source, version):
        if (
            source not in self.versions
            or not isinstance(version, str)
            or not version
            or len(version) > 160
        ):
            raise ValueError("known source and bounded version required")
        self.versions[source] = version
        self.items = [e for e in self.items if self.versions[e.source] == e.version]

    def select(self, policy, entry_budget=1, timestep_budget=8, *, audit=False):
        if (
            policy not in POLICIES
            or type(entry_budget) is not int
            or not 0 <= entry_budget <= 32
        ):
            raise ValueError("invalid policy or entry budget")
        if (
            type(timestep_budget) is not int
            or not 0 <= timestep_budget <= 1024
            or self.calls >= 4096
        ):
            raise ValueError("selection budget exhausted or invalid")
        if type(audit) is not bool:
            raise ValueError("audit flag must be boolean")
        rng_before = canonical_digest(self.rng.bit_generator.state) if audit else None
        kind = "error" if policy == "error_prioritized" else policy
        candidates = [e for e in self.items if policy == "uniform" or e.kind == kind]
        if policy == "none":
            candidates = []
        if policy == "error_prioritized":
            candidates.sort(key=lambda e: (-e.priority, e.item_id))
        else:
            candidates = [candidates[i] for i in self.rng.permutation(len(candidates))]
        selected, steps = [], 0
        for item in candidates:
            length = len(item.episode[0])
            if len(selected) < entry_budget and steps + length <= timestep_budget:
                selected.append(item)
                steps += length
        self.calls += 1
        self.presentations += len(selected)
        self.timesteps += steps
        self.numeric_payload_bytes += sum(
            a.nbytes for e in selected for a in e.arrays()
        )
        self.distinct.update(e.item_id for e in selected)
        if not audit:
            return selected
        # Capture the *eligible, ordered pool at decision time*, not the final
        # checkpoint (which may have evicted old-priority observations).
        # This is a local consistency receipt, not an authenticated owner proof.
        candidates_at_selection = [
            {
                "item_id": e.item_id,
                "scope": e.scope,
                "source": e.source,
                "version": e.version,
                "split": e.split,
                "kind": e.kind,
                "priority": float(e.priority),
                "timesteps": len(e.episode[0]),
                "payload_digest": canonical_digest(e.payload()),
            }
            for e in candidates
        ]
        receipt = {
            "schema": "hepta.replay-selection-audit.v1",
            "policy": policy,
            "scope": self.scope,
            "versions": dict(self.versions),
            "selection_index": self.calls,
            "entry_budget": entry_budget,
            "timestep_budget": timestep_budget,
            "rng_before_digest": rng_before,
            "rng_after_digest": canonical_digest(self.rng.bit_generator.state),
            "ordered_candidates": candidates_at_selection,
            "selected_ids": [e.item_id for e in selected],
            "eligible_candidate_reads": len(candidates),
            "priority_value_reads": len(candidates)
            if policy == "error_prioritized"
            else 0,
            "candidate_payload_digests_computed": len(candidates),
            "decision_timesteps": steps,
            "authority": "SYNTHETIC_CONSISTENCY_ONLY",
        }
        receipt["digest"] = canonical_digest(receipt)
        return selected, receipt

    def checkpoint(self):
        p = {
            "schema": RULE,
            "source_digest": SOURCE_DIGEST,
            "scope": self.scope,
            "versions": dict(self.versions),
            "capacity": self.capacity,
            "items": [e.payload() for e in self.items],
            "rng": self.rng.bit_generator.state,
            "calls": self.calls,
            "presentations": self.presentations,
            "timesteps": self.timesteps,
            "numeric_payload_bytes": self.numeric_payload_bytes,
            "distinct": sorted(self.distinct),
        }
        return {"payload": p, "digest": canonical_digest(p)}

    @classmethod
    def restore(cls, checkpoint, scope, versions):
        p = checkpoint["payload"]
        if (
            checkpoint["digest"] != canonical_digest(p)
            or p["schema"] != RULE
            or p["source_digest"] != SOURCE_DIGEST
        ):
            raise ValueError("replay checkpoint changed")
        if p["scope"] != scope or p["versions"] != versions:
            raise ValueError("replay checkpoint belongs to a different source context")
        pool = cls(scope, versions, capacity=p["capacity"])
        if len(p["items"]) > pool.capacity:
            raise ValueError("checkpoint over capacity")
        for entry in p["items"]:
            pool.add(ReplayItem(**entry))
        if len(pool.items) != len(p["items"]):
            raise ValueError("duplicate checkpoint identities")
        for key, cap in (
            ("calls", 4096),
            ("presentations", 4096 * 32),
            ("timesteps", 4096 * 1024),
            ("numeric_payload_bytes", 4096 * 1024 * 88),
        ):
            if type(p[key]) is not int or not 0 <= p[key] <= cap:
                raise ValueError("invalid checkpoint accounting")
            setattr(pool, key, p[key])
        if len(p["distinct"]) > p["presentations"] or len(set(p["distinct"])) != len(
            p["distinct"]
        ):
            raise ValueError("invalid distinct replay accounting")
        pool.distinct = set(p["distinct"])
        pool.rng.bit_generator.state = p["rng"]
        return pool


def verify_priority_selection_audit(receipt):
    """Recheck one historical priority decision without a current replay pool.

    This proves internal order/selection consistency for recorded candidate
    priorities. It does *not* establish that priorities came from real observed
    losses, that the candidate list was exhaustive, or owner authentication.
    """
    if not isinstance(receipt, dict) or receipt.get("policy") != "error_prioritized":
        raise ValueError("only priority audit receipts support this verification")
    payload = {key: value for key, value in receipt.items() if key != "digest"}
    if receipt.get("digest") != canonical_digest(payload):
        raise ValueError("priority audit digest mismatch")
    if (
        receipt.get("schema") != "hepta.replay-selection-audit.v1"
        or receipt.get("authority") != "SYNTHETIC_CONSISTENCY_ONLY"
        or not isinstance(receipt.get("scope"), str)
        or not receipt["scope"]
        or type(receipt.get("selection_index")) is not int
        or not 1 <= receipt["selection_index"] <= 4096
        or type(receipt.get("entry_budget")) is not int
        or not 0 <= receipt["entry_budget"] <= 32
        or type(receipt.get("timestep_budget")) is not int
        or not 0 <= receipt["timestep_budget"] <= 1024
    ):
        raise ValueError("invalid priority audit contract")
    candidates = receipt.get("ordered_candidates")
    versions = receipt.get("versions")
    if (
        not isinstance(candidates, list)
        or not isinstance(versions, dict)
        or len(candidates) > 256
        or receipt.get("eligible_candidate_reads") != len(candidates)
        or receipt.get("priority_value_reads") != len(candidates)
        or receipt.get("candidate_payload_digests_computed") != len(candidates)
    ):
        raise ValueError("priority audit accounting mismatch")
    ids = [e.get("item_id") for e in candidates if isinstance(e, dict)]
    if len(ids) != len(candidates) or len(set(ids)) != len(ids):
        raise ValueError("duplicate or invalid priority candidates")
    for entry in candidates:
        if (
            not isinstance(entry["item_id"], str)
            or not entry["item_id"]
            or entry.get("scope") != receipt["scope"]
            or entry.get("split") != "train"
            or entry.get("kind") != "error"
            or versions.get(entry.get("source")) != entry.get("version")
            or not isinstance(entry.get("payload_digest"), str)
            or len(entry["payload_digest"]) != 64
            or type(entry.get("timesteps")) is not int
            or not 1 <= entry["timesteps"] <= 32
            or not isinstance(entry.get("priority"), (int, float))
            or not np.isfinite(entry["priority"])
            or entry["priority"] < 0
        ):
            raise ValueError("ineligible historical candidate")
    if candidates != sorted(candidates, key=lambda e: (-e["priority"], e["item_id"])):
        raise ValueError("priority candidates not in declared order")
    selected, steps = [], 0
    for entry in candidates:
        n = entry["timesteps"]
        if len(selected) < receipt["entry_budget"] and steps + n <= receipt["timestep_budget"]:
            selected.append(entry["item_id"])
            steps += n
    if receipt.get("selected_ids") != selected or receipt.get("decision_timesteps") != steps:
        raise ValueError("historical priority decision mismatched candidate ordering")
    return True


def replay_specs(seeds=(11, 29, 47)):
    specs = []
    for seed in seeds:
        if type(seed) is not int or seed < 0:
            raise ValueError("nonnegative seed required")
        for method in POLICIES:
            s = {
                "family": "memory_replay",
                "method": method,
                "seed": seed,
                "warmup": 16,
                "steps": 16,
                "entry_budget": 1,
                "timestep_budget": 8,
            }
            specs.append({**s, "attempt_id": "replay:" + canonical_digest(s)[:24]})
    return specs


def make_item(seed, index, phase=0, split="train"):
    """Four distinct fixed-length mechanisms; changed workflow has a new version."""
    if (
        type(seed) is not int
        or not 0 <= seed < 2**32
        or type(index) is not int
        or not 0 <= index < 4096
        or type(phase) is not int
        or phase not in (0, 1)
        or split not in ("train", "holdout")
    ):
        raise ValueError(
            "bounded seed/index, phase 0/1 and train/holdout split required"
        )
    kind = KINDS[index % 4]
    x, y, f, m = copy_episode(
        np.random.default_rng(
            np.random.SeedSequence(
                [seed, 712903, index, phase, int(split == "holdout")]
            )
        ),
        8,
    )
    cue = float(y[0, 0])
    if kind == "fact":
        # Preserve each example's nuisance variation instead of collapsing every
        # fact sequence to one of the two cue-sign payloads.
        x[1:, 0] += cue
    elif kind == "procedure":
        x[1::2, 0] = -cue * 0.2
    elif kind == "error":
        x[0, 0], x[-2, 0] = -cue, cue
    changed = phase and kind in ("procedure", "error")
    if changed:
        y = -y
    return ReplayItem(
        f"{split}:{phase}:{index}:{seed}",
        "synthetic",
        kind,
        f"{kind}:phase{phase}",
        "v2" if changed else "v1",
        split,
        kind,
        0.0,
        (x, y, f, m),
    )


def raw_fingerprints(item):
    """Hash numerical arrays only; identity/split labels never establish separation."""
    x, y, feedback, messages = item.arrays()
    return {
        "input_message_sha256": canonical_digest(
            {"inputs": x.tolist(), "messages": messages.tolist()}
        ),
        "supervised_payload_sha256": canonical_digest(
            [a.tolist() for a in (x, y, feedback, messages)]
        ),
    }


def audit_replay_splits(train, probes):
    """Reject shared raw observations even when their labels or IDs differ."""
    if (
        not train
        or not probes
        or any(e.split != "train" for e in train)
        or any(e.split != "holdout" for e in probes)
    ):
        raise ValueError("nonempty training and holdout sequences required")
    rows = {
        name: [
            {"item_id": e.item_id, "kind": e.kind, **raw_fingerprints(e)}
            for e in entries
        ]
        for name, entries in (("train", train), ("probe", probes))
    }
    overlaps = {
        key: sorted({e[key] for e in rows["train"]} & {e[key] for e in rows["probe"]})
        for key in ("input_message_sha256", "supervised_payload_sha256")
    }
    if any(overlaps.values()):
        raise ValueError(
            "cross-split raw-array overlap: "
            + str({key: len(value) for key, value in overlaps.items()})
        )
    return {
        "schema": "hepta.replay-raw-split-audit.v1",
        "fingerprint_scope": "numerical_arrays_only_excludes_identity_scope_version_kind_and_split",
        "fingerprints": rows,
        "cross_split_overlaps": overlaps,
        "unique_input_payloads_by_kind": {
            name: {
                kind: len(
                    {e["input_message_sha256"] for e in values if e["kind"] == kind}
                )
                for kind in KINDS
            }
            for name, values in rows.items()
        },
        "passed": True,
    }


def run_replay_attempt(spec):
    if spec not in replay_specs((spec["seed"],)):
        raise ValueError("replay specification mismatch")
    started = time.perf_counter()
    model = make_model(spec["seed"])
    initial = model.digest
    pool = ReplayPool("synthetic", dict.fromkeys(KINDS, "v1"), spec["seed"])
    stream = [
        make_item(spec["seed"] + 800, i, phase) for phase in (0, 1) for i in range(16)
    ]
    probes = [
        [make_item(spec["seed"] + 1800, i, phase, "holdout") for i in range(16)]
        for phase in (0, 1)
    ]
    data_audit = audit_replay_splits(stream, [e for group in probes for e in group])
    receipts, selections, probe_losses = [], [], []

    def evaluate():
        return [
            [
                float(
                    0.5
                    * np.sum(
                        item.arrays()[2][:, None]
                        * (
                            forward(model, item.arrays()[0], item.arrays()[3])[1]
                            - item.arrays()[1]
                        )
                        ** 2
                    )
                )
                for item in group
            ]
            for group in probes
        ]

    probe_losses.append(evaluate())
    for position, item in enumerate(stream):
        if position == 16:
            probe_losses.append(evaluate())
        if pool.versions[item.source] != item.version:
            # A source transitions when its first new-version observation arrives.
            pool.update_version(item.source, item.version)
        x, y, f, m = item.arrays()
        result = gradient(model, x, y, f, "bptt", messages=m)
        model, receipt = propose(model, result["gradients"])
        receipts.append(receipt)
        pool.add(ReplayItem(**{**item.payload(), "priority": result["loss"]}))
        if position >= 16:
            chosen, selection_audit = pool.select(
                spec["method"], spec["entry_budget"], spec["timestep_budget"],
                audit=True,
            )
            selections.append(
                {
                    "position": position,
                    "ids": [e.item_id for e in chosen],
                    "selection_audit": selection_audit,
                    "entry_presentations": len(chosen),
                    "timesteps": sum(len(e.episode[0]) for e in chosen),
                    "numeric_payload_bytes": sum(
                        a.nbytes for e in chosen for a in e.arrays()
                    ),
                }
            )
            for selected in chosen:
                x, y, f, m = selected.arrays()
                result = gradient(model, x, y, f, "bptt", messages=m)
                model, receipt = propose(model, result["gradients"])
                receipts.append(receipt)
        if position == 23:
            checkpoint = pool.checkpoint()
            pool = ReplayPool.restore(checkpoint, pool.scope, pool.versions)
            restored_model = Model(**model_payload(model))
            if restored_model.digest != model.digest:
                raise AssertionError("model restoration changed the candidate")
            model = restored_model
    probe_losses.append(evaluate())
    return {
        **spec,
        "status": "completed",
        "scope": "synthetic_supervised_replay_strata",
        "initial_model_digest": initial,
        "final_model_digest": model.digest,
        "data_digest": canonical_digest([e.payload() for e in stream]),
        "data_split_audit": data_audit,
        "data_split_audit_digest": canonical_digest(data_audit),
        "probe_ids": [[e.item_id for e in group] for group in probes],
        "probe_kinds": [[e.kind for e in group] for group in probes],
        "probe_obsolete_workflow": [
            [phase == 0 and e.kind in ("procedure", "error") for e in group]
            for phase, group in enumerate(probes)
        ],
        "probe_losses_initial_mid_final": probe_losses,
        "replay_selections": selections,
        "update_receipts": receipts,
        "replay_presentations": pool.presentations,
        "distinct_replayed_entries": len(pool.distinct),
        "replay_timesteps": pool.timesteps,
        "replay_numeric_payload_bytes": pool.numeric_payload_bytes,
        "unique_training_entries": len(stream),
        "gradient_calls": len(receipts),
        "optimizer_calls": len(receipts),
        "unique_supervision_events": len(stream),
        "total_label_exposures": len(stream) + pool.presentations,
        "label_exposure_unit": "one_terminal_supervision_event_per_gradient_call",
        "replay_byte_scope": "sum_selected_fp64_array_nbytes_per_presentation_not_distinct_or_actual_io",
        "error_stratum": "synthetic_correction_cue_sequences_not_observed_tool_failures",
        "final_model": model_payload(model),
        "final_checkpoint": pool.checkpoint(),
        "wall_seconds": time.perf_counter() - started,
        "energy_joules": None,
        "new_independent_real_tasks": 0,
        "production_adoption": False,
        "limitation": "stratum selection only; no procedural compression or native effect claim",
    }
