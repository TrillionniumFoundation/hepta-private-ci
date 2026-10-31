"""Differentiable finite joint-state control; no private rollout labels.

The external transition graph is independently enumerated by oracle.py. The
internal transition is exactly model.core's stated finite model. This is an
exact soft-policy expectation on that graph, not a continuous diffusion QVI.
"""

from dataclasses import dataclass

import torch

from . import oracle
from .data import task_configuration
from .task import ACTIONS, State, features, legal_actions


@dataclass
class ControlGraph:
    states: list
    inputs: torch.Tensor
    legal: torch.Tensor
    immediate: torch.Tensor
    myopic: torch.Tensor
    layers: list
    initial_indices: list
    configurations: list


def build_graph(configurations=None):
    configurations = configurations or [task_configuration(i) for i in range(8)]
    states, index, pending, initial_indices = [], {}, [], []

    def register(state):
        if state not in index:
            index[state] = len(states)
            states.append(state)
            pending.append(state)
        return index[state]

    for configuration in configurations:
        initial_indices.append(register(State(configuration, remaining_budget=configuration.budget)))
    edges = {}
    while pending:
        state = pending.pop()
        i = index[state]
        for a, action in enumerate(ACTIONS):
            if action not in legal_actions(state):
                continue
            edges[i, a] = []
            for probability, successor, reward in oracle.transition_distribution(state, action):
                if probability == 0:
                    continue
                j = -1 if successor.terminated else register(successor)
                edges[i, a].append((probability, j, reward))
    count = len(states)
    immediate = torch.zeros(count, len(ACTIONS), dtype=torch.float64)
    legal = torch.zeros(count, len(ACTIONS), dtype=torch.bool)
    myopic = torch.zeros_like(immediate)
    for i, state in enumerate(states):
        target = oracle.myopic_action_values(state)
        for a, action in enumerate(ACTIONS):
            myopic[i, a] = target[action]
            if (i, a) in edges:
                legal[i, a] = True
                immediate[i, a] = sum(p * r for p, _, r in edges[i, a])
    layers = []
    for tick in sorted({s.tick for s in states}, reverse=True):
        ids = [i for i, s in enumerate(states) if s.tick == tick]
        width = max((sum(j >= 0 for _, j, _ in edges.get((i, a), []))
                     for i in ids for a in range(len(ACTIONS))), default=1)
        width = max(1, width)
        successors = torch.full((len(ids), len(ACTIONS), width), count, dtype=torch.long)
        weights = torch.zeros(len(ids), len(ACTIONS), width, dtype=torch.float64)
        for row, i in enumerate(ids):
            for a in range(len(ACTIONS)):
                continuing = [(p, j) for p, j, _ in edges.get((i, a), []) if j >= 0]
                for branch, (probability, j) in enumerate(continuing):
                    successors[row, a, branch] = j
                    weights[row, a, branch] = probability
        layers.append((torch.tensor(ids), successors, weights))
    return ControlGraph(states, torch.tensor([features(s).tolist() for s in states], dtype=torch.float64),
                        legal, immediate, myopic, layers, initial_indices,
                        [p.to_dict() for p in configurations])


