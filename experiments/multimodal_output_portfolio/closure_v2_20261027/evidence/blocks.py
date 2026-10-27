"""Joint evidence blocks, with capture identity distinct from content identity."""

from dataclasses import dataclass
import hashlib
import json

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Capture:
    """A trusted acquisition identity; equal content does not equate captures."""

    source: str
    acquisition: str
    content_sha256: str

    def __post_init__(self):
        if not isinstance(self.source, str) or not isinstance(self.acquisition, str) or not self.source or not self.acquisition:
            raise ValueError("An acquisition source and identity are required")
        if not isinstance(self.content_sha256, str) or len(self.content_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.content_sha256):
            raise ValueError("Invalid content commitment")

    @property
    def event_id(self):
        return sha({"source": self.source, "acquisition": self.acquisition})


class JointLaw:
    """A normalized finite likelihood over all registered views and targets."""

    def __init__(self, table, views):
        self.table = np.asarray(table, dtype=np.float64).copy()
        self.views = tuple(views)
        if len(set(self.views)) != len(self.views) or len(self.views) != self.table.ndim-1:
            raise ValueError("Each observation axis needs one unique public view")
        flat = self.table.reshape(-1, self.table.shape[-1])
        self.known = np.isfinite(flat).all(0)
        if not np.isnan(flat[:, ~self.known]).all():
            raise ValueError("Unknown targets must have entirely unknown columns")
        if np.any(flat[:, self.known] < 0) or not np.allclose(flat[:, self.known].sum(0), 1,
                                                           rtol=0, atol=1e-10):
            raise ValueError("Measured target columns must be normalized likelihoods")
        self.table.setflags(write=False)
        self.known.setflags(write=False)

    def marginal(self, observed):
        if not set(observed) <= set(self.views):
            raise ValueError("Unknown observation view")
        result = self.table
        for axis in reversed(range(len(self.views))):
            name = self.views[axis]
            if name in observed:
                value = observed[name]
                if type(value) is not int or not 0 <= value < self.table.shape[axis]:
                    raise ValueError("Observation is outside the frozen alphabet")
                result = np.take(result, value, axis=axis)
            else:
                result = result.sum(axis=axis)
        return result.copy()

    def export(self):
        safe = self.table.astype(object)
        safe[..., ~self.known] = None
        return {"views": list(self.views), "table": safe.tolist()}

    @classmethod
    def load(cls, record):
        return cls(np.asarray(record["table"], dtype=float), record["views"])


