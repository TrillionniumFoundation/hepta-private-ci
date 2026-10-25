"""Future warm-load worker. Importing this module never imports a model runtime."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


GENERATION_LIMITS = {
    "calls": 20,
    "prompt_tokens": 192,
    "new_tokens": 16,
    "input_tokens_total": 3840,
    "output_tokens_total": 320,
}


def emit(value):
    print(json.dumps(value, sort_keys=True, allow_nan=False), flush=True)


class GenerationGuard:
    """Bound the real generate entry, including unsuccessful invocation attempts."""

    def __init__(self, generate, limits, context, output=emit):
        if limits != GENERATION_LIMITS:
            raise ValueError("exact frozen generation limits required")
        self.generate, self.limits, self.context, self.output = (
            generate,
            dict(limits),
            context,
            output,
        )
        self.calls, self.input_tokens, self.output_tokens, self.closed = 0, 0, 0, False

    def __call__(self, *args, **kwargs):
        if self.closed:
            raise ValueError("generation guard closed after failure")
        try:
            shape = tuple(kwargs["input_ids"].shape)
            if (
                args
                or len(shape) != 2
                or shape[0] != 1
                or not 1 <= shape[1] <= self.limits["prompt_tokens"]
                or tuple(kwargs["attention_mask"].shape) != shape
                or type(kwargs.get("max_new_tokens")) is not int
                or kwargs["max_new_tokens"] != self.limits["new_tokens"]
                or self.calls >= self.limits["calls"]
                or self.input_tokens + shape[1] > self.limits["input_tokens_total"]
            ):
                raise ValueError(
                    "complete prompt or decoder invocation exceeds frozen budget"
                )
            self.calls += 1
            self.input_tokens += shape[1]
            identity = dict(self.context(), call_number=self.calls)
            self.output(
                {"event": "decoder_started", **identity, "input_tokens": shape[1]}
            )
            value = self.generate(**kwargs)
            output_shape = tuple(value.shape)
            generated = (
                output_shape[1] - shape[1]
                if len(output_shape) == 2 and output_shape[0] == 1
                else None
            )
            valid = (
                generated is not None
                and 1 <= generated <= self.limits["new_tokens"]
                and self.output_tokens + generated <= self.limits["output_tokens_total"]
            )
            self.output(
                {
                    "event": "decoder_finished",
                    **identity,
                    "input_tokens": shape[1],
                    "output_tokens": generated,
                    "within_frozen_output_budget": valid,
                }
            )
            if generated is not None and generated >= 0:
                self.output_tokens += generated
            if not valid:
                raise ValueError("generated output exceeds frozen budget")
            return value
        except Exception:
            self.closed = True
            raise


def source_query(request, job):
    """Exact typed retrieval from all two-rule source outcomes, not a gold table."""
    observations, read_bytes = {}, 0
    for entry in request["sources"]:
        raw = Path(entry["path"]).read_bytes()
        if (
            len(raw) != entry["bytes"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError("source observation changed")
        row = json.loads(raw)
        if row["code"] in observations:
            raise ValueError("ambiguous typed source identity")
        observations[row["code"]] = row
        read_bytes += len(raw)
    if not job["codes"] or not set(job["codes"]) <= set(observations):
        raise ValueError("unsupported typed source query")
    accepted = [
        operation
        for operation in request["operations"]
        if all(
            all(
                observations[code]["outcomes"][operation][phase]["returncode"] == 0
                for phase in ("action", "after", "semantic")
            )
            for code in job["codes"]
        )
    ]
    if not accepted:
        raise ValueError("sources do not establish a common successful operation")
    return {
        "text": accepted[0],
        "source_bytes_read": read_bytes,
        "input_tokens": 0,
        "generated_tokens": 0,
        "support_roots": [entry["sha256"] for entry in request["sources"]],
    }


def sample_loop(jobs, query, output=emit):
    """Sequential closed-loop samples; stop on failure and never silently retry."""
    for job in jobs:
        output({"event": "query_started", "phase": job["phase"], "index": job["index"]})
        start, cpu = time.monotonic_ns(), time.process_time_ns()
        result, error = None, None
        try:
            result = query(job)
        except Exception as caught:
            error = repr(caught)[:2048]
        end = time.monotonic_ns()
        output(
            {
                "event": "sample",
                "phase": job["phase"],
                "index": job["index"],
                "query_id": job["query_id"],
                "start_ns": start,
                "end_ns": end,
                "wall_ns": end - start,
                "cpu_ns": time.process_time_ns() - cpu,
                "success": error is None,
                "result": result,
                "error": error,
            }
        )
        if error is not None:
            return False
    return True


def run(request):
    start, cpu = time.monotonic_ns(), time.process_time_ns()
    if request.get("generation_limits") != GENERATION_LIMITS:
        raise ValueError("worker request is not bound to frozen generation limits")
    current = {}
    if request["mode"] == "memory":
        # Only this explicitly executed branch can allocate the pretrained model.
        sys.path.insert(0, request["model_code"])
        import torch
        from parametric_model import SourceMemoryCell

        torch.set_num_threads(1)
        payload = request["model_request"]
        cell = SourceMemoryCell(
            Path(payload["model"]), rank=payload["rank"], seed=payload["seed"]
        )
        cell.load(
            Path(payload["snapshot"]),
            expected_manifest_sha256=payload["manifest_sha256"],
            scope=payload["scope"],
            allowed_roots=set(payload["allowed_roots"]),
            revoked=set(),
        )
        cell.reader.model.generate = GenerationGuard(
            cell.reader.model.generate,
            request["generation_limits"],
            lambda: dict(current),
        )

        def query(job):
            current.update(phase=job["phase"], index=job["index"])
            row = cell.generate([job["question"]])[0]
            return dict(row, source_bytes_read=0)
    elif request["mode"] == "retrieval":

        def query(job):
            return source_query(request, job)
    else:
        raise ValueError("unregistered warm-load arm")
    emit(
        {
            "event": "startup",
            "mode": request["mode"],
            "wall_ns": time.monotonic_ns() - start,
            "cpu_ns": time.process_time_ns() - cpu,
            "generation_limits": request["generation_limits"],
            "protocol_sha256": request["protocol_sha256"],
            "basis": "imports and loader inside worker; parent process receipt also includes interpreter startup",
        }
    )
    success = sample_loop(request["jobs"], query)
    emit(
        {
            "event": "finished",
            "success": success,
            "optimizer_updates": 0,
            "explicit_feature_calls": 0,
            "autoregressive_forward_steps": None,
        }
    )
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    raw = args.request.read_bytes()
    if len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("bounded pinned request required")
    sys.exit(0 if run(json.loads(raw)) else 1)
