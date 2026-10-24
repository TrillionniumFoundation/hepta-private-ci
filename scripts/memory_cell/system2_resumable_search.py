"""In-memory continuation of the existing exact-verifier arithmetic search.

The heap, visited states, partially generated node, and its child cursor survive
budget boundaries. No new policy, oracle, training, or durable checkpoint format.
Only a larger cumulative successor allowance resumes the SAME frozen policy.
"""

from fractions import Fraction
import heapq
import time

import torch

from system2_ablation import model_digest
from system2_verified_search import (
    ARMS,
    digest,
    features,
    state_key,
    successors,
    validate_task,
    verify,
)
from finite_tree_bsde import recursive_utility
from system2_canonical_generation import canonical_successors


class SearchSession:
    """Single-task, single-policy cursor; not thread-safe or crash-recoverable."""

    def __init__(
        self,
        numbers,
        goal,
        arm,
        critic=None,
        *,
        popped_ceiling=8192,
        generation_profile="reference",
        terminal_prefilter=False,
    ):
        validate_task(numbers, goal)
        if (
            arm not in ARMS
            or type(popped_ceiling) is not int
            or not 1 <= popped_ceiling <= 8192
            or generation_profile not in ("reference", "canonical_pair")
            or type(terminal_prefilter) is not bool
        ):
            raise ValueError("unregistered policy or popped-state bound")
        neural = arm in ("value_search", "ndu_value", "shuffled_value")
        if neural and (
            critic is None
            or critic.training
            or any(p.requires_grad for p in critic.parameters())
        ):
            raise ValueError("frozen evaluation-mode critic required")
        self.numbers, self.goal, self.arm = tuple(numbers), goal, arm
        self.generation_profile = generation_profile
        self.terminal_prefilter = terminal_prefilter
        self._exact_goal = Fraction(goal)
        self.verification_skips = 0
        self.generation_counts = dict(
            pair_checks=0, pair_skips=0, symmetry_skips=0, emitted=0
        )
        self.critic = critic if neural else None
        self.model_seal = model_digest(self.critic) if neural else None
        root = tuple((Fraction(n), ("n" + str(i),)) for i, n in enumerate(numbers))
        self.queue, self.seen, self.serial = [(0.0, 0, root)], {state_key(root)}, 1
        self.pending, self.children, self.cursor = None, [], 0
        self.limit, self.popped_ceiling, self.proof = 0, popped_ceiling, None
        self.failed, self.seconds, self.calls = False, 0.0, 0
        self.costs = dict(
            popped_states=0, generated_successors=0, critic_examples=0, verifier_calls=0
        )

    @torch.no_grad()
    def advance(self, successor_ceiling):
        """Increase a cumulative allowance; do not restart or discard frontier work.

        Complete a node's child batch before priority insertion. Pausing halfway
        must not change floating-point batch shape, tie order, or greedy choice.
        Generator-local option preparation is timed but is not a yielded-child
        count, just as in the historical reference. Boundaries are cooperative.
        """
        if (
            self.failed
            or type(successor_ceiling) is not int
            or not self.limit <= successor_ceiling <= 65536
            or successor_ceiling < 1
        ):
            raise ValueError(
                "nondecreasing bounded allowance and healthy cursor required"
            )
        if self.critic is not None and (
            self.critic.training
            or any(p.requires_grad for p in self.critic.parameters())
            or model_digest(self.critic) != self.model_seal
        ):
            self.failed = True
            raise ValueError("frozen critic changed while search was paused")
        self.limit = successor_ceiling
        self.calls += 1
        started = time.perf_counter()
        try:
            while (
                self.proof is None and self.costs["generated_successors"] < self.limit
            ):
                if self.pending is None:
                    if (
                        not self.queue
                        or self.costs["popped_states"] >= self.popped_ceiling
                    ):
                        break
                    _, _, terms = heapq.heappop(self.queue)
                    self.costs["popped_states"] += 1
                    generator = (
                        successors(terms)
                        if self.generation_profile == "reference"
                        else canonical_successors(terms, self.generation_counts)
                    )
                    self.pending, self.children, self.cursor = iter(generator), [], 0
                try:
                    child = next(self.pending)
                except StopIteration:
                    self.pending = None
                    children, self.children = self.children, []
                    if not children:
                        continue
                    depth = 4 - len(children[0])
                    if self.critic is not None:
                        batch = torch.tensor(
                            [features(state_key(c), self.goal) for c in children],
                            dtype=torch.float32,
                        )
                        self.costs["critic_examples"] += len(children)
                        scores = torch.sigmoid(self.critic(batch).flatten())
                        if (
                            scores.shape != (len(children),)
                            or not torch.isfinite(scores).all()
                        ):
                            raise ValueError("invalid frozen critic output")
                        values = scores.tolist()
                    elif self.arm == "breadth_first":
                        values = [-depth] * len(children)
                    elif self.arm == "flat_ndu":
                        values = [0.5] * len(children)
                    else:
                        values = [
                            1 / (1 + min(abs(float(v) - self.goal) for v, _ in c))
                            for c in children
                        ]
                    if self.arm in ("ndu_value", "flat_ndu"):
                        values = [
                            recursive_utility([-0.001] * depth, [0.98] * depth, v)[0]
                            for v in values
                        ]
                    if self.arm == "greedy":
                        best = max(range(len(children)), key=lambda i: values[i])
                        children, values = [children[best]], [values[best]]
                    for child, value in zip(children, values, strict=True):
                        heapq.heappush(self.queue, (-value, self.serial, child))
                        self.serial += 1
                    continue
                self.cursor += 1
                self.costs["generated_successors"] += 1
                key = state_key(child)
                if key in self.seen:
                    continue
                self.seen.add(key)
                if len(child) == 1:
                    # Trusted successor values are exact Fractions. Rejecting a
                    # value unequal to the goal cannot discard a valid proof;
                    # every candidate success STILL goes through the separate
                    # original postfix proof verifier.
                    if self.terminal_prefilter and child[0][0] != self._exact_goal:
                        self.verification_skips += 1
                        continue
                    self.costs["verifier_calls"] += 1
                    if verify(self.numbers, self.goal, child[0][1]):
                        self.proof = child[0][1]
                else:
                    self.children.append(child)
            if self.critic is not None and model_digest(self.critic) != self.model_seal:
                raise ValueError("critic mutated during evaluation")
        except Exception:
            self.failed = True
            raise
        finally:
            self.seconds += time.perf_counter() - started
        return self.receipt()

    def receipt(self):
        """Detached accounting; an unfinished cursor is not an impossibility proof."""
        return dict(
            found=self.proof is not None,
            proof=self.proof,
            costs=dict(self.costs),
            seconds=self.seconds,
            calls=self.calls,
            successor_ceiling=self.limit,
            frontier_states=len(self.queue),
            partial_children=len(self.children),
            partial_child_cursor=self.cursor if self.pending is not None else None,
            visited_states=len(self.seen),
            status="failed" if self.failed else "completed",
            paused=self.proof is None
            and (self.pending is not None or bool(self.queue)),
            certified_impossible=False,
            in_memory_only=True,
            frozen_model=self.model_seal,
            task_digest=digest(self.numbers),
            generation_profile=self.generation_profile,
            generation_filter=dict(self.generation_counts),
            terminal_prefilter=self.terminal_prefilter,
            verification_skips=self.verification_skips,
        )
