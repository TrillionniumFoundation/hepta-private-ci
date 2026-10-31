"""Signed exponential action-minus-stop moments on all 763 public features."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F


DIM, GAMMA, ACTION_COST = 763, 2., .002
CONFIG = {"widths": [32, 128], "folds": 2, "fold_steps": 600,
          "steps": 1200, "batch": 256, "lr": .002, "weight_decay": .0001}


class Head(nn.Module):
    """Four signed action differences; stop is identically zero outside the head."""

    def __init__(self, width, seed):
        super().__init__()
        self.config = {"width": width, "seed": seed}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.net = nn.Sequential(nn.Linear(DIM, width), nn.Tanh(), nn.Linear(width, 4))
        self.register_buffer("mean", torch.zeros(DIM))
        self.register_buffer("scale", torch.ones(DIM))

    def forward(self, public):
        if public.ndim != 2 or public.shape[1] != DIM or not torch.isfinite(public).all():
            raise ValueError("A finite complete rich-public matrix is required")
        result = self.net((public - self.mean) / self.scale)
        if not torch.isfinite(result).all(): raise ValueError("Nonfinite signed moment difference")
        return result


def values(head, public, remaining):
    delta = head(public)
    result = torch.cat((torch.zeros(len(public), 1), delta), 1)
    if remaining == 1: result[:, 1] = float("inf")
    elif remaining != 2: raise ValueError("Only the frozen H1/H2 budget is supported")
    return result


def fit_head(public, target, width, seed, steps):
    if public.shape != (len(target), DIM) or target.shape[1:] != (4,) or not torch.isfinite(target).all():
        raise ValueError("Paired public states and finite outcomes required")
    head = Head(width, seed)
    with torch.no_grad():
        head.mean.copy_(public.mean(0))
        scale = public.std(0, unbiased=False)
        head.scale.copy_(torch.where(scale > 1e-6, scale, torch.ones_like(scale)))
    optimizer = torch.optim.AdamW(head.parameters(), lr=CONFIG["lr"], weight_decay=CONFIG["weight_decay"])
    rng = torch.Generator().manual_seed(seed + 1)
    trace = []
    for step in range(steps):
        ids = torch.randint(len(public), (CONFIG["batch"],), generator=rng)
        prediction = head(public[ids]); loss = F.mse_loss(prediction, target[ids])
        if not torch.isfinite(loss): raise ValueError("Nonfinite paired regression objective")
        optimizer.zero_grad(set_to_none=True); loss.backward()
        nn.utils.clip_grad_norm_(head.parameters(), 2.)
        optimizer.step()
        if step == 0 or (step + 1) % 200 == 0: trace.append({"step": step + 1, "MSE": float(loss.detach())})
    return head.eval().requires_grad_(False), trace


def examples(public, utility):
    if public.shape != (len(utility), 5, DIM) or utility.shape[1:] != (21,):
        raise ValueError("Complete original public roots/children and actual finite outputs required")
    x = public.clone(); x[:, 0, -1] = .5
    outcomes = torch.empty(len(public), 5, 5)
    outcomes[:, 0] = utility[:, :5]
    for first in range(4):
        outcomes[:, first + 1, 0] = utility[:, first + 1]
        outcomes[:, first + 1, 1:] = utility[:, 5 + first * 4:9 + first * 4]
    cost = torch.tensor([0., ACTION_COST, ACTION_COST, ACTION_COST, ACTION_COST])
    moment = torch.exp(-GAMMA * (outcomes - cost))
    return x.flatten(0, 1), (moment[..., 1:] - moment[..., :1]).flatten(0, 1), moment


@dataclass
class Policy:
    one: Head
    two: Head

    @torch.inference_mode()
    def predict(self, public, remaining):
        return values(self.one if remaining == 1 else self.two, public, remaining)

    @torch.inference_mode()
    def choose(self, public, remaining):
        return self.predict(public, remaining).argmin(-1)


def fit(public, utility, cases, width, seed, audit_directory):
    audit_directory = Path(audit_directory); audit_directory.mkdir(parents=True, exist_ok=False)
    x, delta, realized = examples(public, utility)
    folds = cases % 2
    root_targets = torch.empty(len(public), 4)
    oof = torch.empty_like(delta)
    backup_choices = torch.empty(len(public), 4, dtype=torch.long)
    fold_reports = []
    for held in range(2):
        train = folds.repeat_interleave(5) != held; test = folds == held
        model, trace = fit_head(x[train], delta[train], width, seed + held, CONFIG["fold_steps"])
        with torch.no_grad():
            oof[~train] = model(x[~train])
            choices = values(model, public[test, 1:].flatten(0, 1), 1).argmin(-1)
            backup_choices[test] = choices.reshape(-1, 4)
            actual_selected = realized[test, 1:].flatten(0, 1)[torch.arange(len(choices)), choices]
            # The held-source H1 action sees only its current public child.
            # Its actual result supplies a regression label afterwards. No
            # realized grandchild maximum is used as an action or backup.
            root_targets[test] = torch.exp(torch.tensor(GAMMA * ACTION_COST)) * actual_selected.reshape(-1, 4) - torch.exp(-GAMMA * utility[test, :1])
        with (audit_directory / f"fold-{held}.pt").open("xb") as stream:
            torch.save({"config": model.config, "state": model.state_dict(), "held_fold": held,
                        "fit_cases": torch.unique(cases[~test]), "held_cases": torch.unique(cases[test])}, stream)
        fold_reports.append({"held_fold": held, "fit_source_pairs": int(torch.unique(cases[~test]).numel()),
                             "held_source_pairs": int(torch.unique(cases[test]).numel()), "trace": trace})
        del model
    one, one_trace = fit_head(x, delta, width, seed + 10, CONFIG["steps"])
    two, two_trace = fit_head(public[:, 0], root_targets, width, seed + 20, CONFIG["steps"])
    with (audit_directory / "backups.pt").open("xb") as stream:
        torch.save({"cases": cases, "root_targets": root_targets, "fold_selected_actions": backup_choices}, stream)
    return Policy(one, two), {"width": width, "folds": fold_reports, "one_trace": one_trace, "two_trace": two_trace,
        "H1_OOF_all_action_difference_MSE": float((oof - delta).square().mean()),
        "H1_OOF_zero_baseline_MSE": float(delta.square().mean()),
        "audit_files_sha256": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in audit_directory.iterdir()},
        "backup": "Other-source-fold H1 choice followed by actual held-source result, including first-action cost; paired against actual root stop",
        "scope": "One approximate source-cross-fitted backup. Final refit H1 differs from fold heads; no Bellman/global/conditional error certificate."}


def save(policy, path):
    with path.open("xb") as stream:
        torch.save({"schema": "hepta.next.rich-paired-moment.v1", "heads": [
            {"config": h.config, "state": h.state_dict()} for h in (policy.one, policy.two)]}, stream)


def load(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.next.rich-paired-moment.v1": raise ValueError("Unknown paired policy")
    heads = []
    for item in record["heads"]:
        head = Head(**item["config"]); head.load_state_dict(item["state"], strict=True)
        if any(not torch.isfinite(p).all() for p in head.state_dict().values()): raise ValueError("Nonfinite policy parameter")
        heads.append(head.eval().requires_grad_(False))
    return Policy(*heads)
