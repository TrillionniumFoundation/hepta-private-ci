"""Next-cell policies fitted to actual source-step outcomes, never final labels."""

import hashlib
import json
from pathlib import Path
import sys

from evolution_common import (
    canonical,
    digest,
    file_digest,
    identifier,
    require,
    roots,
    retain,
)


def state_text(state):
    require(
        type(state) is dict and set(state) == {"question", "cell_id", "raw_text"},
        "closed public transition state required",
    )
    identifier(state["cell_id"])
    require(
        all(
            type(state[k]) is str and len(state[k].encode()) <= 2048
            for k in ("question", "raw_text")
        ),
        "bounded transition text required",
    )
    return (
        "Request: "
        + state["question"]
        + "\nCell: "
        + state["cell_id"]
        + "\nObserved raw output: "
        + json.dumps(state["raw_text"], ensure_ascii=False)
    )


def source_utilities(records, targets):
    """Source truth belongs only to fitting; exact raw output determines utility."""
    observations, ancestry = [], set()
    for record in records:
        require(
            set(record)
            == {
                "case_id",
                "phase",
                "state",
                "target_value",
                "candidate_outputs",
                "source_roots",
            }
            and record["phase"] == "source",
            "source-only closed utility record required",
        )
        identifier(record["case_id"])
        require(
            type(record["target_value"]) is str
            and 0 < len(record["target_value"].encode()) <= 1024,
            "bounded source target",
        )
        ancestry.update(roots(record["source_roots"]))
        require(
            set(record["candidate_outputs"]) == set(targets),
            "complete candidate outcome panel required",
        )
        utilities = []
        for target in targets:
            observed = record["candidate_outputs"][target]
            require(
                set(observed)
                == {"status", "raw_text", "receipt_sha256", "actual_callbacks"},
                "closed actual outcome required",
            )
            roots([observed["receipt_sha256"]])
            require(
                observed["status"] in ("generated", "denied", "indeterminate"),
                "unknown observation status",
            )
            require(
                observed["actual_callbacks"] in (0, 1),
                "one measured next-cell callback maximum",
            )
            if observed["status"] == "generated":
                require(
                    observed["actual_callbacks"] == 1
                    and type(observed["raw_text"]) is str,
                    "generated utility requires actual raw decoder call",
                )
                utilities.append(
                    float(observed["raw_text"].strip() == record["target_value"])
                )
            else:
                utilities.append(0.0)
        observations.append(
            dict(
                question=state_text(record["state"]),
                utilities=utilities,
                reject=not any(utilities),
            )
        )
    require(observations, "nonempty source utility observations required")
    return observations, sorted(ancestry)


def fit_edges(records, targets, *, scripts, output, seed=24031):
    """Use existing real fitted-router weights on post-cell transition state."""
    sys.path.insert(0, str(Path(scripts).resolve() / "memory_cell_router"))
    from learned_router import fit_router
    from router_features import checked_config

    observations, ancestry = source_utilities(records, targets)
    config = checked_config(None)
    config.update(seed=seed, epochs=400)
    fitted = fit_router(
        observations, expert_ids=targets, source_sha256=digest(records), config=config
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    retain(output / "source-observations.json", observations)
    receipt = fitted.save(output / "router.bin")
    value = dict(
        recipe="learned-next-cell",
        router_sha256=receipt["sha256"],
        source_sha256=digest(records),
        ancestry_roots=ancestry,
        targets=list(targets),
        config=config,
        training=receipt["training"],
        final_outputs_used=False,
        production_accepted=False,
    )
    retain(output / "policy.json", value)
    return dict(
        recipe=value["recipe"],
        sha256=file_digest(output / "policy.json"),
        ancestry_roots=ancestry,
    )


class EdgePolicy:
    """Frozen conditional edge policy; policy outcomes are never memory answers."""

    def __init__(
        self, recipe, targets, *, seed=24031, learned_directory=None, scripts=None
    ):
        require(
            recipe
            in ("no-edges", "fixed", "random", "capability", "learned-next-cell"),
            "unregistered edge policy",
        )
        self.recipe, self.targets, self.seed = recipe, list(targets), seed
        require(
            len(self.targets) == len(set(self.targets))
            and all(identifier(t) for t in self.targets),
            "distinct target cells required",
        )
        require(
            recipe == "no-edges" or 1 <= len(self.targets) <= 16,
            "bounded nonempty next-cell choices required",
        )
        self.directory = Path(learned_directory) if learned_directory else None
        self.model = None
        if recipe == "learned-next-cell":
            value = json.loads((self.directory / "policy.json").read_bytes())
            require(
                value["targets"] == self.targets
                and value["final_outputs_used"] is False,
                "frozen next-cell policy binding",
            )
            sys.path.insert(0, str(Path(scripts).resolve() / "memory_cell_router"))
            from learned_router import load_router

            self.model = load_router(
                self.directory / "router.bin", expected_sha256=value["router_sha256"]
            )
            require(
                list(self.model.expert_ids) == self.targets
                and self.model.source_sha256 == value["source_sha256"],
                "router/state-source binding",
            )
            self.binding = dict(
                recipe=recipe,
                sha256=file_digest(self.directory / "policy.json"),
                ancestry_roots=roots(value["ancestry_roots"]),
            )
        else:
            self.binding = dict(
                recipe=recipe,
                sha256=digest(dict(recipe=recipe, targets=self.targets, seed=seed)),
                ancestry_roots=[],
            )

    def check(self):
        if self.directory:
            require(
                file_digest(self.directory / "policy.json") == self.binding["sha256"],
                "edge policy changed after freeze",
            )
            value = json.loads((self.directory / "policy.json").read_bytes())
            require(
                file_digest(self.directory / "router.bin") == value["router_sha256"],
                "edge weights changed after freeze",
            )

    def choose(self, state, capability_targets=()):
        state_text(state)
        self.check()
        if self.recipe == "no-edges":
            return None
        if self.recipe == "fixed":
            return self.targets[0] if self.targets else None
        if self.recipe == "random":
            index = int(
                hashlib.sha256(
                    canonical(dict(seed=self.seed, state=state))
                ).hexdigest(),
                16,
            ) % len(self.targets)
            return self.targets[index]
        if self.recipe == "capability":
            eligible = sorted(set(capability_targets) & set(self.targets))
            return eligible[0] if eligible else None
        return self.model.predict({"question": state_text(state)})["expert_id"]
