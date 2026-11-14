"""V5 research-only physical frozen-stem / matched Cell-Head producer.

TRAIN and PREDICT are separate invocations and accept disjoint inputs. The
operator supplies already verified and offline-staged pretrained files. Exact
LocalEncoder checks actual on-disk safetensors; no download/fallback or NDU,
authority, publisher authentication, production selection, or baseline synthesis.
"""
from __future__ import annotations

import argparse
from importlib import metadata
import math
import os
from pathlib import Path
import platform
import tempfile
import time

import psutil
import torch
from safetensors.torch import load as safetensors_load
from safetensors.torch import save as safetensors_save
from torch.nn import functional as F

from multimodal_alignment_contract import (
    canonical, load_pinned_document, load_pinned_jsonl, sha, write_new,
)
from multimodal_bridge import ContractError, _digest
from multimodal_candidate_gate import MAX_CASES, RESULT, _name, validate_plan
from multimodal_head import StateGatedCellHead
from multimodal_real_encoder import validated_profile

SCHEMA = "hepta.pinned-stem-cell-train.v5"
EVIDENCE = "hepta.pinned-stem-cell-predict-evidence.v5"
STATE_WIDTH = 64
RANK = 8
TRAIN_BATCH = 16
LEARNING_RATE = 0.01
WEIGHT_DECAY = 0.0
MAX_HEAD_BYTES = 16 * 1024 * 1024


def text_input_digest(scope: str, text: str, state: list[float]) -> str:
    return sha(canonical(["hepta.stem-cell-input.v5", scope, text, state]))


def _validate_examples(plan: dict, rows: list[dict], phase: str,
                       train_texts: set[str] | None = None) -> tuple[list[str], torch.Tensor, list[int]]:
    if phase not in {"train", "future"}:
        raise ContractError("unregistered input phase")
    if not 16 <= len(rows) <= MAX_CASES:
        raise ContractError("insufficient or excessive cases")
    exact = {"case_id", "group_id", "scope", "observed_at", "split", "text", "state"}
    if phase == "train":
        exact.add("label")
    else:
        exact.add("input_sha256")
    ids, groups, texts, states, labels = [], [], [], [], []
    metadata = []
    for row in rows:
        if type(row) is not dict or set(row) != exact or row["split"] != phase:
            raise ContractError("unexpected input fields or phase; future labels forbidden")
        cid, gid = _name(row["case_id"], "case id"), _name(row["group_id"], "group id")
        if row["scope"] != plan["scope"]:
            raise ContractError("scope isolation violated")
        stamp = row["observed_at"]
        if type(stamp) is not int or not 0 <= stamp < 2**63:
            raise ContractError("invalid observation timestamp")
        if ((phase == "train" and stamp > plan["train_cutoff"])
                or (phase == "future" and not plan["future_start"] <= stamp <= plan["future_end"])):
            raise ContractError("train/future chronology violated")
        text = row["text"]
        if type(text) is not str or not 1 <= len(text.encode("utf-8")) <= 8192:
            raise ContractError("invalid or unbounded text")
        state = row["state"]
        if (type(state) is not list or len(state) != STATE_WIDTH
                or any(type(v) not in (float, int) or not math.isfinite(v) or not -8 <= v <= 8
                       for v in state)):
            raise ContractError("invalid local state or width")
        if phase == "train":
            if type(row["label"]) is not int or not 0 <= row["label"] < plan["classes"]:
                raise ContractError("invalid training label")
            labels.append(row["label"])
        else:
            if row["input_sha256"] != text_input_digest(row["scope"], text, state):
                raise ContractError("future input digest mismatch")
            if train_texts is None or sha(text.encode()) in train_texts:
                raise ContractError("identical text appears in train/future")
            metadata.append({k: row[k] for k in
                             ("case_id", "group_id", "scope", "observed_at", "input_sha256")})
        ids.append(cid)
        groups.append(sha(gid.encode()))
        texts.append(text)
        states.append(state)
    if ids != sorted(set(ids)):
        raise ContractError("noncanonical or duplicate case ids")
    if phase == "train":
        if sorted(set(groups)) != plan["train_group_sha256s"]:
            raise ContractError("training group census differs from frozen plan")
    else:
        if set(groups) & set(plan["train_group_sha256s"]):
            raise ContractError("future group leaks into train")
        if sha(b"".join(canonical(v) for v in metadata)) != plan["future_source_sha256"]:
            raise ContractError("future cohort does not match frozen source-only plan")
    return texts, torch.tensor(states, dtype=torch.float32), labels


