"""One fresh-base training attempt, with actual forward observation and no retry."""

import argparse
import os
from pathlib import Path
import resource
import time

from retention_common import digest, read_json, require, retain, verify_source_pin
from memory_service import MemoryService
from parameter_publication import publish
from service_types import verify_snapshot
from training_backend import seal_candidate, verify_candidate


class ForwardAudit:
    """Observe the public model call boundary, including incomplete forwards."""

    def __init__(self, limit):
        self.limit = limit
        self.entered = []
        self.completed = 0
        self.over_budget_calls = 0

    def before(self, _module, args, kwargs):
        if len(self.entered) >= self.limit:
            self.over_budget_calls += 1
            raise ValueError("training forward reservation exhausted")
        ids = kwargs.get("input_ids", args[0] if args else None)
        require(
            ids is not None and len(ids.shape) == 2 and ids.shape[0] == 1,
            "registered single-example forward required",
        )
        self.entered.append(int(ids.numel()))

    def after(self, _module, _args, _kwargs, _output):
        self.completed += 1

    def receipt(self):
        return dict(
            entered_model_forwards=len(self.entered),
            completed_model_forwards=self.completed,
            entered_input_tokens=sum(self.entered),
            input_tokens_per_entered_forward=list(self.entered),
            over_budget_calls=self.over_budget_calls,
        )


def train(request):
    required = {
        "schema",
        "trial_id",
        "source_identity_path",
        "source_identity_sha256",
        "base",
        "base_identity",
        "service_root",
        "snapshot_path",
        "snapshot_sha256",
        "scope",
        "cell_id",
        "role",
        "seed",
        "rank",
        "torch_threads",
        "actual_forward_budget",
        "templates",
        "name",
        "objective",
        "learning_rate",
        "steps",
    }
    require(
        set(request) == required
        and request["schema"] == "hepta.retention-v2.train-request.v1",
        "closed retention training request required",
    )
    require(
        (request["rank"], request["torch_threads"], request["actual_forward_budget"])
        == (8, 2, 256),
        "unregistered screen resource policy",
    )
    require(
        (request["objective"], request["learning_rate"], request["steps"])
        in (
            ("completion_ce", 0.001, 256),
            ("completion_ce", 0.01, 256),
            ("source_value_margin_v2", 0.01, 128),
        ),
        "unregistered training arm",
    )
    source = verify_source_pin(
        request["source_identity_path"], request["source_identity_sha256"]
    )
    snapshot = verify_snapshot(read_json(request["snapshot_path"]))
    require(digest(snapshot) == request["snapshot_sha256"], "training snapshot changed")
    service = MemoryService(
        request["service_root"], request["scope"], request["cell_id"], request["role"]
    )
    require(
        service.snapshot() == snapshot, "live source state differs from frozen trial"
    )
    require(
        not set(snapshot["revoked"]) & {f["source_digest"] for f in snapshot["facts"]},
        "withdrawn root in live training facts",
    )
    require(
        request["steps"] >= len(snapshot["facts"]) * len(request["templates"]),
        "every live source/template must be exposed",
    )
    lease = service.queue.claim("retention-v2-screen", lease_seconds=900)
    require(
        lease is not None and lease.snapshot == snapshot and lease.candidate is None,
        "exact new source lease required; no retry or learned continuation",
    )
    audit = ForwardAudit(request["actual_forward_budget"])
    started = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = dict(
        schema="hepta.retention-v2.train-result.v1",
        trial_id=request["trial_id"],
        request_sha256=digest(request),
        status="failed",
        pid=os.getpid(),
        reserved_training_forwards=request["actual_forward_budget"],
        charged_training_forwards=request["actual_forward_budget"],
        budget_refund=0,
        write_receipt=None,
        publication=None,
        error=None,
        source_identity_sha256=digest(source),
        source_pin_after=False,
        production_accepted=False,
    )
    try:
        import torch
        from parametric_model import SourceMemoryCell

        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        if hasattr(os, "sched_getaffinity"):
            affinity = sorted(os.sched_getaffinity(0))[:2]
            os.sched_setaffinity(0, affinity)
            result["cpu_affinity"] = affinity
        cell = SourceMemoryCell(
            request["base"], rank=request["rank"], seed=request["seed"]
        )
        require(
            cell.reader.identity == request["base_identity"],
            "loaded fixed base identity changed",
        )
        cell.reset(request["scope"])
        before_hook = cell.reader.model.register_forward_pre_hook(
            audit.before, with_kwargs=True
        )
        after_hook = cell.reader.model.register_forward_hook(
            audit.after, with_kwargs=True
        )
        try:
            receipt = cell.fit_sources(
                snapshot["facts"],
                request["steps"],
                request["learning_rate"],
                request["templates"],
                objective=request["objective"],
            )
        finally:
            before_hook.remove()
            after_hook.remove()
        result["write_receipt"] = receipt
        require(
            audit.completed
            == len(audit.entered)
            == receipt["actual_model_forwards"]
            == request["actual_forward_budget"]
            and audit.over_budget_calls == 0,
            "actual forward observation differs from reserved/returned charge",
        )
        require(
            sum(audit.entered) == receipt["input_tokens"],
            "actual input token charge differs",
        )
        require(
            receipt["initialization"] == "frozen_base"
            and receipt["inherited_roots"] == []
            and receipt["learned_parent_manifest_sha256"] is None
            and all(receipt["example_visits"]),
            "fresh-base full source replay required",
        )
        destination = service.artifacts / "screen-candidate"
        destination.mkdir(exist_ok=False)
        checkpoint = destination / "checkpoint"
        manifest = cell.save(checkpoint)
        candidate = seal_candidate(snapshot, checkpoint, manifest)
        verify_candidate(candidate, snapshot, service.artifacts)
        service.queue.stage(lease, candidate)
        result["publication"] = publish(service, lease)
        require(
            result["publication"]["status"] == "published",
            "fresh candidate not published",
        )
        result["status"] = "published"
    except Exception as error:
        result["error"] = repr(error)[:2000]
        try:
            service.queue.fail(lease, error)
        except Exception as lease_error:
            result["lease_failure"] = str(lease_error)
    finally:
        result["forward_audit"] = audit.receipt()
        after = resource.getrusage(resource.RUSAGE_SELF)
        result.update(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=after.ru_utime
            + after.ru_stime
            - usage.ru_utime
            - usage.ru_stime,
            peak_self_rss_kib=after.ru_maxrss,
        )
        try:
            verify_source_pin(
                request["source_identity_path"], request["source_identity_sha256"]
            )
            result["source_pin_after"] = True
        except Exception as error:
            result["source_pin_error"] = repr(error)[:2000]
            result["status"] = "failed"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    result = dict(
        schema="hepta.retention-v2.train-result.v1",
        status="failed",
        charged_training_forwards=256,
        budget_refund=0,
        actual_forwards_unknown=True,
        production_accepted=False,
    )
    try:
        request = read_json(args.request)
        require(
            digest(request) == args.request_sha256,
            "registered training request changed",
        )
        result = train(request)
    except Exception as error:
        result["error"] = repr(error)[:2000]
    retain(args.request.parent / "train-result.json", result)
    print(result["status"], flush=True)
    if result["status"] != "published":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
