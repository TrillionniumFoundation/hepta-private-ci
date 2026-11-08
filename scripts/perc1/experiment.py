"""Actor-only execution and validation; this module never loads an evaluator."""
import base64
import re
from dataclasses import asdict

from .schema import (ARMS, PHASES, ActorObservation, Cost, Invalid, Proposal, canonical, digest,
                     exact, integer, require, sha, string)
from .schema import manifest as validate_manifest

STATUSES = ("observed", "no_new_evidence", "failed", "cancelled", "unknown", "budget_denied", "stopped")


def communication_cost(proposal, observation, status, tariff):
    return sum(len(canonical(item)) for item in (proposal, observation, status)) * tariff["communication"]


def capture_identity(source):
    return sha({"raw_sha256": source["sha256"], "locator": source["locator"]})


def actor_context(dataset, episode, steps):
    return {"task": episode["task"], "catalog": [{"id": i, "description": dataset.sources[i]["description"]}
            for i in episode["source_ids"]], "history": steps}


def answer(value, observed):
    exact(value, "text fields evidence_ids")
    require(type(value["text"]) is str and len(value["text"]) <= 65536 and type(value["fields"]) is dict, "invalid answer")
    for key, item in value["fields"].items():
        string(key)
        require(type(item) is str and len(item) <= 65536, "critical fields must preserve strings")
    ids = value["evidence_ids"]
    require(type(ids) is list and len(ids) == len(set(ids)) and set(ids) <= set(observed), "answer cites unobserved evidence")
    return value


def validate_trace(trace, manifest, dataset):
    validate_manifest(manifest, dataset)
    exact(trace, "schema manifest_sha256 episode_id seed arm steps answer")
    require(trace["schema"] == "perc1.trace.v1" and digest(trace["manifest_sha256"]) == sha(manifest), "trace manifest mismatch")
    require(trace["episode_id"] in dataset.episodes and trace["arm"] in ARMS, "unknown episode or arm")
    require(integer(trace["seed"]) in {r["seed"] for r in manifest["controller"]["training_runs"]}, "unregistered training seed")
    episode, steps = dataset.episodes[trace["episode_id"]], trace["steps"]
    require(type(steps) is list and 0 < len(steps) <= 10000, "invalid attempt count")
    tariff, cap = manifest["budget"]["tariff"], manifest["budget"]["cap"]
    observed, captures, ids, spent, end, previous = set(), set(), set(), 0, 0, []
    fixed = episode["initial_ids"] + [i for i in episode["source_ids"] if i not in episode["initial_ids"]]
    for index, step in enumerate(steps):
        exact(step, "attempt_id input_sha256 proposal status reservation cost billing_receipt_sha256 started_ns finished_ns observation")
        require(string(step["attempt_id"]) not in ids and step["status"] in STATUSES, "duplicate attempt or unknown status")
        ids.add(step["attempt_id"])
        digest(step["billing_receipt_sha256"])
        require(digest(step["input_sha256"]) == sha(actor_context(dataset, episode, previous)), "actor prefix mismatch")
        require(end <= integer(step["started_ns"]) <= integer(step["finished_ns"]), "nonmonotone time")
        end = step["finished_ns"]
        cost, status = Cost.parse(step["cost"]), step["status"]
        require(cost.decision >= tariff["decision"] and cost.communication >= tariff["communication"], "missing decision/communication charge")
        require(cost.training == cost.evaluation == 0, "training/evaluator costs belong in separate receipts")
        if trace["arm"].endswith("active"):
            require(cost.planning >= tariff["planning"], "active planning cost missing")
        quote = integer(step["reservation"], 1)
        if status == "budget_denied":
            require(quote > cap - spent and cost.acquisition == cost.encoding == cost.inference == cost.wait == cost.failure == cost.cancellation == 0, "invalid denied reservation")
        else:
            require(cost.total <= quote <= cap - spent, "reservation does not bound incurred cost")
        spent += cost.total
        require(spent <= cap, "budget exceeded")
        proposal = step["proposal"]
        if status == "stopped":
            require(proposal is None and cost.acquisition == cost.encoding == cost.inference == cost.wait == cost.failure == cost.cancellation == 0, "invalid stop")
            require(index >= len(episode["initial_ids"]), "stopped before initial evidence attempts")
        else:
            Proposal.parse(proposal, episode["source_ids"])
            if index < len(episode["initial_ids"]):
                require(proposal["source_id"] == episode["initial_ids"][index], "initial evidence differs between arms")
            if trace["arm"].endswith("fixed"):
                require(proposal["source_id"] == fixed[index % len(fixed)], "fixed reading schedule changed")
            if status != "budget_denied":
                require(cost.acquisition >= tariff["acquisition"], "unmetered acquisition attempt")
        require(cost.failure >= tariff["failure"] if status in ("failed", "unknown") else cost.failure == 0, "missing or unexplained failure charge")
        require(cost.cancellation >= tariff["cancellation"] if status == "cancelled" else cost.cancellation == 0, "missing or unexplained cancellation charge")
        if status == "observed":
            source_id = proposal["source_id"]
            capture = capture_identity(dataset.sources[source_id])
            require(capture not in captures, "duplicate captured evidence or source alias claimed as new")
            obs = ActorObservation.parse(step["observation"], dataset.sources[source_id], dataset.read(source_id), manifest["encoder"], trace["arm"])
            require(obs.observed_ns == end and cost.encoding >= tariff["encoding"], "missing encoding charge or wrong observation time")
            require(cost.inference >= tariff["inference"], "downstream inference cost missing")
            observed.add(source_id)
            captures.add(capture)
        else:
            require(step["observation"] is None and cost.encoding == 0, "non-observation exposes evidence or encoding")
        require(cost.communication >= communication_cost(proposal, step["observation"], status, tariff), "communication payload undercounted")
        if status in ("stopped", "budget_denied", "unknown"):
            require(index == len(steps) - 1, "continued after terminal receipt")
        previous.append(step)
    require(len(steps) >= len(episode["initial_ids"]) or steps[-1]["status"] in ("budget_denied", "unknown"), "missing initial attempts")
    answer(trace["answer"], observed)
    pending = steps[-1]["reservation"] - Cost.parse(steps[-1]["cost"]).total if steps[-1]["status"] == "unknown" else 0
    return {"spent": spent, "pending_reservation": pending, "observed": observed, "observed_captures": captures, "attempts": len(steps), "duration_ns": end - steps[0]["started_ns"]}


