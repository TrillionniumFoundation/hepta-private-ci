#!/usr/bin/env python3
"""Bounded CPU F32 incremental-cache qualification of fixed public Qwen edits.

The mapping and source identities extend the 2026-11-04 strict-load receipt.
The original exports and installed dependencies are read-only. This is a short
software consistency test, not an accuracy benchmark or a new weight edit.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import gc
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time


class QualificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise QualificationError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def regular_identity(path):
    value = path.lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
            "Expected an ordinary single-link regular file")
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def digest(path, deadline=None):
    before = regular_identity(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            h.update(block)
            if deadline is not None:
                require(time.monotonic() < deadline, "Total wall budget exhausted during hashing")
    require(regular_identity(path) == before, "Source file changed during reading")
    return h.hexdigest()


def write_new(path, value):
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def public_error(exc, roots):
    message = str(exc)
    for root in roots:
        message = message.replace(str(root), "<input>")
    message = message.replace(str(Path.home()), "<home>")
    return {"type": type(exc).__name__, "message": message[:1200]}


def load_bound_json(path, expected):
    require(digest(path) == expected, "Predeclared JSON identity mismatch")
    return json.loads(path.read_bytes())


def dependency_identity(pins, deadline=None):
    require(sys.version == pins["python_version"], "Python version changed")
    result = {"python_version": sys.version, "dependencies": {}, "transformers_sources": {}}
    for name, expected in pins["dependencies"].items():
        dist = metadata.distribution(name)
        meta, record = dist.read_text("METADATA"), dist.read_text("RECORD")
        observed = {
            "version": dist.version,
            "metadata_sha256": hashlib.sha256(meta.encode()).hexdigest(),
            "record_sha256": hashlib.sha256(record.encode()).hexdigest() if record else None,
        }
        require(observed == expected, "Dependency metadata changed: " + name)
        result["dependencies"][name] = observed
    framework = Path(metadata.distribution("transformers").locate_file("transformers"))
    for rel, expected in pins["transformers_sources"].items():
        source = framework / rel
        observed = {"bytes": regular_identity(source)[2], "sha256": digest(source, deadline)}
        require(observed == expected, "Inspected framework source changed: " + rel)
        result["transformers_sources"][rel] = observed
    return result


def raw_hash(tensor, torch):
    require(tensor.device.type == "cpu" and not tensor.is_meta and tensor.is_contiguous(),
            "Unexpected learned tensor storage")
    return hashlib.sha256(memoryview(tensor.detach().view(torch.uint8).numpy())).hexdigest()


def worker(args):
    start, cpu_start = time.monotonic(), time.process_time()
    protocol = load_bound_json(args.protocol, args.protocol_sha256)
    pins = load_bound_json(args.pins, args.pins_sha256)
    out = args.worker_output
    result = {
        "schema": "hepta.qwen.f32_cache_variant.v1",
        "variant": args.worker,
        "status": "started",
        "started_utc": now(),
        "protocol_sha256": args.protocol_sha256,
        "runtime_pins_sha256": args.pins_sha256,
        "source_sha256": digest(Path(__file__).resolve()),
        "comparisons": [],
        "forwards": {"cached_prefill": 0, "incremental_cached": 0, "full_prefix_reference": 0},
    }
    phase = "dependency_identity"
    try:
        dependency_identity(pins)
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (protocol["budgets"]["worker_cpu_soft_seconds"],
             protocol["budgets"]["worker_cpu_hard_seconds"]),
        )
        phase = "framework_import"
        import torch
        from safetensors import safe_open
        from transformers import AutoTokenizer, initialization
        from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5TextConfig
        from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.set_default_dtype(torch.float32)
        require(not torch.cuda.is_initialized(), "Unexpected accelerator context")
        require(torch.get_num_threads() == 1 and torch.get_num_interop_threads() == 1,
                "Thread contract changed")
        require(len(os.sched_getaffinity(0)) == 1, "Worker is not restricted to one logical CPU")
        result["execution"] = {
            "device": "cpu", "learned_dtype": "torch.float32",
            "source_lifting": "BF16/F32 values lifted exactly to F32; no optimization or requantization",
            "cpu_threads": 1, "interop_threads": 1,
            "attention_implementation": "eager",
            "accelerator_initialized": False,
        }
        phase = "source_contract"
        tensor_document = json.loads((args.exports / "tensor_manifest.json").read_bytes())
        tensors = {row["name"]: row for row in tensor_document["tensors"]}
        language = {name: value for name, value in tensors.items()
                    if name.startswith("model.language_model.")}
        excluded_mtp = sorted(name for name in tensors if name.startswith("mtp."))
        require(len(tensors) == 335 and len(language) == 320 and len(excluded_mtp) == 15,
                "Published tensor namespace changed")
        mapping = {name: "model." + name[len("model.language_model."):] for name in language}
        cfg = Qwen3_5TextConfig.from_pretrained(str(args.exports / "base"), local_files_only=True)
        cfg._attn_implementation = protocol["attention_implementation"]
        cfg.use_cache = True
        require(cfg.tie_word_embeddings is True, "Unexpected output-head contract")
        with torch.device("meta"), initialization.no_init_weights():
            meta_model = Qwen3_5ForCausalLM(copy.deepcopy(cfg))
        meta_model.tie_weights()
        target_shapes = {name: list(value.shape) for name, value in meta_model.state_dict().items()}
        expected_shapes = {mapping[name]: value["shape"] for name, value in language.items()}
        expected_shapes["lm_head.weight"] = language["model.language_model.embed_tokens.weight"]["shape"]
        require(target_shapes == expected_shapes and len(target_shapes) == 321,
                "Mapped text-class key/shape coverage is not exact")
        del meta_model
        gc.collect()

        phase = "strict_f32_lift_and_load"
        print(json.dumps({"variant": args.worker, "phase": phase}), flush=True)
        with initialization.no_init_weights(), torch.device("cpu"):
            model = Qwen3_5ForCausalLM(copy.deepcopy(cfg))
        loaded, lifted_hashes, source_dtypes = {}, {}, {}
        source_path = args.exports / args.worker / "model.safetensors"
        source_stamp = regular_identity(source_path)
        with safe_open(str(source_path), framework="pt", device="cpu") as archive:
            require(set(archive.keys()) == set(tensors), "Export tensor keys changed")
            for name, target in mapping.items():
                original = archive.get_tensor(name)
                expected_hash = tensors[name]["base_sha256" if args.worker == "base" else "p50c_sha256"]
                require(raw_hash(original, torch) == expected_hash, "Source tensor identity mismatch")
                require(original.dtype in (torch.bfloat16, torch.float32), "Unqualified source parameter dtype")
                require(list(original.shape) == tensors[name]["shape"], "Source tensor shape mismatch")
                require(bool(torch.isfinite(original).all()), "Nonfinite source parameter")
                lifted = original.to(dtype=torch.float32)
                require(torch.equal(lifted.to(dtype=original.dtype), original), "Parameter lifting is not exact")
                loaded[target] = lifted
                lifted_hashes[target] = raw_hash(lifted, torch)
                source_dtypes[str(original.dtype)] = source_dtypes.get(str(original.dtype), 0) + 1
            del original, lifted
        require(regular_identity(source_path) == source_stamp, "Source export changed while loading")
        loaded["lm_head.weight"] = loaded["model.embed_tokens.weight"]
        incompatible = model.load_state_dict(loaded, strict=True, assign=True)
        require(not incompatible.missing_keys and not incompatible.unexpected_keys, "Strict load failed")
        model.tie_weights()
        require(model.lm_head.weight is model.model.embed_tokens.weight, "Tied head alias was lost")
        require(all(p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters()),
                "A learned parameter is not CPU F32")
        require(all(b.device.type == "cpu" for b in model.buffers()), "A buffer is not on CPU")
        require(all(bool(torch.isfinite(b).all()) for b in model.buffers()), "A buffer is not finite")
        state = model.state_dict()
        require(all(raw_hash(state[name], torch) == value for name, value in lifted_hashes.items()),
                "Strict load changed a lifted parameter")
        del state, loaded
        gc.collect()
        model.requires_grad_(False)
        model.eval()
        result["strict_load"] = {
            "missing_keys": [], "unexpected_keys": [],
            "source_language_tensors_verified": 320,
            "lifted_parameter_hashes_verified": 320,
            "source_dtypes": source_dtypes,
            "excluded_mtp_count": len(excluded_mtp),
            "tied_embedding_head": True,
            "learned_parameters": sum(p.numel() for p in model.parameters()),
        }
        tokenizer = AutoTokenizer.from_pretrained(
            str(args.exports / "base"), local_files_only=True, trust_remote_code=False)
        encoded = tokenizer(protocol["original_text"], add_special_tokens=False)["input_ids"]
        require([encoded] == protocol["input_ids"], "Original fixed seven-token input changed")
        prefix = torch.tensor(protocol["input_ids"], dtype=torch.long, device="cpu")
        result["input_ids"] = protocol["input_ids"]
        result["appended_tokens"] = []

        def compare(cached_logits, reference_logits, cache, step):
            require(tuple(cached_logits.shape) == (1, 1, cfg.vocab_size), "Unexpected cached logits shape")
            require(cached_logits.shape == reference_logits.shape, "Reference/cached shape mismatch")
            require(cached_logits.dtype == reference_logits.dtype == torch.float32, "Logits are not F32")
            require(bool(torch.isfinite(cached_logits).all()) and bool(torch.isfinite(reference_logits).all()),
                    "Nonfinite compared logits")
            difference = (cached_logits - reference_logits).abs()
            tolerance = protocol["comparator"]["atol"] + protocol["comparator"]["rtol"] * reference_logits.abs()
            within = bool(torch.allclose(
                cached_logits, reference_logits,
                atol=protocol["comparator"]["atol"],
                rtol=protocol["comparator"]["rtol"],
                equal_nan=False))
            cached_token = int(cached_logits[0, -1].argmax())
            reference_token = int(reference_logits[0, -1].argmax())
            observed_length = int(cache.get_seq_length())
            require(observed_length == prefix.shape[1], "Cache sequence length does not match actual prefix")
            row = {
                "step": step, "prefix_tokens": int(prefix.shape[1]),
                "cache_sequence_length": observed_length,
                "cache_class": type(cache).__name__,
                "finite": True, "allclose": within,
                "maximum_absolute_logit_difference": float(difference.max()),
                "maximum_ratio_to_fixed_tolerance": float((difference / tolerance).max()),
                "greedy_equal": cached_token == reference_token,
                "cached_argmax": cached_token, "reference_argmax": reference_token,
                "cached_f32_logits_sha256": raw_hash(cached_logits.contiguous(), torch),
                "reference_f32_logits_sha256": raw_hash(reference_logits.contiguous(), torch),
            }
            result["comparisons"].append(row)
            print(json.dumps({"variant": args.worker, "phase": "compare", "step": step,
                              "prefix_tokens": row["prefix_tokens"], "allclose": within,
                              "greedy_equal": row["greedy_equal"]}), flush=True)
            return cached_token

        phase = "prefill_and_incremental_decode"
        with torch.inference_mode():
            mask = torch.ones_like(prefix)
            cached = model(input_ids=prefix, attention_mask=mask, use_cache=True,
                           logits_to_keep=1, return_dict=True)
            result["forwards"]["cached_prefill"] += 1
            require(cached.past_key_values is not None, "Prefill returned no cache")
            cache = cached.past_key_values
            reference = model(input_ids=prefix, attention_mask=mask, use_cache=False,
                              logits_to_keep=1, return_dict=True)
            result["forwards"]["full_prefix_reference"] += 1
            require(reference.past_key_values is None, "Full-prefix reference unexpectedly returned a cache")
            next_token = compare(cached.logits, reference.logits, cache, 0)
            del cached, reference
            for step in range(1, protocol["incremental_single_token_cache_calls_per_variant"] + 1):
                token = torch.tensor([[next_token]], dtype=torch.long, device="cpu")
                prefix = torch.cat((prefix, token), dim=1)
                result["appended_tokens"].append(next_token)
                mask = torch.ones_like(prefix)
                cached = model(input_ids=token, attention_mask=mask, past_key_values=cache,
                               use_cache=True, logits_to_keep=1, return_dict=True)
                result["forwards"]["incremental_cached"] += 1
                require(cached.past_key_values is not None, "Incremental step returned no cache")
                cache = cached.past_key_values
                reference = model(input_ids=prefix, attention_mask=mask, use_cache=False,
                                  logits_to_keep=1, return_dict=True)
                result["forwards"]["full_prefix_reference"] += 1
                require(reference.past_key_values is None, "Full-prefix reference returned a cache")
                next_token = compare(cached.logits, reference.logits, cache, step)
                del cached, reference

        phase = "post_execution_identity"
        state = model.state_dict()
        require(all(raw_hash(state[name], torch) == value for name, value in lifted_hashes.items()),
                "Forward changed a learned parameter")
        require(regular_identity(source_path) == source_stamp, "Original export identity changed")
        require(not torch.cuda.is_initialized(), "Accelerator context was initialized")
        require([row["prefix_tokens"] for row in result["comparisons"]] ==
                protocol["comparison_prefix_lengths"], "Incomplete comparison prefix set")
        require(len(result["appended_tokens"]) == protocol["generated_tokens_appended_per_variant"],
                "Wrong fixed generation count")
        numeric_pass = all(row["allclose"] and row["greedy_equal"] for row in result["comparisons"])
        result["status"] = "PASS_F32_CACHE_CONSISTENCY" if numeric_pass else "FAIL_F32_CACHE_CONSISTENCY"
        result["checks"] = {
            "learned_f32_parameters_unchanged": True,
            "source_parameter_values_exactly_lifted": True,
            "cpu_only": True,
            "no_benchmark_score": True,
            "original_bf16_runtime_qualified": False,
        }
        del state, model, cache
        gc.collect()
    except Exception as exc:
        result["status"] = "BLOCKED_OR_FAILED"
        result["blocked_phase"] = phase
        result["error"] = public_error(exc, [args.exports, out])
    finally:
        result["finished_utc"] = now()
        result["measurement"] = {
            "wall_seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu_start,
            "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        write_new(out, result)
        print(json.dumps({"variant": args.worker, "status": result["status"],
                          "measurement": result["measurement"]}), flush=True)
    return 0 if result["status"] == "PASS_F32_CACHE_CONSISTENCY" else 2


def owned_memory(root_pid):
    pending, seen, rss, hwm = [root_pid], set(), 0, 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        require(len(seen) <= 32, "Owned worker process-tree bound exceeded")
        try:
            values = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                          if ":" in line)
            rss += int(values.get("VmRSS", "0 kB").split()[0]) * 1024
            hwm += int(values.get("VmHWM", "0 kB").split()[0]) * 1024
            tasks = list(Path(f"/proc/{pid}/task").iterdir())
            require(len(tasks) <= 128, "Owned worker thread inventory bound exceeded")
            for task in tasks:
                try:
                    pending.extend(int(x) for x in (task / "children").read_text().split())
                except OSError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            pass
    return {"rss_bytes": rss, "sum_observed_hwm_bytes": hwm, "process_count": len(seen)}


def stop_owned(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=3)


def supervisor(args):
    started, cpu_started = time.monotonic(), time.process_time()
    os.umask(0o077)
    require(args.output.is_absolute() and not args.output.exists(), "Output must be a new absolute directory")
    args.output.mkdir(mode=0o700)
    result = {
        "schema": "hepta.qwen.f32_cache_qualification.v1",
        "status": "started", "started_utc": now(),
        "protocol_sha256": args.protocol_sha256,
        "runtime_pins_sha256": args.pins_sha256,
        "source_sha256": digest(Path(__file__).resolve()),
        "variants": {}, "processes": [],
        "capability_score_computed": False,
        "original_bf16_or_vllm_benchmark_qualified": False,
    }
    proc = None
    phase = "predeclared_protocol"
    try:
        protocol = load_bound_json(args.protocol, args.protocol_sha256)
        pins = load_bound_json(args.pins, args.pins_sha256)
        deadline = started + protocol["budgets"]["wall_seconds_total"]
        require(protocol["variants"] == ["base", "p50c"], "Variant protocol changed")
        require(protocol["attempts"] == 1, "Only the fixed first attempt is qualified")
        result["protocol"] = protocol
        result["runtime_identity"] = dependency_identity(pins, deadline)
        require(digest(args.original_loader, deadline) == pins["original_loader_sha256"],
                "Original strict-loader source identity changed")
        require(digest(args.original_receipt, deadline) == pins["original_forward_receipt_sha256"],
                "Original strict-load receipt identity changed")
        old_receipt = json.loads(args.original_receipt.read_bytes())
        require(old_receipt["protocol"]["input_ids"] == protocol["input_ids"],
                "Probe input is not the original fixed input")
        phase = "full_export_identity_before_execution"
        source_pins = dict(pins["export_sha256"])
        source_stamps = {}
        for rel, expected in source_pins.items():
            source_stamps[rel] = regular_identity(args.exports / rel)
            require(digest(args.exports / rel, deadline) == expected, "Full original export identity mismatch: " + rel)
        export_receipt = json.loads((args.exports / "receipt.json").read_bytes())
        for rel, entry in export_receipt["text_assets"].items():
            require(rel.startswith(("base/", "p50c/")) and ".." not in Path(rel).parts,
                    "Unexpected export asset path")
            source_pins[rel] = entry["sha256"]
            source_stamps[rel] = regular_identity(args.exports / rel)
            require(digest(args.exports / rel, deadline) == entry["sha256"],
                    "Original text-asset content identity mismatch")
        require(all(regular_identity(args.exports / rel) == stamp for rel, stamp in source_stamps.items()),
                "An original input changed during preflight")
        result["input_sha256"] = source_pins
        result["original_loader_sha256"] = pins["original_loader_sha256"]
        result["original_forward_receipt_sha256"] = pins["original_forward_receipt_sha256"]
        if hasattr(os, "sched_setaffinity"):
            available = sorted(os.sched_getaffinity(0))
            require(bool(available), "No CPU available to the caller")
            os.sched_setaffinity(0, {available[0]})
        result["execution_cpu_affinity_count"] = len(os.sched_getaffinity(0))
        child_env = dict(os.environ)
        child_env.update({
            "CUDA_VISIBLE_DEVICES": "", "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        for variant in protocol["variants"]:
            phase = variant + "_owned_worker"
            require(time.monotonic() < deadline, "Total wall budget exhausted before worker")
            output = args.output / (variant + ".json")
            argv = [
                sys.executable, "-B", str(Path(__file__).resolve()),
                "--protocol", str(args.protocol), "--protocol-sha256", args.protocol_sha256,
                "--pins", str(args.pins), "--pins-sha256", args.pins_sha256,
                "--exports", str(args.exports), "--worker", variant,
                "--worker-output", str(output),
            ]
            w, c = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
            observed_peak, observed_hwm, max_processes = 0, 0, 0
            termination = None
            with (args.output / (variant + ".stdout.log")).open("xb") as stdout, \
                    (args.output / (variant + ".stderr.log")).open("xb") as stderr:
                proc = subprocess.Popen(argv, stdout=stdout, stderr=stderr, env=child_env,
                                        start_new_session=True, stdin=subprocess.DEVNULL)
                while proc.poll() is None:
                    memory = owned_memory(proc.pid)
                    observed_peak = max(observed_peak, memory["rss_bytes"])
                    observed_hwm = max(observed_hwm, memory["sum_observed_hwm_bytes"])
                    max_processes = max(max_processes, memory["process_count"])
                    if max(observed_peak, observed_hwm) > protocol["budgets"]["rss_monitor_threshold_bytes"]:
                        termination = "OWNED_PROCESS_RSS_THRESHOLD"
                        stop_owned(proc)
                        break
                    if time.monotonic() >= deadline:
                        termination = "TOTAL_WALL_BUDGET"
                        stop_owned(proc)
                        break
                    time.sleep(protocol["budgets"]["rss_poll_seconds"])
                return_code = proc.wait()
            cc = resource.getrusage(resource.RUSAGE_CHILDREN)
            process_record = {
                "variant": variant, "exit_code": return_code,
                "wall_seconds": time.monotonic() - w,
                "child_cpu_seconds": (cc.ru_utime + cc.ru_stime) - (c.ru_utime + c.ru_stime),
                "observed_peak_rss_sum_bytes": observed_peak,
                "observed_peak_hwm_sum_bytes": observed_hwm,
                "maximum_observed_owned_processes": max_processes,
                "termination_reason": termination,
                "stdout_sha256": digest(args.output / (variant + ".stdout.log")),
                "stderr_sha256": digest(args.output / (variant + ".stderr.log")),
            }
            result["processes"].append(process_record)
            if output.exists():
                v = json.loads(output.read_bytes())
                result["variants"][variant] = v
                if v.get("measurement", {}).get("peak_rss_kib_linux", 0) * 1024 > protocol["budgets"]["rss_monitor_threshold_bytes"]:
                    process_record["termination_reason"] = process_record["termination_reason"] or "FINAL_REPORTED_RSS_OVER_BUDGET"
            else:
                result["variants"][variant] = {"status": "NO_COMPLETED_WORKER_RECEIPT"}
            proc = None
            if termination == "TOTAL_WALL_BUDGET":
                break
        phase = "source_identity_after_execution"
        require(all(regular_identity(args.exports / rel) == stamp for rel, stamp in source_stamps.items()),
                "An original export/config identity changed")
        require({rel: digest(args.exports / rel, deadline) for rel in source_pins} == source_pins,
                "An original export/config content changed")
        require(dependency_identity(pins, deadline) == result["runtime_identity"],
                "Execution dependency identity changed")
        require(digest(args.original_loader, deadline) == pins["original_loader_sha256"],
                "Original loader changed")
        passed = (
            set(result["variants"]) == set(protocol["variants"])
            and all(v["status"] == "PASS_F32_CACHE_CONSISTENCY" for v in result["variants"].values())
            and all(p["exit_code"] == 0 and p["termination_reason"] is None for p in result["processes"])
            and time.monotonic() < deadline
        )
        result["status"] = "PASS_F32_SHORT_CACHE_QUALIFICATION" if passed else "FAIL_OR_INCOMPLETE_F32_CACHE_QUALIFICATION"
        result["original_exports_unchanged"] = True
        result["named_runtime_sources_and_dependency_metadata_unchanged"] = True
    except Exception as exc:
        result["status"] = "BLOCKED_OR_FAILED"
        result["blocked_phase"] = phase
        result["error"] = public_error(exc, [args.exports, args.output, args.protocol, args.pins])
    finally:
        if proc is not None:
            stop_owned(proc)
        result["finished_utc"] = now()
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["measurement"] = {
            "wall_seconds": time.monotonic() - started,
            "supervisor_cpu_seconds": time.process_time() - cpu_started,
            "owned_child_cpu_seconds": child.ru_utime + child.ru_stime,
            "supervisor_peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        write_new(args.output / "receipt.json", result)
        print(json.dumps({"status": result["status"],
                          "receipt_sha256": digest(args.output / "receipt.json"),
                          "measurement": result["measurement"]}), flush=True)
    return 0 if result["status"] == "PASS_F32_SHORT_CACHE_QUALIFICATION" else 2


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--protocol-sha256", required=True)
    p.add_argument("--pins", type=Path, required=True)
    p.add_argument("--pins-sha256", required=True)
    p.add_argument("--exports", type=Path, required=True)
    p.add_argument("--original-loader", type=Path)
    p.add_argument("--original-receipt", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--worker", choices=("base", "p50c"))
    p.add_argument("--worker-output", type=Path)
    a = p.parse_args()
    if a.worker:
        require(a.worker_output is not None, "Worker output is required")
    else:
        require(a.output is not None and a.original_loader is not None and a.original_receipt is not None,
                "Supervisor source/output arguments are required")
    return a


if __name__ == "__main__":
    arguments = parse()
    sys.exit(worker(arguments) if arguments.worker else supervisor(arguments))
