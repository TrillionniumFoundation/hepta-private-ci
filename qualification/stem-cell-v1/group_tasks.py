"""Source-group-disjoint symbolic tasks with an independent evidence checker.

Targets belong to training/final evaluation only. The online verifier recomputes
support from public facts and returns a status, without supplying a correction.
Synthetic tasks establish controlled mechanisms, not natural-language ability.
"""
import hashlib
import json
import random
from dataclasses import dataclass, replace

from system2_execution import Verification


SPLITS = ("train", "validation", "selection", "test")
FAMILIES = ("dependency", "constraint", "temporal")


@dataclass(frozen=True)
class GroupTask:
    task_id: str
    family: str
    split: str
    text: str
    target: int
    old_task: bool
    source_group: str
    depth: int
    query: tuple
    evidence: tuple

    @property
    def sentences(self):
        return tuple(self.text.split("\n"))


def _render(family, query, facts, classes):
    if family == "composition":
        prompt = ("Combine LEFT and RIGHT: solve each task, map A=0 B=1 C=2 D=3 "
                  "E=4 F=5 G=6 H=7, add modulo 8, and return the resulting class.")
        left = facts[0].text if facts else "[MISSING EVIDENCE]"
        right = facts[1].text if len(facts) == 2 else "[MISSING EVIDENCE]"
        return "\n".join((prompt, "[LEFT]", left, "[RIGHT]", right))
    options = " ".join(chr(65 + i) for i in range(classes))
    if family == "dependency":
        prompt = f"Start at {query[1]} and follow every link. What is the endpoint class?"
        lines = [f"{a} links to {b}." if kind == "link" else f"{a} has class {b}."
                 for kind, a, b in facts]
    elif family == "constraint":
        prompt = "Which class satisfies every allowed-class constraint?"
        lines = [f"Constraint {i} allows {' '.join(values)}." for _, i, values in facts]
    else:
        prompt = f"What is the class of the last event for {query[1]} by time?"
        lines = [f"At time {time}, {entity} has class {label}."
                 for entity, time, label in facts]
    return "\n".join([prompt + f" Answer one of {options}.", *lines])


def supported_answer(task):
    """Compute the answer independently of task.target; missing support is None."""
    if task.family == "composition":
        if task.query != ("sum_mod", 8) or len(task.evidence) != 2:
            return None
        values = [supported_answer(part) for part in task.evidence]
        return sum(values) % 8 if all(value is not None for value in values) else None
    if task.family == "dependency":
        links = {a: b for kind, a, b in task.evidence if kind == "link"}
        labels = {a: b for kind, a, b in task.evidence if kind == "label"}
        node, visited = task.query[1], set()
        while node in links and node not in visited:
            visited.add(node)
            node = links[node]
        value = labels.get(node) if node not in visited else None
    elif task.family == "constraint":
        allowed = [set(values) for _, _, values in task.evidence]
        values = set.intersection(*allowed) if allowed else set()
        value = next(iter(values)) if len(values) == 1 else None
    elif task.family == "temporal":
        events = [(time, label) for entity, time, label in task.evidence if entity == task.query[1]]
        value = max(events)[1] if events else None
    else:
        raise ValueError("unknown task family")
    return ord(value) - 65 if value is not None else None


def verify(task, candidate):
    """No correction/target in feedback; repeated calls can still cost information."""
    if isinstance(candidate, str) and len(candidate.strip()) == 1:
        candidate = ord(candidate.strip().upper()) - 65
    if type(candidate) is not int or not 0 <= candidate < 8:
        return Verification(False, "invalid_candidate")
    supported = supported_answer(task)
    if supported is None:
        return Verification(False, "missing_evidence")
    accepted = candidate == supported
    return Verification(accepted, "supported" if accepted else "unsupported_" + task.family)


def feedback_vector(accepted, feedback):
    """Public status only: accepted, dependency, constraint, temporal failure."""
    return (float(accepted), float(feedback == "unsupported_dependency"),
            float(feedback == "unsupported_constraint"), float(feedback == "unsupported_temporal"))