def diagnostic_encode(raw_length, loc, dense, dimension):
    """Shape-only smoke features, explicitly not a learned encoder."""
    positions = [loc]
    if dense and loc["kind"] == "bytes" and loc["end"] - loc["start"] > 1:
        midpoint = (loc["start"] + loc["end"]) // 2
        positions = [dict(loc, end=midpoint), dict(loc, start=midpoint)]
    return [{"locator": position, "values": [float(raw_length % (i + 17)) for i in range(dimension)]} for position in positions]


class FixtureExecutor:
    """Deterministic protocol fixture. No truth/teacher object is accepted."""
    def __init__(self, manifest, dataset, episode, seed, arm):
        require(manifest["encoder"]["kind"] == "diagnostic_fixture", "fixture cannot execute external encoder")
        self.manifest, self.dataset, self.episode = manifest, dataset, episode
        self.trace = dict(schema="perc1.trace.v1", manifest_sha256=sha(manifest), episode_id=episode["id"], seed=seed, arm=arm,
                          steps=[], answer={"text": "", "fields": {}, "evidence_ids": []})
        self.spent = 0
        self.pending_reservation = 0

    def attempt(self, source_id, outcome=None):
        steps, tariff = self.trace["steps"], self.manifest["budget"]["tariff"]
        require(not steps or steps[-1]["status"] not in ("unknown", "budget_denied"), "terminal/pending attempt requires owner reconciliation")
        source, now = self.dataset.sources[source_id], (len(steps) + 1) * 1000
        proposal = asdict(Proposal(source_id, "acquire", "registered catalog / actor-visible continuation", 0.0))
        # Quote uses frozen metadata only; no I/O occurs before reservation.
        size = source["byte_length"]
        tokens = diagnostic_encode(size, source["locator"], self.trace["arm"].startswith("dense"), self.manifest["encoder"]["dimension"])
        require(len(tokens) * self.manifest["encoder"]["dimension"] <= 65536, "fixture scalar budget exceeded")
        template = ActorObservation(source_id, source["sha256"], "A" * (4 * ((size + 2) // 3)), source["locator"],
                                    self.manifest["encoder"]["checkpoint_sha256"], tokens, now).to_dict()
        quote = sum(tariff.values()) + communication_cost(proposal, template, "observed", tariff)
        integer(quote, 1)
        costs = {phase: 0 for phase in PHASES}
        costs.update(communication=communication_cost(proposal, None, "budget_denied", tariff), decision=tariff["decision"], planning=tariff["planning"] if self.trace["arm"].endswith("active") else 0)
        if self.manifest["budget"]["cap"] - self.spent < sum(costs.values()):
            return False
        status, obs = outcome or "observed", None
        require(status in STATUSES[:5], "unsupported fixture execution status")
        if quote > self.manifest["budget"]["cap"] - self.spent:
            status = "budget_denied"
        else:
            costs["acquisition"] = tariff["acquisition"]
            seen = {capture_identity(self.dataset.sources[s["proposal"]["source_id"]]) for s in steps if s["status"] == "observed"}
            if status == "observed" and (capture_identity(source) in seen or now < source["available_ns"]):
                status = "no_new_evidence"
            if status == "observed":
                try:
                    raw = self.dataset.read(source_id)
                    obs = ActorObservation(source_id, sha(raw), base64.b64encode(raw).decode(), source["locator"],
                        self.manifest["encoder"]["checkpoint_sha256"], tokens, now).to_dict()
                    costs["encoding"] = tariff["encoding"]
                    costs["inference"] = tariff["inference"]
                except (OSError, Invalid):
                    status = "failed"
            if status in ("failed", "unknown"):
                costs["failure"] = tariff["failure"]
            if status == "cancelled":
                costs["cancellation"] = tariff["cancellation"]
        costs["communication"] = communication_cost(proposal, obs, status, tariff)
        receipt = dict(attempt_id=str(len(steps)), input_sha256=sha(actor_context(self.dataset, self.episode, steps)), proposal=proposal,
                       status=status, reservation=quote, cost=costs, billing_receipt_sha256=sha(["synthetic-billing", self.trace["seed"], self.trace["arm"], now]),
                       started_ns=now - 1000, finished_ns=now, observation=obs)
        self.spent += Cost.parse(costs).total
        self.pending_reservation = quote - Cost.parse(costs).total if status == "unknown" else 0
        steps.append(receipt)
        require(Cost.parse(costs).total <= quote, "fixture reservation underestimated; receipt retained")
        return status not in ("budget_denied", "unknown")

    def run(self):
        pending = self.episode["initial_ids"] + [i for i in self.episode["source_ids"] if i not in self.episode["initial_ids"]]
        while pending:
            source_id = pending.pop(0)
            if not self.attempt(source_id):
                break
            obs = self.trace["steps"][-1]["observation"]
            if obs is None:
                continue
            text = base64.b64decode(obs["raw_base64"]).decode(errors="replace")
            found = re.search(r"^answer:(.*)$", text, re.MULTILINE)
            if found:
                self.trace["answer"] = {"text": found[1], "fields": {"critical": found[1]}, "evidence_ids": [source_id]}
                break
            if self.trace["arm"].endswith("active"):
                link = re.search(r"^next:([^\n]+)$", text, re.MULTILINE)
                if link and link[1] in pending and len(self.trace["steps"]) >= len(self.episode["initial_ids"]):
                    pending.remove(link[1])
                    pending.insert(0, link[1])
        validate_trace(self.trace, self.manifest, self.dataset)
        return self.trace