class EvidenceState:
    """Sequential views replace their block marginal, never add another factor."""

    def __init__(self, prior, blocks, captures, independence_assumption):
        if independence_assumption != "conditional independence only between declared blocks":
            raise ValueError("The cross-block conditional-independence assumption must be explicit")
        self.prior = np.asarray(prior, dtype=float).copy()
        if (self.prior.ndim != 1 or not np.isfinite(self.prior).all()
                or np.any(self.prior < 0) or abs(self.prior.sum()-1) > 1e-12):
            raise ValueError("The target prior must be separately normalized")
        self.prior.setflags(write=False)
        self.blocks = {name: (law, dict(bindings)) for name, (law, bindings) in blocks.items()}
        self.captures = dict(captures)
        if any(key != value.event_id for key, value in self.captures.items()):
            raise ValueError("Capture key does not match its acquisition identity")
        owners = {}
        for block_id, (law, bindings) in self.blocks.items():
            if set(bindings) != set(law.views):
                raise ValueError("Every view must bind a physical acquisition")
            if len(law.known) != len(self.prior) or not law.known[self.prior > 0].all():
                raise ValueError("Positive prior on an unidentified target is not inferable")
            for event in bindings.values():
                if event not in self.captures:
                    raise ValueError("Unknown acquisition")
                if event in owners and owners[event] != block_id:
                    raise ValueError("A physical acquisition cannot be counted in two blocks")
                owners[event] = block_id
        self.observed = {name: {} for name in self.blocks}
        self.aliases = {event: event for event in self.captures}
        self.posterior = self.prior.copy()
        self.unique_view_updates = 0

    def register_alias(self, alias, capture):
        event = capture.event_id
        if event not in self.captures or capture != self.captures[event]:
            raise ValueError("An alias must bind the same registered acquisition and content")
        if not alias or (alias in self.aliases and self.aliases[alias] != event):
            raise ValueError("Alias collision")
        self.aliases[alias] = event

    def ingest(self, receipt):
        required = {"block", "view", "alias", "content_sha256", "value"}
        if set(receipt) != required:
            raise ValueError("Only the declared public receipt fields are accepted")
        block, view, alias = (receipt[k] for k in ("block", "view", "alias"))
        if block not in self.blocks or alias not in self.aliases:
            raise ValueError("Unregistered evidence")
        law, bindings = self.blocks[block]
        event = self.aliases[alias]
        if view not in bindings or bindings[view] != event:
            raise ValueError("View belongs to another acquisition")
        if receipt["content_sha256"] != self.captures[event].content_sha256:
            raise ValueError("Acquisition content conflict")
        value = receipt["value"]
        law.marginal({view: value})
        previous = self.observed[block]
        if view in previous:
            if previous[view] != value:
                raise ValueError("A delivered view cannot be revised silently")
            return {"duplicate": True, **self.snapshot()}
        proposed = {key: dict(values) for key, values in self.observed.items()}
        proposed[block][view] = value
        active = self.prior > 0
        log_weight = np.full_like(self.prior, -np.inf)
        log_weight[active] = np.log(self.prior[active])
        for name, (block_law, _) in self.blocks.items():
            likelihood = block_law.marginal(proposed[name])[active]
            with np.errstate(divide="ignore"):
                log_weight[active] += np.log(likelihood)
        normalizer = np.max(log_weight)
        if not np.isfinite(normalizer):
            raise ValueError("Receipt has no support under the frozen model")
        posterior = np.exp(log_weight-normalizer)
        posterior /= posterior.sum()
        self.observed = proposed
        self.posterior = posterior
        self.unique_view_updates += 1
        return {"duplicate": False, **self.snapshot()}

    def snapshot(self):
        active_blocks = [key for key, values in self.observed.items() if values]
        physical = {self.blocks[key][1][view] for key in active_blocks for view in self.observed[key]}
        return {"posterior": self.posterior.tolist(), "observed": {key: dict(value) for key, value in self.observed.items()},
                "factor_count": len(active_blocks), "physical_event_count": len(physical),
                "unique_view_updates": self.unique_view_updates}

    def checkpoint(self):
        manifest = {"prior": self.prior.tolist(), "captures": {key: vars(value)
                    for key, value in sorted(self.captures.items())},
                    "blocks": {key: {"law": law.export(), "bindings": bindings}
                               for key, (law, bindings) in sorted(self.blocks.items())}}
        return {"manifest_sha256": sha(manifest), "aliases": dict(self.aliases),
                "state": self.snapshot()}

    def restore(self, checkpoint):
        if self.unique_view_updates or checkpoint["manifest_sha256"] != self.checkpoint()["manifest_sha256"]:
            raise ValueError("Restore requires the same externally frozen manifest and an empty state")
        candidate = EvidenceState(self.prior, self.blocks, self.captures,
                                  "conditional independence only between declared blocks")
        for alias, event in checkpoint["aliases"].items():
            if event not in self.captures:
                raise ValueError("Checkpoint alias references an unknown acquisition")
            candidate.register_alias(alias, self.captures[event])
        for block, observations in checkpoint["state"]["observed"].items():
            if block not in self.blocks:
                raise ValueError("Checkpoint contains an unknown block")
            for view, value in observations.items():
                event = self.blocks[block][1].get(view)
                if event not in self.captures:
                    raise ValueError("Checkpoint contains an unknown view")
                candidate.ingest({"block": block, "view": view, "alias": event,
                                  "content_sha256": self.captures[event].content_sha256, "value": value})
        expected = checkpoint["state"]
        actual = candidate.snapshot()
        for field in ("observed", "factor_count", "physical_event_count", "unique_view_updates"):
            if actual[field] != expected[field]:
                raise ValueError("Checkpoint state is inconsistent with its observations")
        if not np.allclose(actual["posterior"], expected["posterior"], rtol=0, atol=1e-14):
            raise ValueError("Checkpoint posterior does not match replay")
        self.aliases, self.observed = candidate.aliases, candidate.observed
        self.posterior, self.unique_view_updates = candidate.posterior, candidate.unique_view_updates