def _candidate(plan: dict, name: str, profile: dict, profile_sha: str) -> dict:
    validate_plan(plan)
    if name == "no_change":
        raise ContractError("no_change must be an independent frozen baseline, not synthesized")
    declared = next((x for x in plan["candidates"] if x["name"] == name), None)
    if declared is None or declared["profile_sha256"] != profile_sha:
        raise ContractError("undeclared candidate or profile drift")
    parsed = validated_profile(profile, profile_sha)
    if parsed.candidate != name or parsed.snapshot_digest != declared["snapshot_sha256"]:
        raise ContractError("candidate snapshot drift")
    return {"declaration": declared, "profile": parsed}


def _head(plan: dict, width: int) -> StateGatedCellHead:
    head = StateGatedCellHead(width, STATE_WIDTH, RANK, plan["classes"])
    if head.parameter_count() != plan["head_parameters"]:
        raise ContractError("head width/classes yield unequal trainable parameter budget")
    return head


def _encode(backend, texts: list[str], profile) -> torch.Tensor:
    before = backend.forward_calls
    batches = []
    for start in range(0, len(texts), profile.batch_size):
        group = texts[start:start + profile.batch_size]
        value = (backend.encode(group) if profile.pooling == "attention-mask-mean"
                 else backend.encode(group, pooling=profile.pooling))
        if (not isinstance(value, torch.Tensor) or value.ndim != 2
                or tuple(value.shape) != (len(group), profile.expected_width)
                or value.device.type != "cpu" or value.dtype != torch.float32
                or not bool(torch.isfinite(value).all())
                or backend.forward_calls != before + len(batches) + 1):
            raise ContractError("real physical encoder forward/feature contract violated")
        if profile.normalization == "unit_l2":
            norms = torch.linalg.vector_norm(value, dim=1, keepdim=True)
            if not bool((norms > 0).all()) or not bool(torch.isfinite(norms).all()):
                raise ContractError("cannot normalize zero or nonfinite feature")
            value = value / norms
        batches.append(value.detach().clone())
    return torch.cat(batches, dim=0)


def _measurement_start() -> tuple[int, int, int]:
    return time.perf_counter_ns(), time.process_time_ns(), psutil.Process().memory_info().rss


def _measurement_done(begin: tuple[int, int, int]) -> dict:
    wall = time.perf_counter_ns() - begin[0]
    cpu = time.process_time_ns() - begin[1]
    rss = max(begin[2], psutil.Process().memory_info().rss)
    if wall <= 0 or cpu <= 0 or rss <= 0:
        raise ContractError("real wall/CPU/RSS observation required")
    return {"wall_ns": wall, "cpu_ns": cpu, "resident_bytes": rss}