def evaluate_graph(model, graph, *, temperature=0.12, compute_price=0.0005,
                   event_price=0.0002, head=1, policy="soft"):
    """V(s,z_before) includes recovery/reset, later actions, and all step fees.

    The event charge is applied on the incoming state transition. Q(s,z_after,a)
    therefore excludes that already incurred fee but includes all future ones.
    Prices are registered utility coefficients, not measured dollars or energy.
    """
    inputs = graph.inputs.to(dtype=torch.float64)
    content, drive = model.encode(inputs)
    count, latent = len(graph.states), model.core.n_states
    if model.mode == "direct":
        transition = torch.eye(latent, dtype=torch.float64).expand(count, -1, -1)
        events = torch.zeros(count, latent, 2, dtype=torch.float64)
    else:
        transition, events = model.core.transition_matrix(drive)
    prediction = model.state_action_values(inputs, content)
    selected = prediction[:, :, head, :].masked_fill(~graph.legal[:, None, :], -1e9)
    if policy == "soft":
        probabilities = torch.softmax(selected / temperature, dim=-1)
    elif policy == "greedy":
        probabilities = torch.nn.functional.one_hot(selected.argmax(dim=-1), len(ACTIONS)).double()
    else:
        raise ValueError(policy)
    values = torch.zeros(count + 1, latent, dtype=torch.float64)
    q_targets = torch.zeros(count, latent, len(ACTIONS), dtype=torch.float64)
    myopic_targets = torch.zeros_like(q_targets)
    stop_before = (graph.immediate[:, ACTIONS.index("STOP"), None] - compute_price
                   - event_price * events.sum(dim=-1))
    stop_before = torch.cat((stop_before, torch.zeros(1, latent, dtype=torch.float64)))
    for ids, successors, weights in graph.layers:
        continuation = (values[successors] * weights[:, :, :, None]).sum(dim=2).transpose(1, 2)
        q = graph.immediate[ids, None, :] - compute_price + continuation
        after = (probabilities[ids] * q).sum(dim=-1)
        before = torch.bmm(transition[ids], after[:, :, None]).squeeze(-1)
        before = before - event_price * events[ids].sum(dim=-1)
        values = values.index_copy(0, ids, before)
        q_targets = q_targets.index_copy(0, ids, q)
        one_step = (stop_before[successors] * weights[:, :, :, None]).sum(dim=2).transpose(1, 2)
        one_step = graph.immediate[ids, None, :] - compute_price + one_step
        myopic_targets = myopic_targets.index_copy(0, ids, one_step)
    starts = torch.tensor(graph.initial_indices)
    expected_return = (values[starts] * model.initial(len(starts))).sum(dim=-1).mean()
    legal = graph.legal[:, None, :].expand(-1, latent, -1)
    critic_loss = ((prediction[:, :, 1, :] - q_targets.detach()).square() * legal).sum() / legal.sum()
    myopic_loss = ((prediction[:, :, 0, :] - myopic_targets.detach()).square() * legal).sum() / legal.sum()
    return expected_return, {"critic_loss": critic_loss, "myopic_loss": myopic_loss,
                             "q_targets": q_targets, "myopic_targets": myopic_targets,
                             "state_values": values,
                             "policy_probabilities": probabilities,
                             "initial_values": values[starts, model.n_grid // 2]}


def refine(model, graph, *, epochs=30, lr=0.003):
    """Fixed-budget task-return improvement; no confirmation or private data."""
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=lr)
    curve = []
    gradient_max = {key: 0.0 for key in model.parameter_groups()}
    for epoch in range(epochs + 1):
        optimizer.zero_grad(set_to_none=True)
        value, details = evaluate_graph(model, graph)
        loss = -value + details["critic_loss"] + details["myopic_loss"]
        if epoch % 5 == 0 or epoch == epochs:
            curve.append({"epoch": epoch, "exact_soft_return": float(value.detach()),
                          "critic_mse": float(details["critic_loss"].detach()),
                          "myopic_mse": float(details["myopic_loss"].detach()),
                          "objective": float(loss.detach())})
        if epoch == epochs:
            break
        loss.backward()
        for key, parameters in model.parameter_groups().items():
            norm = sum(float(p.grad.detach().square().sum()) for p in parameters if p.grad is not None)**0.5
            gradient_max[key] = max(gradient_max[key], norm)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
    with torch.no_grad():
        hard_value, _ = evaluate_graph(model, graph, policy="greedy")
    return {"epochs": epochs, "learning_rate": lr, "temperature": 0.12,
            "compute_price": 0.0005, "event_price": 0.0002,
            "critic_weight": 1.0, "myopic_weight": 1.0,
            "training_public_states": len(graph.states), "curve": curve,
            "gradient_max_by_group": gradient_max,
            "exact_greedy_internal_state_return": float(hard_value),
            "meaning": "exact finite joint external/internal-state soft-policy task return"}