def make_tasks(split, count=96, seed=0, classes=8, longer=False):
    """Hash-partition source facts, then select examples; labels never partition.

    A source has the same canonical digest and split at every random seed.
    Longer examples use lengths 5..7, versus 2..4 for the ordinary cohort.
    """
    if split not in SPLITS or type(count) is not int or count < 1 or classes != 8:
        raise ValueError("positive count, eight classes and an explicit split required")
    tasks, seen, attempt = [], set(), 0
    while len(tasks) < count:
        rng = random.Random(f"{seed}/{attempt}")
        family = FAMILIES[len(tasks) % len(FAMILIES)]
        depth = rng.randint(5, 7) if longer else rng.randint(2, 4)
        labels = [chr(65 + i) for i in range(classes)]
        if family == "dependency":
            nodes = rng.sample([f"n{i}" for i in range(16)], depth + 4)
            query = ("follow", nodes[0])
            facts = [("link", a, b) for a, b in zip(nodes[:depth], nodes[1:depth + 1])]
            answer = rng.choice(labels)
            expected = ord(answer) - 65
            facts += [("label", nodes[depth], answer)]
            facts += [("label", node, rng.choice(labels)) for node in nodes[depth + 1:]]
        elif family == "constraint":
            query = ("intersection",)
            answer = rng.choice(labels)
            expected = ord(answer) - 65
            others = [label for label in labels if label != answer]
            rng.shuffle(others)
            # Every incorrect class is excluded by at least one public fact.
            facts = [("allow", str(i), tuple(sorted([answer] + [v for j, v in enumerate(others)
                                                     if j % depth != i]))) for i in range(depth)]
        else:
            entity, other = rng.sample(["sensor0", "sensor1", "sensor2", "sensor3"], 2)
            query = ("latest", entity)
            times = rng.sample(range(1, 100), depth + 2)
            facts = [(entity, time, rng.choice(labels)) for time in times[:depth]]
            latest = max(range(depth), key=times.__getitem__)
            expected = ord(facts[latest][2]) - 65
            facts += [(other, time, rng.choice(labels)) for time in times[depth:]]
        canonical = json.dumps([family, query, sorted(facts)], separators=(",", ":"))
        source = hashlib.sha256(canonical.encode()).hexdigest()
        attempt += 1
        if int(source[:8], 16) % len(SPLITS) != SPLITS.index(split) or source in seen:
            continue
        seen.add(source)
        rng.shuffle(facts)
        task = GroupTask(f"{split}/{source[:20]}", family, split,
                         _render(family, query, facts, classes), expected,
                         family == "dependency", source, depth, query, tuple(facts))
        assert supported_answer(task) == expected, "constructed target and public evidence checker disagree"
        tasks.append(task)
    return tasks


def compose_tasks(first, second):
    """Untrained operation over two different-family, held-out source tasks.

    Construction labels use the source targets; online verification independently
    follows each part's public evidence and never reads those labels.
    """
    if (not isinstance(first, GroupTask) or not isinstance(second, GroupTask)
            or first.split != "test" or second.split != "test"
            or first.family not in FAMILIES or second.family not in FAMILIES
            or first.family == second.family or first.source_group == second.source_group
            or any(type(t.target) is not int or not 0 <= t.target < 8 for t in (first, second))):
        raise ValueError("composition requires two different-family base test sources")
    query, evidence = ("sum_mod", 8), (first, second)
    canonical = json.dumps(["composition", query,
                            [[t.task_id, t.source_group] for t in evidence]], separators=(",", ":"))
    source = hashlib.sha256(canonical.encode()).hexdigest()
    return GroupTask("composition/" + source[:20], "composition", "test",
                     _render("composition", query, evidence, 8),
                     (first.target + second.target) % 8, False, source,
                     first.depth + second.depth + 1, query, evidence)


def delete_evidence(task):
    """Ablation retains the evaluation label; verifier sees the degraded facts."""
    facts = ()
    return replace(task, evidence=facts, text=_render(task.family, task.query, facts, 8))