def _pkg(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError as exc:
        raise ContractError("missing pinned execution dependency: " + name) from exc


def host_identity() -> dict:
    """Machine *class* identity, not a TPM/physical-device attestation."""
    if torch.cuda.is_available():
        raise ContractError("CPU-only matched comparison required")
    machine = {"system": platform.system(), "machine": platform.machine(),
               "cpu_count": os.cpu_count(), "processor": platform.processor(),
               "memory_total_bytes": psutil.virtual_memory().total, "device": "cpu"}
    environment = {"python": platform.python_version(), "torch": _pkg("torch"),
                   "transformers": _pkg("transformers"),
                   "safetensors": _pkg("safetensors"), "numpy": _pkg("numpy"),
                   "tokenizers": _pkg("tokenizers"), "huggingface-hub": _pkg("huggingface-hub"),
                   "psutil": _pkg("psutil"), "algorithm": SCHEMA,
                   "optimizer": "AdamW-lr0.01-wd0-batch16-gradient-clipped1",
                   "head": "StateGatedCellHead-state64-rank8", "torch_threads": 1}
    return {"hardware": machine, "environment": environment,
            "hardware_sha256": sha(canonical(machine)),
            "environment_sha256": sha(canonical(environment)),
            "independently_attested": False}


def _host_check(plan: dict, host: dict) -> None:
    if (plan["hardware_sha256"] != host["hardware_sha256"]
            or plan["environment_sha256"] != host["environment_sha256"]):
        raise ContractError("physical machine-class or pinned software environment changed")


def _material(backend, expected_identity: str) -> None:
    # Production result paths may not accept a substitute or simulated backend.
    from execution import LocalEncoder
    if type(backend) is not LocalEncoder or backend.simulated is not False:
        raise ContractError("physical pinned LocalEncoder required, no mock fallback")
    # LocalEncoder identity is the complete SHA-pinned snapshot manifest.
    if type(getattr(backend, "identity", None)) is not str or backend.identity != expected_identity:
        raise ContractError("backend material identity mismatch")


def _fit_head(plan: dict, x: torch.Tensor, state: torch.Tensor, labels: list[int]) -> tuple[StateGatedCellHead, dict]:
    if (len(x) != len(state) or len(x) != len(labels) or x.ndim != 2
            or x.device.type != "cpu" or x.dtype != torch.float32):
        raise ContractError("mismatched frozen training vectors")
    with torch.random.fork_rng():
        torch.manual_seed(plan["seed"])
        head = _head(plan, x.shape[1]).train()
    opt = torch.optim.AdamW(head.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    generator = torch.Generator(device="cpu").manual_seed(plan["seed"])
    truth = torch.tensor(labels, dtype=torch.long)
    losses = []
    for k in range(plan["train_steps"]):
        indices = torch.randint(len(x), (min(TRAIN_BATCH, len(x)),), generator=generator)
        opt.zero_grad(set_to_none=True)
        loss = F.cross_entropy(head(x[indices].detach(), state[indices].detach()), truth[indices])
        if not bool(torch.isfinite(loss)):
            raise ContractError("nonfinite Cell training loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1., error_if_nonfinite=True)
        opt.step()
        if not all(bool(torch.isfinite(v).all()) for v in head.parameters()):
            raise ContractError("nonfinite updated Head")
        if k == 0 or k == plan["train_steps"]-1:
            losses.append(float(loss.detach().item()))
    return head.eval(), {"first_step_loss": losses[0], "last_step_loss": losses[-1],
                         "physical_gradient_steps": plan["train_steps"],
                         "samples_per_step": min(TRAIN_BATCH, len(x))}


def _save_dir(output: Path, contents: dict[str, bytes]) -> None:
    if (output.exists() or output.is_symlink() or not output.parent.is_dir()
            or output.parent.is_symlink()):
        raise ContractError("new output directory with safe parent required")
    with tempfile.TemporaryDirectory(prefix=".hepta-candidate-", dir=output.parent) as tmp:
        directory = Path(tmp)
        for name, raw in contents.items():
            if "/" in name or not name:
                raise ContractError("invalid output member")
            with (directory / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(directory, output)
        handle = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def train(plan: dict, plan_sha: str, profile: dict, profile_sha: str, name: str,
          rows: list[dict], train_sha: str, backend, host: dict) -> tuple[bytes, dict]:
    _digest(plan_sha)
    if sha(canonical(plan)) != plan_sha or plan["train_sha256"] != train_sha:
        raise ContractError("frozen plan/training file identity drift")
    declaration = _candidate(plan, name, profile, profile_sha)
    _host_check(plan, host)
    texts, states, labels = _validate_examples(plan, rows, "train")
    identity = declaration["profile"].snapshot_digest
    _material(backend, identity)
    began = _measurement_start()
    initial = backend.forward_calls
    features = _encode(backend, texts, declaration["profile"])
    model, learning = _fit_head(plan, features, states, labels)
    state = {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()}
    raw_head = safetensors_save(state)
    if not 0 < len(raw_head) <= MAX_HEAD_BYTES:
        raise ContractError("head checkpoint exceeds permitted size")
    backend.close()  # verifies model/checkpoint bytes after physical execution
    usage = _measurement_done(began)
    calls = backend.forward_calls - initial
    if calls != math.ceil(len(texts)/declaration["profile"].batch_size):
        raise ContractError("unaccounted actual training model forwards")
    receipt = {"schema": SCHEMA, "plan_sha256": plan_sha, "candidate": name,
               "profile_sha256": profile_sha, "snapshot_sha256": identity,
               "train_sha256": train_sha, "future_source_sha256": plan["future_source_sha256"],
               "head_sha256": sha(raw_head), "head_parameters": model.parameter_count(),
               "train_steps": plan["train_steps"], "seed": plan["seed"],
               "classes": plan["classes"], "feature_width": declaration["profile"].expected_width,
               "train_cases": len(rows), "training_group_sha256s": plan["train_group_sha256s"],
               "training_text_sha256s": sorted({sha(t.encode()) for t in texts}),
               "normalization": declaration["profile"].normalization,
               "pooling": "attention-mask-mean", "model_forwards": calls,
               "observed_resources": usage, "learning": learning,
               "checkpoint_locally_verified": True, "publisher_authenticated": False,
               "actual_pretrained_model_proven": False, "independent_ndu_verified": False,
               "production_accepted": False}
    return raw_head, receipt


def _restore_head(plan: dict, manifest: dict, raw: bytes, width: int) -> StateGatedCellHead:
    if not 0 < len(raw) <= MAX_HEAD_BYTES or sha(raw) != manifest.get("head_sha256"):
        raise ContractError("tampered or oversized Head artifact")
    restored = _head(plan, width)
    saved = safetensors_load(raw)
    expected = restored.state_dict()
    if set(saved) != set(expected) or any(
            saved[k].shape != expected[k].shape or saved[k].dtype != expected[k].dtype
            or not bool(torch.isfinite(saved[k]).all()) for k in expected):
        raise ContractError("wrong or corrupted exact Head tensor inventory")
    restored.load_state_dict(saved, strict=True)
    return restored.eval()


def predict(plan: dict, plan_sha: str, profile: dict, profile_sha: str,
            name: str, train_receipt: dict, train_receipt_sha: str,
            head_bytes: bytes, future: list[dict], backend, host: dict) -> tuple[dict, dict]:
    if sha(canonical(plan)) != plan_sha:
        raise ContractError("changed frozen evaluation plan")
    declaration = _candidate(plan, name, profile, profile_sha)
    _host_check(plan, host)
    if (sha(canonical(train_receipt)) != train_receipt_sha or train_receipt.get("schema") != SCHEMA
            or train_receipt.get("plan_sha256") != plan_sha
            or train_receipt.get("candidate") != name
            or train_receipt.get("profile_sha256") != profile_sha
            or train_receipt.get("snapshot_sha256") != declaration["profile"].snapshot_digest
            or train_receipt.get("train_sha256") != plan["train_sha256"]
            or train_receipt.get("future_source_sha256") != plan["future_source_sha256"]
            or train_receipt.get("seed") != plan["seed"]
            or train_receipt.get("head_parameters") != plan["head_parameters"]
            or train_receipt.get("train_steps") != plan["train_steps"]
            or train_receipt.get("feature_width") != declaration["profile"].expected_width
            or train_receipt.get("classes") != plan["classes"]
            or train_receipt.get("training_group_sha256s") != plan["train_group_sha256s"]
            or train_receipt.get("checkpoint_locally_verified") is not True):
        raise ContractError("unbound or unverified Head training receipt")
    texts, states, _ = _validate_examples(
        plan, future, "future", set(train_receipt["training_text_sha256s"]))
    model = _restore_head(plan, train_receipt, head_bytes, declaration["profile"].expected_width)
    _material(backend, declaration["profile"].snapshot_digest)
    began = _measurement_start()
    initial = backend.forward_calls
    features = _encode(backend, texts, declaration["profile"])
    with torch.no_grad():
        p = model(features, states).softmax(-1)
        if p.shape != (len(future), plan["classes"]) or not bool(torch.isfinite(p).all()):
            raise ContractError("nonfinite predicted probabilities")
        probs = p.detach().cpu().tolist()
    backend.close()
    resource = _measurement_done(began)
    calls = backend.forward_calls - initial
    if calls != math.ceil(len(future)/declaration["profile"].batch_size):
        raise ContractError("incomplete physical future forwards")
    training_cost = train_receipt["observed_resources"]
    if any(type(training_cost.get(k)) is not int or training_cost[k] <= 0
           for k in ("wall_ns", "cpu_ns", "resident_bytes")):
        raise ContractError("missing real training resource observation")
    execution = {"physical_forwards": calls + train_receipt["model_forwards"],
                 "checkpoint_locally_verified": True, "publisher_authenticated": False,
                 "resident_bytes": max(training_cost["resident_bytes"], resource["resident_bytes"]),
                 "wall_ns": training_cost["wall_ns"] + resource["wall_ns"],
                 "cpu_ns": training_cost["cpu_ns"] + resource["cpu_ns"],
                 "energy_joules": None}
    source_fields = ("case_id", "group_id", "scope", "observed_at", "input_sha256")
    result = {"schema": RESULT, "candidate": name, "plan_sha256": plan_sha,
              "profile_sha256": profile_sha, "snapshot_sha256": declaration["profile"].snapshot_digest,
              "train_sha256": plan["train_sha256"],
              "future_source_sha256": plan["future_source_sha256"],
              "hardware_sha256": plan["hardware_sha256"],
              "environment_sha256": plan["environment_sha256"],
              "train_steps": plan["train_steps"], "head_parameters": plan["head_parameters"],
              "seed": plan["seed"], "execution": execution,
              "predictions": [{**{k: row[k] for k in source_fields}, "probabilities": pr}
                              for row, pr in zip(future, probs)]}
    evidence = {"schema": EVIDENCE, "candidate_result_sha256": sha(canonical(result)),
                "training_receipt_sha256": train_receipt_sha,
                "future_source_sha256": plan["future_source_sha256"],
                "future_examples": len(future), "predict_model_forwards": calls,
                "predict_resources": resource, "independent_attestation": False,
                "publisher_authenticated": False, "independent_ndu_verified": False,
                "production_accepted": False}
    return result, evidence


def _offline_model(path: Path, profile) -> object:
    from execution import LocalEncoder
    backend = LocalEncoder(path, profile.snapshot, profile.maximum_tokens)
    if type(backend) is not LocalEncoder or backend.simulated is not False:
        raise ContractError("only the exact local physical model owner is admitted")
    return backend


def _read_common(args) -> tuple[dict, str, dict, object, dict]:
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    plan = load_pinned_document(args.plan, args.plan_sha256)
    raw_profile = load_pinned_document(args.profile, args.profile_sha256)
    candidate = _candidate(plan, args.candidate, raw_profile, args.profile_sha256)
    host = host_identity()
    _host_check(plan, host)
    return plan, args.plan_sha256, raw_profile, candidate["profile"], host


def _v6_material_gate(args, plan: dict, plan_sha: str, profile: dict) -> dict | None:
    """Force independent operator material admission for every non-fixture CLI arm.

    Research-only helper: no publisher or production authorization is implied.
    """
    trust_args = (args.operator_trust, args.operator_trust_sha256,
                  args.signed_claim, args.signed_claim_sha256)
    if args.candidate == "tiny_random":
        if any(x is not None for x in trust_args):
            raise ContractError("random-fixture profile may not claim operator-reviewed material")
        return None
    if any(x is None for x in trust_args):
        raise ContractError("non-fixture model requires independent V6 operator material admission")
    # Granite R2 documents CLS pooling followed by unit-L2 normalization.
    # A mean-pooled arm is an ablation and must not use the official arm name.
    if args.candidate == "granite_97m" and (
            profile["pooling"] != "cls-first-token"
            or profile["normalization"] != "unit_l2"):
        raise ContractError("granite_97m requires publisher-documented CLS pooling and unit L2")
    from multimodal_material_admission import admission
    trust = load_pinned_document(args.operator_trust, args.operator_trust_sha256)
    claim = load_pinned_document(args.signed_claim, args.signed_claim_sha256)
    return admission(plan, plan_sha, profile, args.profile_sha256,
                     args.model_snapshot, trust, args.operator_trust_sha256,
                     claim, args.signed_claim_sha256, now_seconds=int(time.time()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only frozen real Encoder / Cell Head producer")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("host", help="Print precommittable software and machine-class fingerprints")
    for name in ("train", "predict"):
        p = sub.add_parser(name)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--plan-sha256", required=True)
        p.add_argument("--candidate", required=True)
        p.add_argument("--profile", type=Path, required=True)
        p.add_argument("--profile-sha256", required=True)
        p.add_argument("--model-snapshot", type=Path, required=True)
        # Non-fixture model execution requires an operator-reviewed, separately
        # pinned key and a real file-inventory check before either phase.
        p.add_argument("--operator-trust", type=Path)
        p.add_argument("--operator-trust-sha256")
        p.add_argument("--signed-claim", type=Path)
        p.add_argument("--signed-claim-sha256")
        if name == "train":
            p.add_argument("--train", type=Path, required=True)
            p.add_argument("--train-sha256", required=True)
            p.add_argument("--output-dir", type=Path, required=True)
        else:
            p.add_argument("--train-receipt", type=Path, required=True)
            p.add_argument("--train-receipt-sha256", required=True)
            p.add_argument("--head", type=Path, required=True)
            p.add_argument("--future-inputs", type=Path, required=True)
            p.add_argument("--future-inputs-sha256", required=True)
            p.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "host":
        import sys
        torch.set_num_threads(1)
        sys.stdout.buffer.write(canonical(host_identity()))
        return
    plan, plan_sha, profile, parsed, host = _read_common(args)
    material_receipt = _v6_material_gate(args, plan, plan_sha, profile)
    if args.operation == "train":
        rows, _ = load_pinned_jsonl(args.train, args.train_sha256)
        if args.train_sha256 != plan["train_sha256"]:
            raise ContractError("unexpected training data")
        _validate_examples(plan, rows, "train")
        if args.output_dir.exists():
            raise ContractError("output directory already exists")
        backend = _offline_model(args.model_snapshot, parsed)
        head_raw, receipt = train(plan, plan_sha, profile, args.profile_sha256, args.candidate,
                                  rows, args.train_sha256, backend, host)
        if material_receipt is not None:
            receipt["operator_material_assertion_sha256"] = args.signed_claim_sha256
        files = {"head.safetensors": head_raw, "train_receipt.json": canonical(receipt)}
        if material_receipt is not None:
            files["operator_material_admission.json"] = canonical(material_receipt)
        _save_dir(args.output_dir, files)
    else:
        receipt = load_pinned_document(args.train_receipt, args.train_receipt_sha256)
        if material_receipt is not None and (receipt.get("operator_material_assertion_sha256")
                                            != args.signed_claim_sha256):
            raise ContractError("training receipt not linked to V6 operator assertion")
        head_path = args.head
        if head_path.is_symlink() or not head_path.is_file() or head_path.stat().st_size > MAX_HEAD_BYTES:
            raise ContractError("invalid Head artifact file")
        raw = head_path.read_bytes()
        if sha(raw) != receipt.get("head_sha256"):
            raise ContractError("Head bytes differ from pinned training receipt")
        rows, _ = load_pinned_jsonl(args.future_inputs, args.future_inputs_sha256)
        _validate_examples(plan, rows, "future", set(receipt.get("training_text_sha256s", [])))
        if args.output_dir.exists():
            raise ContractError("output directory already exists")
        backend = _offline_model(args.model_snapshot, parsed)
        result, evidence = predict(plan, plan_sha, profile, args.profile_sha256, args.candidate,
                                   receipt, args.train_receipt_sha256, raw, rows, backend, host)
        files = {"candidate_result.json": canonical(result),
                 "predict_evidence.json": canonical(evidence)}
        if material_receipt is not None:
            evidence["operator_material_assertion_sha256"] = args.signed_claim_sha256
            files["predict_evidence.json"] = canonical(evidence)
            files["operator_material_admission.json"] = canonical(material_receipt)
        _save_dir(args.output_dir, files)


if __name__ == "__main__":
    main()
