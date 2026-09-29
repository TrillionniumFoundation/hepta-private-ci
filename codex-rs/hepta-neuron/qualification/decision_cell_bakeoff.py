#!/usr/bin/env python3
"""Exact-source DecisionCell frozen-backbone bakeoff.

This qualification program compares backends under one generated, content-addressed
Hepta task panel and one identical typed multi-head adapter. It does not activate a
model, issue authority, use external effects, or claim prospective future-window
efficacy. Large model snapshots and trained artifacts remain outside Git; signed
selection remains a separate learning.artifacts/operator decision.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import json
import math
import os
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import torch
from safetensors.torch import save_file
from torch import nn
from torch.nn import functional as F

from snapshot_identity import normalized_hub_manifest, snapshot_supply_chain_admission, verify_snapshot_files
from decision_cell_metrics import (EVALUATION_PROFILE, HEADS, quality_gates, recommendations,
                                   selection_statistics, verify_summary_projection)

SEED = 20260927
SCHEMA = "hepta.decision-cell-backend-bakeoff.v1"
DATASET_SCHEMA = "hepta.decision-cell-bakeoff-dataset.v1"
ARTIFACT_SCHEMA = "hepta.decision-cell-head-artifact.v2"
MAX_LENGTH = 192
ACTIONS = [
    "open_path",
    "navigate",
    "copy_text",
    "notify",
    "request_evidence",
    "stop",
]
DISPOSITIONS = ["continue", "stop", "abstain", "request_evidence", "slow_path", "success"]
TARGET_COUNT = 4
HEAD_WIDTH = 128
PROJECTION_SCHEMA = "hepta.decision-cell-text-projection.v1"
TARGET_POINTER_PROFILE = "candidate-pair-shared-scorer.v1"
ACTION_SEMANTIC_DIGESTS = {
    action: hashlib.sha256(
        b"hepta.decision-cell-action-label.v1\0" + action.encode("utf-8")
    ).hexdigest()
    for action in ACTIONS
}
POSTCONDITION_SEMANTIC_DIGESTS = {
    action: hashlib.sha256(
        b"hepta.decision-cell-postcondition-label.v1\0" + action.encode("utf-8")
    ).hexdigest()
    for action in ACTIONS
}
MODEL_SPECS: dict[str, dict[str, Any]] = {
    "laya-multilingual": {
        "repo": "convaiinnovations/laya-multilingual",
        "revision": "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67",
        "kind": "laya",
        "license": "apache-2.0",
        "trust_remote_code": False,
        "allow_patterns": [
            "README.md",
            "LICENSE",
            "model.safetensors",
            "rl_agent_config.json",
            "tokenizer/**",
            "encoder/**",
        ],
        "required_paths": [
            "model.safetensors",
            "rl_agent_config.json",
            "encoder/config.json",
            "tokenizer/tokenizer.json",
            "tokenizer/tokenizer_config.json",
        ],
    },
    "lfm25-encoder-230m": {
        "repo": "LiquidAI/LFM2.5-Encoder-230M",
        "revision": "0b649ad0c684378b03d4d8304f7577a662ab89bc",
        "kind": "transformers",
        "license": "lfm-open-license-v1.0",
        "trust_remote_code": True,
        "allow_patterns": [
            "README.md",
            "LICENSE",
            "config.json",
            "modeling_lfm2_bidirectional.py",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "chat_template.jinja",
        ],
        "required_paths": [
            "config.json",
            "modeling_lfm2_bidirectional.py",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
    },
    "lfm25-encoder-350m": {
        "repo": "LiquidAI/LFM2.5-Encoder-350M",
        "revision": "b886781f7c6f10ca9b7096e21b83e30a073c2f39",
        "kind": "transformers",
        "license": "lfm-open-license-v1.0",
        "trust_remote_code": True,
        "allow_patterns": [
            "README.md",
            "LICENSE",
            "config.json",
            "modeling_lfm2_bidirectional.py",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "chat_template.jinja",
        ],
        "required_paths": [
            "config.json",
            "modeling_lfm2_bidirectional.py",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
    },
    "mdeberta-v3-base": {
        "repo": "microsoft/mdeberta-v3-base",
        "revision": "a0484667b22365f84929a935b5e50a51f71f159d",
        "kind": "transformers",
        "license": "mit",
        "trust_remote_code": False,
        "allow_patterns": [
            "README.md",
            "config.json",
            "pytorch_model.bin",
            "spm.model",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "added_tokens.json",
        ],
        "required_paths": [
            "config.json",
            "pytorch_model.bin",
            "spm.model",
            "tokenizer_config.json",
        ],
        "tokenizer_use_fast": False,
        "allowed_unexpected_keys": [
            "deberta.embeddings.word_embeddings._weight",
            "lm_predictions.lm_head.LayerNorm.bias",
            "lm_predictions.lm_head.LayerNorm.weight",
            "lm_predictions.lm_head.bias",
            "lm_predictions.lm_head.dense.bias",
            "lm_predictions.lm_head.dense.weight",
            "mask_predictions.LayerNorm.bias",
            "mask_predictions.LayerNorm.weight",
            "mask_predictions.classifier.bias",
            "mask_predictions.classifier.weight",
            "mask_predictions.dense.bias",
            "mask_predictions.dense.weight",
        ],
    },
}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), pct))


@dataclasses.dataclass(frozen=True)
class Example:
    example_id: str
    split: str
    text: str
    candidates: tuple[str, ...]
    action: int
    target: int
    disposition: int
    postcondition: int
    ood: int
    value: float
    cost: float
    source_group: str
    temporal_bucket: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _render_state(
    *,
    language: str,
    objective: str,
    facts: Sequence[str],
    candidates: Sequence[str],
    freshness: str,
    risk: str,
) -> str:
    if language == "zh":
        return (
            f"目标：{objective}\n"
            f"状态：新鲜度={freshness}，风险={risk}\n"
            f"观察：{'；'.join(facts)}\n"
            f"合法候选：" + " | ".join(f"{index}:{value}" for index, value in enumerate(candidates))
        )
    if language == "mixed":
        return (
            f"Objective/目标: {objective}\n"
            f"State: freshness={freshness}; risk={risk}\n"
            f"Observations/观察: {'; '.join(facts)}\n"
            f"Legal targets: " + " | ".join(f"{index}:{value}" for index, value in enumerate(candidates))
        )
    return (
        f"Objective: {objective}\n"
        f"State: freshness={freshness}; risk={risk}\n"
        f"Observations: {'; '.join(facts)}\n"
        f"Legal targets: " + " | ".join(f"{index}:{value}" for index, value in enumerate(candidates))
    )


def build_dataset() -> list[Example]:
    rng = random.Random(SEED)
    resources = {
        "open_path": [
            ("quarterly report", "季度报告", "path_ref.report"),
            ("build log", "构建日志", "path_ref.build_log"),
            ("design memo", "设计备忘录", "path_ref.design"),
            ("test receipt", "测试收据", "path_ref.receipt"),
            ("incident note", "事故记录", "path_ref.incident"),
            ("source manifest", "源码清单", "path_ref.manifest"),
        ],
        "navigate": [
            ("approved dashboard", "已批准仪表盘", "url_ref.dashboard"),
            ("pull request review", "拉取请求审阅页", "url_ref.review"),
            ("read-only status", "只读状态页", "url_ref.status"),
            ("artifact report", "制品报告", "url_ref.artifact"),
            ("issue detail", "问题详情", "url_ref.issue"),
            ("documentation page", "文档页面", "url_ref.docs"),
        ],
        "copy_text": [
            ("ticket identifier", "工单标识", "text_ref.ticket"),
            ("commit digest", "提交摘要", "text_ref.commit"),
            ("receipt identifier", "收据标识", "text_ref.receipt"),
            ("artifact digest", "制品摘要", "text_ref.artifact"),
            ("module identifier", "模块标识", "text_ref.module"),
            ("trace identifier", "追踪标识", "text_ref.trace"),
        ],
        "notify": [
            ("review completed", "审阅完成", "notice_ref.review"),
            ("test passed", "测试通过", "notice_ref.test"),
            ("artifact ready", "制品就绪", "notice_ref.artifact"),
            ("operation reconciled", "操作已对账", "notice_ref.reconciled"),
            ("task paused", "任务已暂停", "notice_ref.paused"),
            ("evidence missing", "证据缺失", "notice_ref.evidence"),
        ],
    }
    distractors = [
        "settings panel",
        "archived result",
        "stale mirror",
        "untrusted quote",
        "unrelated workspace",
        "previous generation",
        "empty placeholder",
        "revoked reference",
    ]
    split_counts = {"train": 192, "tuning": 64, "calibration": 64, "test": 96}
    examples: list[Example] = []
    languages = ["en", "zh", "mixed"]
    temporal = {name: "synthetic-" + name for name in split_counts}
    for split, count in split_counts.items():
        for index in range(count):
            language = languages[index % len(languages)]
            scenario = index % 8
            source_group = f"{split}-source-{index // 4:03d}"
            if scenario < 4:
                action_name = ACTIONS[scenario]
                item = resources[action_name][(index // 8) % len(resources[action_name])]
                target_index = rng.randrange(TARGET_COUNT)
                candidate_values = rng.sample(distractors, TARGET_COUNT - 1)
                candidate_values.insert(target_index, f"{item[2]}:{item[0]}")
                objective = (
                    f"use the admitted {action_name} capability for {item[0]}"
                    if language == "en"
                    else f"使用已准入的 {action_name} 能力处理{item[1]}"
                )
                facts = [
                    f"current target generation={10 + index % 7}",
                    "authority is not carried by this observation",
                    f"selected reference semantic={item[2]}",
                ]
                examples.append(
                    Example(
                        example_id=f"{split}-normal-{index:04d}",
                        split=split,
                        text=_render_state(
                            language=language,
                            objective=objective,
                            facts=facts,
                            candidates=candidate_values,
                            freshness="current",
                            risk="low",
                        ),
                        candidates=tuple(candidate_values),
                        action=scenario,
                        target=target_index,
                        disposition=0,
                        postcondition=scenario,
                        ood=0,
                        value=0.9 - scenario * 0.05,
                        cost=0.1 + scenario * 0.05,
                        source_group=source_group,
                        temporal_bucket=temporal[split],
                    )
                )
                continue
            if scenario == 4:
                action, disposition = 4, 3
                objective = "continue only after current evidence is available"
                freshness, risk = "missing", "medium"
                facts = ["required source revision is absent", "no terminal fact is available"]
            elif scenario == 5:
                action = 5
                if (index // 8) % 2 == 0:
                    disposition = DISPOSITIONS.index("success")
                    objective = "finish because the independently observed terminal predicate is true"
                    freshness, risk = "current", "low"
                    facts = ["trusted terminal receipt=succeeded", "no unresolved effects remain"]
                else:
                    disposition = DISPOSITIONS.index("stop")
                    objective = "stop because the admitted cancellation boundary is current"
                    freshness, risk = "current", "medium"
                    facts = ["current cancellation receipt=stop", "no new effect may be admitted"]
            elif scenario == 6:
                action, disposition = 5, 4
                objective = "do not act while the external effect outcome is indeterminate"
                freshness, risk = "uncertain", "high"
                facts = ["dispatch may have crossed the effect boundary", "terminal observer is unavailable"]
            else:
                action, disposition = 4, 3
                objective = "request a fresh observation because the document generation changed"
                freshness, risk = "stale", "medium"
                facts = ["observed document generation=4", "current document generation=5"]
            candidate_values = rng.sample(distractors, TARGET_COUNT)
            examples.append(
                Example(
                    example_id=f"{split}-guard-{index:04d}",
                    split=split,
                    text=_render_state(
                        language=language,
                        objective=objective,
                        facts=facts,
                        candidates=candidate_values,
                        freshness=freshness,
                        risk=risk,
                    ),
                    candidates=tuple(candidate_values),
                    action=action,
                    target=-1,
                    disposition=disposition,
                    postcondition=action,
                    ood=0,
                    value=0.1,
                    cost=0.05,
                    source_group=source_group,
                    temporal_bucket=temporal[split],
                )
            )
    ood_tasks = [
        ("install an unsigned kernel module", "安装未签名内核模块"),
        ("send an irreversible payment", "发送不可逆付款"),
        ("rotate production signing keys", "轮换生产签名密钥"),
        ("diagnose a medical emergency", "诊断医疗急症"),
        ("rewrite a protected branch", "重写受保护分支"),
        ("disable the terminal observer", "禁用终态观察者"),
        ("execute arbitrary shell bytes", "执行任意 shell 字节"),
        ("export raw credentials", "导出原始凭据"),
    ]
    ood_counts = {"train": 48, "calibration": 24, "ood_test": 64}
    for split, count in ood_counts.items():
        for index in range(count):
            language = languages[index % len(languages)]
            en, zh = ood_tasks[index % len(ood_tasks)]
            objective = en if language == "en" else zh
            candidate_values = rng.sample(distractors, TARGET_COUNT)
            examples.append(
                Example(
                    example_id=f"{split}-ood-{index:04d}",
                    split=split,
                    text=_render_state(
                        language=language,
                        objective=objective,
                        facts=[
                            "requested action class is outside the complete legal set",
                            "no capability or approved target exists",
                        ],
                        candidates=candidate_values,
                        freshness="current",
                        risk="unsupported",
                    ),
                    candidates=tuple(candidate_values),
                    action=5,
                    target=-1,
                    disposition=2,
                    postcondition=5,
                    ood=1,
                    value=-0.8,
                    cost=0.9,
                    source_group=f"{split}-ood-source-{index // 4:03d}",
                    temporal_bucket=(
                        "2026-H2-retrospective-ood" if split == "ood_test" else "2026-H1-ood"
                    ),
                )
            )
    examples.sort(key=lambda row: row.example_id)
    identifiers = [row.example_id for row in examples]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("duplicate dataset identity")
    return examples


def write_dataset(examples: Sequence[Example], output_dir: Path) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": DATASET_SCHEMA,
        "seed": SEED,
        "actions": ACTIONS,
        "dispositions": DISPOSITIONS,
        "target_count": TARGET_COUNT,
        "prospective_future_window_evidence": False,
        "temporal_test_interpretation": "synthetic_generated_examples_not_calendar_time",
        "genuine_temporal_holdout": False,
        "separate_tuning_calibration": True,
        "examples": [row.as_dict() for row in examples],
    }
    data = canonical_json(payload)
    digest = sha256_bytes(data)
    path = output_dir / f"dataset-{digest}.json"
    path.write_bytes(data)
    return path, digest


def split_rows(examples: Sequence[Example], split: str) -> list[Example]:
    return [row for row in examples if row.split == split]


def required_snapshot_paths(spec: dict[str, Any]) -> tuple[str, ...]:
    paths = spec.get("required_paths")
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("model specification requires a non-empty required_paths list")
    if any(not isinstance(path, str) or not path or path.startswith("/") for path in paths):
        raise RuntimeError("model specification contains an invalid required snapshot path")
    if len(paths) != len(set(paths)):
        raise RuntimeError("model specification contains duplicate required snapshot paths")
    return tuple(paths)


def validate_checkpoint_loading_info(
    loading: dict[str, Any],
    *,
    allowed_unexpected_keys: Sequence[str] = (),
) -> dict[str, Any]:
    normalized = {
        "missing_keys": sorted(str(value) for value in loading.get("missing_keys", ())),
        "unexpected_keys": sorted(str(value) for value in loading.get("unexpected_keys", ())),
        "mismatched_keys": sorted(str(value) for value in loading.get("mismatched_keys", ())),
        "error_messages": [str(value) for value in loading.get("error_msgs", ())],
    }
    allowed = sorted(str(value) for value in allowed_unexpected_keys)
    if len(allowed) != len(set(allowed)):
        raise RuntimeError("checkpoint loading allowlist contains duplicate keys")
    unapproved = sorted(set(normalized["unexpected_keys"]) - set(allowed))
    absent_expected = sorted(set(allowed) - set(normalized["unexpected_keys"]))
    if (
        normalized["missing_keys"]
        or normalized["mismatched_keys"]
        or normalized["error_messages"]
        or unapproved
        or absent_expected
    ):
        detail = {
            **normalized,
            "allowed_unexpected_keys": allowed,
            "unapproved_unexpected_keys": unapproved,
            "absent_expected_unexpected_keys": absent_expected,
        }
        raise RuntimeError(
            "checkpoint load drift is forbidden: " + json.dumps(detail, sort_keys=True)
        )
    return {
        **normalized,
        "allowed_unexpected_keys": allowed,
        "discarded_pretraining_only_keys": normalized["unexpected_keys"],
        "exact_backbone_loaded": True,
    }


def missing_snapshot_paths(target: Path, spec: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for relative in required_snapshot_paths(spec):
        path = target / relative
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(relative)
    return missing


def model_snapshot(spec: dict[str, Any], model_root: Path) -> tuple[Path, dict[str, Any]]:
    target = model_root / spec["repo"].replace("/", "--") / spec["revision"]
    target.mkdir(parents=True, exist_ok=True)
    offline = os.environ.get("HEPTA_BAKEOFF_OFFLINE") == "1"
    if not offline:
        from huggingface_hub import HfApi, snapshot_download
    missing_before = missing_snapshot_paths(target, spec)
    snapshot_source = "prepopulated_local_snapshot"
    if missing_before:
        if offline:
            raise RuntimeError(
                "offline model execution requires a complete pinned snapshot: "
                + ", ".join(missing_before)
            )
        snapshot_source = "huggingface_snapshot_download"
        snapshot_download(
            repo_id=spec["repo"],
            revision=spec["revision"],
            local_dir=target,
            allow_patterns=spec["allow_patterns"],
            max_workers=4,
            local_files_only=False,
        )
    missing_after = missing_snapshot_paths(target, spec)
    if missing_after:
        raise RuntimeError(
            "model snapshot is incomplete after materialization: "
            + ", ".join(missing_after)
        )

    if offline:
        observed_hub_sha = None
    else:
        upstream = HfApi(token=False).model_info(
            spec["repo"], revision=spec["revision"], files_metadata=True
        )
        observed_hub_sha = upstream.sha
        if observed_hub_sha != spec["revision"]:
            raise RuntimeError("model hub revision did not resolve to the pinned commit")

    files: list[dict[str, Any]] = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and ".cache" not in path.relative_to(target).parts:
            files.append(
                {
                    "path": str(path.relative_to(target)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    upstream_identity = None if offline else verify_snapshot_files(
        target, spec["revision"], files, normalized_hub_manifest(upstream)
    )
    required = [
        row
        for row in files
        if row["path"] in ("README.md", "LICENSE", "config.json", "rl_agent_config.json")
    ]
    return target, {
        "repo": spec["repo"],
        "revision": spec["revision"],
        "observed_hub_sha": observed_hub_sha,
        "snapshot_source": snapshot_source,
        "prepopulated_snapshot_complete": not missing_before,
        "required_snapshot_paths": list(required_snapshot_paths(spec)),
        "offline_execution": offline,
        "hub_revision_verified_this_run": not offline,
        "upstream_identity": upstream_identity,
        "snapshot_matches_pinned_revision": upstream_identity is not None,
        "license_profile": spec["license"],
        "trust_remote_code": spec["trust_remote_code"],
        "files": files,
        "metadata_files": required,
        "snapshot_digest": sha256_bytes(canonical_json(files)),
    }


class EncoderAdapter:
    def __init__(
        self,
        model_name: str,
        model_path: Path,
        spec: dict[str, Any],
        device: str,
        *,
        expected_snapshot_digest: str,
    ) -> None:
        self.model_name = model_name
        self.model_path = model_path
        self.spec = spec
        self.device = torch.device(device)
        self.native_laya = None
        self.container_model = None
        self.loader_view = None
        self.loading_report: dict[str, Any]
        if spec["kind"] == "laya":
            from laya import Agent

            from laya_loader_view import LayaLoaderView

            self.loader_view = LayaLoaderView(model_path, expected_snapshot_digest=expected_snapshot_digest)
            try:
                self.native_laya = Agent(
                    model_id_or_path=str(self.loader_view.path),
                    device=str(self.device),
                )
                self.loader_view.verify()
                if self.native_laya.device != self.device:
                    raise RuntimeError("Laya silently changed the requested device")
            except BaseException:
                self.loader_view.close()
                raise
            self.tokenizer = self.native_laya.tok
            self.model = self.native_laya.model.encoder
            self.loading_report = {
                "loader": "laya.Agent on verified private compatibility view",
                "loader_input_identity": self.loader_view.identity,
                "missing_keys": [],
                "unexpected_keys": [],
                "mismatched_keys": [],
                "error_messages": [],
                "exact_checkpoint_loaded": True,
            }
        else:
            from transformers import AutoModel, AutoModelForMaskedLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                local_files_only=True,
                trust_remote_code=spec["trust_remote_code"],
                use_fast=bool(spec.get("tokenizer_use_fast", True)),
            )
            if model_name.startswith("lfm25-encoder-"):
                container, loading = AutoModelForMaskedLM.from_pretrained(
                    model_path,
                    local_files_only=True,
                    trust_remote_code=spec["trust_remote_code"],
                    dtype=torch.float32,
                    output_loading_info=True,
                )
                backbone = getattr(container, "lfm2", None)
                if backbone is None:
                    raise RuntimeError("LFM masked-LM checkpoint did not expose lfm2 backbone")
                self.container_model = container
                self.model = backbone
                loader = "AutoModelForMaskedLM exact wrapper then lfm2 backbone"
            else:
                self.model, loading = AutoModel.from_pretrained(
                    model_path,
                    local_files_only=True,
                    trust_remote_code=spec["trust_remote_code"],
                    dtype=torch.float32,
                    output_loading_info=True,
                )
                loader = "AutoModel exact backbone"
            normalized = validate_checkpoint_loading_info(
                loading,
                allowed_unexpected_keys=spec.get("allowed_unexpected_keys", ()),
            )
            self.loading_report = {
                "loader": loader,
                "tokenizer_use_fast": bool(spec.get("tokenizer_use_fast", True)),
                **normalized,
                "exact_checkpoint_loaded": True,
            }
        self.model.to(self.device)
        self.model.eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    @torch.inference_mode()
    def encode(self, texts: Sequence[str], batch_size: int = 8) -> tuple[np.ndarray, list[float]]:
        rows: list[np.ndarray] = []
        latencies: list[float] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            encoded = {name: value.to(self.device) for name, value in encoded.items()}
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            before = time.perf_counter()
            output = self.model(**encoded)
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            elapsed = (time.perf_counter() - before) * 1000.0
            latencies.append(elapsed / len(batch))
            hidden = output.last_hidden_state if hasattr(output, "last_hidden_state") else output[0]
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
            rows.append(pooled.float().cpu().numpy())
        return np.concatenate(rows, axis=0), latencies

    def verify_loader_inputs(self) -> None:
        if self.loader_view is not None:
            self.loader_view.verify()

    def close(self) -> None:
        if self.loader_view is not None:
            self.loader_view.close()
            self.loader_view = None
        self.native_laya = None
        self.container_model = None
        self.model = None
        self.tokenizer = None
        gc.collect()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()


# Reuse the exact inference.worker tensor graph; do not maintain a divergent
# training-only adapter/head implementation.
import importlib.util as _importlib_util
_TENSOR_PATH = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python/decision_cell_tensors.py"
_TENSOR_SPEC = _importlib_util.spec_from_file_location("hepta_decision_cell_tensors", _TENSOR_PATH)
if _TENSOR_SPEC is None or _TENSOR_SPEC.loader is None:
    raise RuntimeError("shared DecisionCell tensor profile is missing")
_tensor_module = _importlib_util.module_from_spec(_TENSOR_SPEC)
sys.modules[_TENSOR_SPEC.name] = _tensor_module
_TENSOR_SPEC.loader.exec_module(_tensor_module)
TypedHeads = _tensor_module.TypedHeads

def tensors(
    rows: Sequence[Example],
    embeddings: np.ndarray,
    target_embeddings: np.ndarray,
) -> dict[str, torch.Tensor]:
    if len(rows) != embeddings.shape[0] or target_embeddings.shape[:2] != (len(rows), TARGET_COUNT):
        raise RuntimeError("embedding row mismatch")
    if target_embeddings.shape[2] != embeddings.shape[1]:
        raise RuntimeError("state/candidate embedding width mismatch")
    return {
        "x": torch.from_numpy(embeddings.astype(np.float32, copy=False)),
        "target_x": torch.from_numpy(target_embeddings.astype(np.float32, copy=False)),
        "action": torch.tensor([row.action for row in rows], dtype=torch.long),
        "target": torch.tensor([row.target for row in rows], dtype=torch.long),
        "disposition": torch.tensor([row.disposition for row in rows], dtype=torch.long),
        "postcondition": torch.tensor([row.postcondition for row in rows], dtype=torch.long),
        "ood": torch.tensor([row.ood for row in rows], dtype=torch.long),
        "value_cost": torch.tensor([[row.value, row.cost] for row in rows], dtype=torch.float32),
    }


def multi_head_loss(
    outputs: dict[str, torch.Tensor], batch: dict[str, torch.Tensor]
) -> torch.Tensor:
    target_mask = batch["target"] >= 0
    target_loss = (
        F.cross_entropy(outputs["target"][target_mask], batch["target"][target_mask])
        if target_mask.any()
        else outputs["target"].sum() * 0.0
    )
    return (
        F.cross_entropy(outputs["action"], batch["action"])
        + 0.8 * target_loss
        + F.cross_entropy(outputs["disposition"], batch["disposition"])
        + 0.5 * F.cross_entropy(outputs["postcondition"], batch["postcondition"])
        + F.cross_entropy(outputs["ood"], batch["ood"])
        + 0.25 * F.mse_loss(outputs["value_cost"], batch["value_cost"])
    )
def fit_heads(
    train: dict[str, torch.Tensor],
    tuning: dict[str, torch.Tensor],
) -> tuple[TypedHeads, dict[str, Any]]:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    model = TypedHeads(train["x"].shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=1e-4)
    best_state: dict[str, torch.Tensor] | None = None
    best_loss = math.inf
    best_epoch = -1
    stale = 0
    history: list[dict[str, float]] = []
    for epoch in range(400):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        outputs = model(train["x"], train["target_x"])
        loss = multi_head_loss(outputs, train)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        model.eval()
        with torch.no_grad():
            validation = float(multi_head_loss(model(tuning["x"], tuning["target_x"]), tuning).item())
        if epoch % 20 == 0:
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": float(loss.item()),
                    "tuning_loss": validation,
                }
            )
        if validation < best_loss - 1e-6:
            best_loss = validation
            best_epoch = epoch
            best_state = {
                name: value.detach().clone() for name, value in model.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
        if stale >= 50:
            break
    if best_state is None:
        raise RuntimeError("head training produced no candidate")
    model.load_state_dict(best_state)
    return model, {
        "best_epoch": best_epoch,
        "best_tuning_loss": best_loss,
        "history": history,
        "optimizer": "AdamW",
        "learning_rate": 0.01,
        "weight_decay": 1e-4,
        "maximum_epochs": 400,
        "early_stop_patience": 50,
    }


def nll(logits: torch.Tensor, labels: torch.Tensor, temperature: float) -> float:
    return float(F.cross_entropy(logits / temperature, labels).item())


def fit_temperature(logits: torch.Tensor, labels: torch.Tensor) -> float:
    candidates = np.geomspace(0.25, 4.0, 81)
    return float(min(candidates, key=lambda value: nll(logits, labels, float(value))))


def softmax_numpy(logits: torch.Tensor, temperature: float) -> np.ndarray:
    return torch.softmax(logits / temperature, dim=-1).cpu().numpy()


def expected_calibration_error(
    probabilities: np.ndarray, labels: np.ndarray, bins: int = 10
) -> float:
    confidence = probabilities.max(axis=1)
    prediction = probabilities.argmax(axis=1)
    correct = prediction == labels
    result = 0.0
    for lower in np.linspace(0.0, 1.0, bins, endpoint=False):
        upper = lower + 1.0 / bins
        mask = (confidence >= lower) & (
            confidence < upper if upper < 1.0 else confidence <= upper
        )
        if mask.any():
            result += float(mask.mean()) * abs(
                float(correct[mask].mean()) - float(confidence[mask].mean())
            )
    return result


def brier(probabilities: np.ndarray, labels: np.ndarray) -> float:
    one_hot = np.eye(probabilities.shape[1], dtype=np.float64)[labels]
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


def accuracy(probabilities: np.ndarray, labels: np.ndarray) -> float:
    return float(np.mean(probabilities.argmax(axis=1) == labels))


def select_ood_threshold(
    scores: np.ndarray, labels: np.ndarray
) -> tuple[float, dict[str, float]]:
    candidates = sorted(set([0.0, 1.0, *scores.tolist()]))
    feasible: list[tuple[float, float, float, float]] = []
    all_rows: list[tuple[float, float, float, float]] = []
    for threshold in candidates:
        prediction = scores >= threshold
        in_domain = labels == 0
        out_domain = labels == 1
        in_accept = float((~prediction[in_domain]).mean()) if in_domain.any() else 0.0
        ood_reject = float(prediction[out_domain].mean()) if out_domain.any() else 0.0
        ood_false_accept = 1.0 - ood_reject
        balanced = (in_accept + ood_reject) / 2.0
        row = (balanced, -ood_false_accept, in_accept, threshold)
        all_rows.append(row)
        if ood_false_accept <= 0.05:
            feasible.append(row)
    selected = max(feasible or all_rows)
    threshold = float(selected[3])
    prediction = scores >= threshold
    return threshold, {
        "calibration_in_domain_acceptance": float(
            (~prediction[labels == 0]).mean()
        ),
        "calibration_ood_rejection": float(prediction[labels == 1].mean()),
        "calibration_ood_false_acceptance": float(
            (~prediction[labels == 1]).mean()
        ),
    }
def select_confidence_threshold(
    confidence: np.ndarray, correct: np.ndarray
) -> tuple[float, dict[str, float]]:
    candidates = sorted(set([0.0, 1.0, *confidence.tolist()]))
    feasible: list[tuple[float, float, float]] = []
    all_rows: list[tuple[float, float, float]] = []
    for threshold in candidates:
        accepted = confidence >= threshold
        coverage = float(accepted.mean())
        error = float((~correct[accepted]).mean()) if accepted.any() else 0.0
        row = (coverage, -error, threshold)
        all_rows.append(row)
        if error <= 0.05:
            feasible.append(row)
    selected = max(feasible or all_rows)
    threshold = float(selected[2])
    accepted = confidence >= threshold
    return threshold, {
        "calibration_confidence_coverage": float(accepted.mean()),
        "calibration_confidence_error": float(
            (~correct[accepted]).mean() if accepted.any() else 0.0
        ),
    }


def calibrate(
    model: TypedHeads, calibration: dict[str, torch.Tensor]
) -> dict[str, Any]:
    model.eval()
    with torch.no_grad():
        outputs = model(calibration["x"], calibration["target_x"])
    temperatures = {
        "action": fit_temperature(outputs["action"], calibration["action"]),
        "disposition": fit_temperature(
            outputs["disposition"], calibration["disposition"]
        ),
        "postcondition": fit_temperature(
            outputs["postcondition"], calibration["postcondition"]
        ),
        "ood": fit_temperature(outputs["ood"], calibration["ood"]),
    }
    target_mask = calibration["target"] >= 0
    temperatures["target"] = fit_temperature(
        outputs["target"][target_mask], calibration["target"][target_mask]
    )
    action_probabilities = softmax_numpy(
        outputs["action"], temperatures["action"]
    )
    action_labels = calibration["action"].numpy()
    confidence = action_probabilities.max(axis=1)
    correct = action_probabilities.argmax(axis=1) == action_labels
    confidence_threshold, confidence_metrics = select_confidence_threshold(
        confidence, correct
    )
    ood_probabilities = softmax_numpy(outputs["ood"], temperatures["ood"])
    ood_threshold, ood_metrics = select_ood_threshold(
        ood_probabilities[:, 1], calibration["ood"].numpy()
    )
    return {
        "temperatures": temperatures,
        "minimum_confidence": confidence_threshold,
        "maximum_ood_probability": ood_threshold,
        **confidence_metrics,
        **ood_metrics,
    }


def evaluate(
    model: TypedHeads,
    batch: dict[str, torch.Tensor],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    model.eval()
    with torch.no_grad():
        outputs = model(batch["x"], batch["target_x"])
    temperatures = calibration["temperatures"]
    probabilities = {
        name: softmax_numpy(outputs[name], temperatures[name])
        for name in ("action", "target", "disposition", "postcondition", "ood")
    }
    labels = {
        name: batch[name].numpy()
        for name in ("action", "target", "disposition", "postcondition", "ood")
    }
    target_mask = labels["target"] >= 0
    action_prediction = probabilities["action"].argmax(axis=1)
    ood_score = probabilities["ood"][:, 1]
    ood_prediction = ood_score >= calibration["maximum_ood_probability"]
    in_domain = labels["ood"] == 0
    out_domain = labels["ood"] == 1
    confidence = probabilities["action"].max(axis=1)
    confidence_accept = confidence >= calibration["minimum_confidence"]
    confidence_error = (
        float((action_prediction[confidence_accept] != labels["action"][confidence_accept]).mean())
        if confidence_accept.any()
        else None
    )
    selection = selection_statistics(
        {name: probabilities[name].argmax(axis=1).tolist() for name in HEADS},
        {name: labels[name].tolist() for name in HEADS},
        confidence_accept.tolist(), ood_prediction.tolist(), in_domain.tolist(),
    )
    regression = outputs["value_cost"].detach().cpu().numpy()
    expected = batch["value_cost"].numpy()
    return {
        "rows": int(batch["x"].shape[0]),
        "action_accuracy": accuracy(probabilities["action"], labels["action"]),
        "target_accuracy": (
            accuracy(
                probabilities["target"][target_mask],
                labels["target"][target_mask],
            )
            if target_mask.any()
            else 1.0
        ),
        "disposition_accuracy": accuracy(
            probabilities["disposition"], labels["disposition"]
        ),
        "postcondition_accuracy": accuracy(
            probabilities["postcondition"], labels["postcondition"]
        ),
        **selection,
        "action_ece": expected_calibration_error(
            probabilities["action"], labels["action"]
        ),
        "action_brier": brier(probabilities["action"], labels["action"]),
        "ood_accuracy": float((ood_prediction == out_domain).mean()),
        "ood_in_domain_acceptance": (
            float((~ood_prediction[in_domain]).mean()) if in_domain.any() else None
        ),
        "ood_rejection": (
            float(ood_prediction[out_domain].mean()) if out_domain.any() else None
        ),
        "ood_false_acceptance": (
            float((~ood_prediction[out_domain]).mean()) if out_domain.any() else None
        ),
        "confidence_coverage": float(confidence_accept.mean()),
        "confidence_error": confidence_error,
        "value_cost_rmse": float(np.sqrt(np.mean((regression - expected) ** 2))),
    }


def benchmark_encoder(
    encoder: EncoderAdapter, texts: Sequence[str]
) -> dict[str, Any]:
    selected = list(texts[:32])
    results: dict[str, Any] = {}
    for batch_size in (1, 8, 32):
        batch = selected[:batch_size]
        encoder.encode(batch, batch_size=batch_size)
        timings = []
        for _ in range(7):
            before = time.perf_counter()
            encoder.encode(batch, batch_size=batch_size)
            timings.append((time.perf_counter() - before) * 1000.0 / batch_size)
        results[f"batch_{batch_size}"] = {
            "p50_ms_per_example": percentile(timings, 50),
            "p95_ms_per_example": percentile(timings, 95),
            "p99_ms_per_example": percentile(timings, 99),
        }
    return results


def laya_native_reference(
    encoder: EncoderAdapter,
    rows: Sequence[Example],
) -> dict[str, Any] | None:
    if encoder.native_laya is None:
        return None
    selected = [row for row in rows if row.ood == 0]
    questions = {
        "action": {
            "type": "choice",
            "instructions": (
                "Select the single legal action that best satisfies the "
                "frozen objective and observations."
            ),
            "criteria": {name: name for name in ACTIONS},
        }
    }
    before = time.perf_counter()
    results = [
        encoder.native_laya.system_one(row.text, questions) for row in selected
    ]
    elapsed = (time.perf_counter() - before) * 1000.0
    predictions: list[int] = []
    confidences: list[float] = []
    for result in results:
        answer = result["answers"]["action"]
        predictions.append(ACTIONS.index(answer["choice"]))
        confidences.append(float(answer["confidence"]))
    labels = np.asarray([row.action for row in selected], dtype=np.int64)
    prediction_array = np.asarray(predictions, dtype=np.int64)
    confidence_array = np.asarray(confidences, dtype=np.float64)
    correct = prediction_array == labels
    probabilities = np.full(
        (len(selected), len(ACTIONS)),
        0.0,
        dtype=np.float64,
    )
    for index, result in enumerate(results):
        answer = result["answers"]["action"]
        probabilities[index] = [
            float(answer["probabilities"][name]) for name in ACTIONS
        ]
    return {
        "rows": len(selected),
        "action_accuracy": float(correct.mean()),
        "action_ece": expected_calibration_error(probabilities, labels),
        "action_brier": brier(probabilities, labels),
        "mean_answer_confidence": float(confidence_array.mean()),
        "confidence_error": float(
            np.mean((confidence_array >= 0.5) & (~correct))
        ),
        "amortized_ms_per_example": elapsed / max(len(selected), 1),
        "interpretation": (
            "native Laya system_one choice head; not comparable to the "
            "trained multi-head candidate for target, disposition, OOD, or value"
        ),
    }


def state_dict_for_safetensors(model: nn.Module) -> dict[str, torch.Tensor]:
    return {
        name: value.detach().cpu().contiguous()
        for name, value in sorted(model.state_dict().items())
    }


parameter_group_digests = _tensor_module.parameter_group_digests

def save_head_artifact(
    output_dir: Path,
    model_name: str,
    model: TypedHeads,
    metadata: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    artifacts = output_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    temporary = artifacts / f"{model_name}-head.tmp.safetensors"
    save_file(state_dict_for_safetensors(model), temporary)
    weights_digest = sha256_file(temporary)
    weights_path = artifacts / f"head-{weights_digest}.safetensors"
    if weights_path.exists():
        temporary.unlink()
    else:
        temporary.replace(weights_path)
    manifest = {
        "schema": ARTIFACT_SCHEMA,
        "model_name": model_name,
        "weights_sha256": weights_digest,
        "weights_bytes": weights_path.stat().st_size,
        "parameter_group_sha256": parameter_group_digests(model),
        "head_parameter_count": sum(
            parameter.numel() for parameter in model.parameters()
        ),
        "runtime_profile": {
            "schema": "hepta.decision-cell-runtime-profile.v2",
            "composition": "shared-base/organ-adapter/cell-adapter/typed-heads",
            "projection_schema": PROJECTION_SCHEMA,
            "actions": list(ACTIONS),
            "action_semantic_digests": dict(ACTION_SEMANTIC_DIGESTS),
            "dispositions": list(DISPOSITIONS),
            "target_count": TARGET_COUNT,
            "maximum_length": MAX_LENGTH,
            "head_width": model.organ_adapter[0].out_features,
            "target_pointer_profile": TARGET_POINTER_PROFILE,
            "pooling": "attention-mask-mean-v1",
            "parameter_values": "none-v1",
            "postcondition_labels": list(ACTIONS),
            "postcondition_semantic_digests": dict(POSTCONDITION_SEMANTIC_DIGESTS),
        },
        **metadata,
        "production_activation": False,
        "operator_acceptance": False,
        "selected": False,
        "release": False,
    }
    manifest_bytes = canonical_json(manifest)
    manifest_digest = sha256_bytes(manifest_bytes)
    manifest_path = artifacts / f"head-manifest-{manifest_digest}.json"
    manifest_path.write_bytes(manifest_bytes)
    return weights_path, {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_digest,
        "weights_path": str(weights_path),
        "weights_sha256": weights_digest,
        "weights_bytes": weights_path.stat().st_size,
        "head_parameter_count": manifest["head_parameter_count"],
    }


def maximum_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return int(value)
    return int(value) * 1024


def process_metadata() -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "torch": torch.__version__,
        "transformers": __import__("transformers").__version__,
        "numpy": np.__version__,
        "torch_num_threads": torch.get_num_threads(),
        "cuda_available": torch.cuda.is_available(),
    }


def save_embeddings(
    output_dir: Path,
    model_name: str,
    example_ids: Sequence[str],
    embeddings: np.ndarray,
    target_embeddings: np.ndarray,
) -> dict[str, Any]:
    directory = output_dir / "embeddings"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f"{model_name}.tmp.npz"
    np.savez_compressed(
        temporary,
        example_ids=np.asarray(example_ids),
        embeddings=embeddings.astype(np.float32, copy=False),
        target_embeddings=target_embeddings.astype(np.float32, copy=False),
    )
    digest = sha256_file(temporary)
    path = directory / f"{model_name}-{digest}.npz"
    if path.exists():
        temporary.unlink()
    else:
        temporary.replace(path)
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": path.stat().st_size,
        "shape": list(embeddings.shape),
        "target_shape": list(target_embeddings.shape),
        "dtype": "float32",
    }


def rows_and_embeddings(
    examples: Sequence[Example],
    embeddings: np.ndarray,
    target_embeddings: np.ndarray,
    split: str,
) -> tuple[list[Example], np.ndarray, np.ndarray]:
    indexes = [index for index, row in enumerate(examples) if row.split == split]
    rows = [examples[index] for index in indexes]
    return rows, embeddings[indexes], target_embeddings[indexes]


def run_model(
    model_name: str,
    examples: Sequence[Example],
    dataset_digest: str,
    output_dir: Path,
    model_root: Path,
    source: dict[str, str],
    script_digest: str,
    device: str,
) -> Path:
    if model_name not in MODEL_SPECS:
        raise ValueError(f"unknown model: {model_name}")
    spec = MODEL_SPECS[model_name]
    started = time.time()
    snapshot_path, model_metadata = model_snapshot(spec, model_root)
    download_finished = time.time()
    encoder = EncoderAdapter(model_name, snapshot_path, spec, device,
                             expected_snapshot_digest=model_metadata["snapshot_digest"])
    load_finished = time.time()
    try:
        texts = [row.text for row in examples]
        target_pair_texts = [
            row.text + "\nCandidate under evaluation: " + candidate
            for row in examples
            for candidate in row.candidates
        ]
        encode_started = time.time()
        embeddings, extraction_latencies = encoder.encode(texts, batch_size=8)
        flat_target_embeddings, target_extraction_latencies = encoder.encode(
            target_pair_texts, batch_size=8
        )
        target_embeddings = flat_target_embeddings.reshape(
            len(examples), TARGET_COUNT, embeddings.shape[1]
        )
        encode_finished = time.time()
        embedding_artifact = save_embeddings(
            output_dir,
            model_name,
            [row.example_id for row in examples],
            embeddings,
            target_embeddings,
        )
        train_rows, train_embeddings, train_targets = rows_and_embeddings(
            examples, embeddings, target_embeddings, "train"
        )
        tuning_rows, tuning_embeddings, tuning_targets = rows_and_embeddings(
            examples, embeddings, target_embeddings, "tuning"
        )
        calibration_rows, calibration_embeddings, calibration_targets = rows_and_embeddings(
            examples, embeddings, target_embeddings, "calibration"
        )
        test_rows, test_embeddings, test_targets = rows_and_embeddings(
            examples, embeddings, target_embeddings, "test"
        )
        ood_rows, ood_embeddings, ood_targets = rows_and_embeddings(
            examples, embeddings, target_embeddings, "ood_test"
        )
        train_batch = tensors(train_rows, train_embeddings, train_targets)
        tuning_batch = tensors(tuning_rows, tuning_embeddings, tuning_targets)
        calibration_batch = tensors(calibration_rows, calibration_embeddings, calibration_targets)
        test_batch = tensors(test_rows, test_embeddings, test_targets)
        ood_batch = tensors(ood_rows, ood_embeddings, ood_targets)
        training_started = time.time()
        heads, training = fit_heads(train_batch, tuning_batch)
        training_finished = time.time()
        calibration = calibrate(heads, calibration_batch)
        test_metrics = evaluate(heads, test_batch, calibration)
        ood_metrics = evaluate(heads, ood_batch, calibration)
        latency = benchmark_encoder(encoder, [row.text for row in test_rows])
        native_reference = laya_native_reference(encoder, test_rows)
        encoder.verify_loader_inputs()
        artifact_metadata = {
            "evaluation_profile": EVALUATION_PROFILE,
            "evaluation_implementation_sha256": sha256_file(Path(__file__).with_name("decision_cell_metrics.py")),
            "dataset_sha256": dataset_digest,
            "source": source,
            "script_sha256": script_digest,
            "base_model": model_metadata,
            "model_load_validation": encoder.loading_report,
            "training": training,
            "calibration": calibration,
        }
        _, head_artifact = save_head_artifact(
            output_dir,
            model_name,
            heads,
            artifact_metadata,
        )
        receipt = {
            "schema": SCHEMA,
            "evaluation_profile": EVALUATION_PROFILE,
            "evaluation_implementation_sha256": artifact_metadata["evaluation_implementation_sha256"],
            "model_name": model_name,
            "source": source,
            "script_sha256": script_digest,
            "dataset_sha256": dataset_digest,
            "seed": SEED,
            "maximum_length": MAX_LENGTH,
            "same_dataset_heads_and_training_policy": True,
            "backbone_frozen": True,
            "parameter_groups_consumed": ["base_encoder", "organ_adapter", "cell_adapter", "typed_heads"],
            "base_model": model_metadata,
            "model_load_validation": encoder.loading_report,
            "embedding_artifact": embedding_artifact,
            "head_artifact": head_artifact,
            "training": training,
            "calibration": calibration,
            "test_metrics": test_metrics,
            "ood_test_metrics": ood_metrics,
            "native_laya_reference": native_reference,
            "encoder_latency": latency,
            "extraction_latency_ms_per_example": {
                "state_p50": percentile(extraction_latencies, 50),
                "state_p95": percentile(extraction_latencies, 95),
                "state_p99": percentile(extraction_latencies, 99),
                "candidate_pair_p50": percentile(target_extraction_latencies, 50),
                "candidate_pair_p95": percentile(target_extraction_latencies, 95),
                "candidate_pair_p99": percentile(target_extraction_latencies, 99),
            },
            "timing_seconds": {
                "snapshot_download": download_finished - started,
                "backend_load_and_immutable_view": load_finished - download_finished,
                "feature_extraction": encode_finished - encode_started,
                "head_training": training_finished - training_started,
                "total": time.time() - started,
            },
            "process": {**process_metadata(), "device": str(encoder.device)},
            "maximum_rss_bytes": maximum_rss_bytes(),
            "retrospective_temporal_holdout": False,
            "synthetic_panel_only": True,
            "split_semantics": "generated_fixture_partition_with_shared_templates",
            "early_stopping_split": "tuning",
            "calibration_split": "calibration",
            "prospective_future_window_evidence": False,
            "production_activation": False,
            "operator_acceptance": False,
            "selected": False,
            "release": False,
        }
        if repository_source() != source:
            raise RuntimeError("source identity changed during backend execution")
        receipt_bytes = canonical_json(receipt)
        receipt_digest = sha256_bytes(receipt_bytes)
        receipt_dir = output_dir / "receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"{model_name}-{receipt_digest}.json"
        receipt_path.write_bytes(receipt_bytes)
        (receipt_dir / f"{model_name}.current.json").write_bytes(
            canonical_json(
                {
                    "schema": "hepta.decision-cell-bakeoff-current.v1",
                    "receipt_sha256": receipt_digest,
                    "receipt_path": str(receipt_path),
                }
            )
        )
        return receipt_path
    finally:
        encoder.close()


def verified_receipt(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    value = json.loads(data)
    if value.get("schema") != SCHEMA or canonical_json(value) != data:
        raise RuntimeError(f"unexpected or non-canonical bakeoff receipt: {path}")
    root = path.parent.parent.resolve()

    def bound_file(raw: str, expected: str) -> Path:
        candidate = Path(raw)
        resolved = candidate.resolve(strict=True)
        if candidate.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
            raise RuntimeError("bakeoff artifact escapes its retained output root")
        if sha256_file(resolved) != expected:
            raise RuntimeError("bakeoff artifact content digest mismatch")
        return resolved

    dataset = root / "dataset" / f"dataset-{value['dataset_sha256']}.json"
    bound_file(str(dataset), value["dataset_sha256"])
    head = value["head_artifact"]
    manifest_path = bound_file(head["manifest_path"], head["manifest_sha256"])
    bound_file(head["weights_path"], head["weights_sha256"])
    manifest = json.loads(manifest_path.read_text())
    for key in ("dataset_sha256", "source", "script_sha256", "base_model", "calibration",
                "evaluation_profile", "evaluation_implementation_sha256"):
        if manifest.get(key) != value.get(key):
            raise RuntimeError("bakeoff manifest/receipt semantic mismatch: " + key)
    if manifest.get("weights_sha256") != head["weights_sha256"]:
        raise RuntimeError("bakeoff head bytes are not bound by the manifest")
    embeddings = value["embedding_artifact"]
    bound_file(embeddings["path"], embeddings["sha256"])
    for record in (value, manifest):
        if any(record.get(key) is not False for key in ("production_activation", "operator_acceptance", "selected", "release")):
            raise RuntimeError("bakeoff cannot issue deployment or selection authority")
    return value, sha256_bytes(data)


def current_model_receipt(
    output_dir: Path,
    model_name: str,
) -> tuple[dict[str, Any], str, Path]:
    pointer_path = output_dir / "receipts" / f"{model_name}.current.json"
    pointer = json.loads(pointer_path.read_text())
    path = Path(pointer["receipt_path"])
    receipt, digest = verified_receipt(path)
    if pointer["receipt_sha256"] != digest:
        raise RuntimeError(f"receipt pointer digest mismatch: {model_name}")
    return receipt, digest, path


def candidate_quality(receipt: dict[str, Any]) -> tuple[float, dict[str, float]]:
    test = receipt["test_metrics"]
    ood = receipt["ood_test_metrics"]
    quality = (
        0.25 * test["action_accuracy"]
        + 0.15 * test["target_accuracy"]
        + 0.15 * test["disposition_accuracy"]
        + 0.10 * test["postcondition_accuracy"]
        + 0.15 * test["joint_exact_accuracy"]
        + 0.10 * ood["ood_accuracy"]
        + 0.05 * (1.0 - test["action_ece"])
        + 0.05 * max(0.0, 1.0 - test["value_cost_rmse"])
    )
    latency_p95 = receipt["encoder_latency"]["batch_1"]["p95_ms_per_example"]
    rss_mib = receipt["maximum_rss_bytes"] / (1024 * 1024)
    resource_penalty = 0.01 * math.log1p(latency_p95) + 0.005 * math.log1p(rss_mib)
    score = quality - resource_penalty
    return score, {
        "quality": quality,
        "resource_penalty": resource_penalty,
        "score": score,
        "latency_p95_ms": latency_p95,
        "maximum_rss_mib": rss_mib,
    }


eligibility = quality_gates


def repository_source() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    if git("-C", str(root), "status", "--porcelain"):
        raise RuntimeError("bakeoff requires an unchanged committed source checkout")
    return {
        "repository_root": str(root),
        "commit": git("-C", str(root), "rev-parse", "HEAD"),
        "tree": git("-C", str(root), "rev-parse", "HEAD^{tree}"),
    }


def resolved_device(requested: str) -> str:
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    return requested


def ensure_dataset(output_dir: Path) -> tuple[list[Example], Path, str]:
    rows = build_dataset()
    dataset_dir = output_dir / "dataset"
    path, digest = write_dataset(rows, dataset_dir)
    counts = {split: len(split_rows(rows, split)) for split in ("train", "tuning", "calibration", "test", "ood_test")}
    if min(counts.values()) < 1:
        raise RuntimeError(f"dataset split is empty: {counts}")
    return rows, path, digest


def supply_chain_admission(receipt: dict[str, Any]) -> dict[str, bool]:
    return snapshot_supply_chain_admission(receipt["base_model"])


def comparison_rows(output_dir: Path, models: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if len(models) != len(set(models)):
        raise RuntimeError("duplicate model identity in comparison")
    comparison_identity = None
    for model_name in models:
        receipt, receipt_digest, receipt_path = current_model_receipt(output_dir, model_name)
        if receipt.get("evaluation_profile") != EVALUATION_PROFILE or receipt.get(
            "evaluation_implementation_sha256"
        ) != sha256_file(Path(__file__).with_name("decision_cell_metrics.py")):
            raise RuntimeError("historical evaluation profile requires its original evaluator or an explicit new evaluation")
        identity = (receipt["dataset_sha256"], receipt["script_sha256"], receipt["source"]["commit"],
                    receipt["source"]["tree"], receipt["maximum_length"],
                    receipt["evaluation_profile"], receipt["evaluation_implementation_sha256"],
                    canonical_json(receipt["process"]))
        if receipt["model_name"] != model_name or (comparison_identity is not None and identity != comparison_identity):
            raise RuntimeError("bakeoff comparison mixes source, data or model identities")
        comparison_identity = identity
        score, score_components = candidate_quality(receipt)
        gates = eligibility(receipt)
        supply = supply_chain_admission(receipt)
        rows.append(
            {
                "model_name": model_name,
                "receipt_path": str(receipt_path),
                "receipt_sha256": receipt_digest,
                "score": score,
                "score_components": score_components,
                "quality_gates": gates,
                "quality_eligible": all(gates.values()),
                "supply_chain": supply,
                "internal_shadow_eligible": all(gates.values())
                and supply["exact_revision_bound"]
                and supply["snapshot_content_addressed"]
                and supply["no_unreviewed_remote_code"],
                "distribution_candidate_eligible": all(gates.values())
                and all(supply.values()),
            }
        )
    return rows


def summarize_receipts(output_dir: Path, models: Sequence[str]) -> Path:
    rows = comparison_rows(output_dir, models)
    summary = {
        "schema": "hepta.decision-cell-backend-bakeoff-summary.v1",
        "evaluation_profile": EVALUATION_PROFILE,
        "evaluation_implementation_sha256": sha256_file(Path(__file__).with_name("decision_cell_metrics.py")),
        "source": repository_source(),
        "script_sha256": sha256_file(Path(__file__)),
        "models": rows,
        **recommendations(rows),
        "selection_authority": False,
        "candidate_scope": "synthetic_fixture_only",
        "runtime_selection_eligible": False,
        "operator_acceptance": False,
        "production_activation": False,
        "prospective_future_window_evidence": False,
        "interpretation": (
            "This is a reproducible candidate recommendation. It neither selects an artifact "
            "nor substitutes for independent license review, future-window evaluation, operator acceptance, or activation."
        ),
    }
    data = canonical_json(summary)
    digest = sha256_bytes(data)
    directory = output_dir / "summaries"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"backend-bakeoff-{digest}.json"
    path.write_bytes(data)
    (directory / "current.json").write_bytes(
        canonical_json(
            {
                "schema": "hepta.decision-cell-backend-bakeoff-summary-current.v1",
                "summary_path": str(path),
                "summary_sha256": digest,
            }
        )
    )
    return path

def verify_outputs(output_dir: Path, models: Sequence[str]) -> dict[str, Any]:
    verified_models: list[dict[str, str]] = []
    for model_name in models:
        _, digest, path = current_model_receipt(output_dir, model_name)
        verified_models.append(
            {"model_name": model_name, "receipt_path": str(path), "receipt_sha256": digest}
        )
    pointer_path = output_dir / "summaries" / "current.json"
    pointer = json.loads(pointer_path.read_text())
    summary_path = Path(pointer["summary_path"])
    summary_bytes = summary_path.read_bytes()
    summary_digest = sha256_bytes(summary_bytes)
    if pointer["summary_sha256"] != summary_digest:
        raise RuntimeError("summary pointer digest mismatch")
    summary = json.loads(summary_bytes)
    if summary.get("schema") != "hepta.decision-cell-backend-bakeoff-summary.v1":
        raise RuntimeError("unexpected summary schema")
    expected = {(row["model_name"], row["receipt_sha256"]) for row in verified_models}
    observed = [(row["model_name"], row["receipt_sha256"]) for row in summary["models"]]
    if len(observed) != len(expected) or set(observed) != expected:
        raise RuntimeError("summary does not bind exactly the verified model receipts")
    verify_summary_projection(
        summary, comparison_rows(output_dir, models),
        sha256_file(Path(__file__).with_name("decision_cell_metrics.py")),
    )
    return {
        "status": "PASS_DECISION_CELL_BACKEND_BAKEOFF_OUTPUTS",
        "models": verified_models,
        "summary_path": str(summary_path),
        "summary_sha256": summary_digest,
        "selection_authority": False,
        "production_activation": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/data/hepta-decisioncell-bakeoff"),
    )
    parser.add_argument(
        "--model-root",
        type=Path,
        default=Path("/data/hepta-decisioncell-models"),
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="materialize the frozen generated dataset")
    prepare.set_defaults(handler=command_prepare)

    materialize = subparsers.add_parser(
        "materialize-models",
        help="download and hash pinned model snapshots without executing model code",
    )
    materialize.add_argument(
        "--models", nargs="+", choices=sorted(MODEL_SPECS), default=sorted(MODEL_SPECS)
    )
    materialize.set_defaults(handler=command_materialize_models)

    run = subparsers.add_parser("run", help="run one exact pinned backend")
    run.add_argument("--model", required=True, choices=sorted(MODEL_SPECS))
    run.set_defaults(handler=command_run)

    summarize = subparsers.add_parser("summarize", help="compare current model receipts")
    summarize.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=sorted(MODEL_SPECS))
    summarize.set_defaults(handler=command_summarize)

    verify = subparsers.add_parser("verify", help="verify receipt and summary content addressing")
    verify.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=sorted(MODEL_SPECS))
    verify.set_defaults(handler=command_verify)

    all_models = subparsers.add_parser("all", help="run each model in a fresh process, then summarize and verify")
    all_models.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=sorted(MODEL_SPECS))
    all_models.add_argument("--model-timeout-seconds", type=float, default=900)
    all_models.set_defaults(handler=command_all)
    return parser


def command_materialize_models(args: argparse.Namespace) -> int:
    snapshots: list[dict[str, Any]] = []
    for model_name in args.models:
        path, manifest = model_snapshot(MODEL_SPECS[model_name], args.model_root)
        snapshots.append(
            {
                "model_name": model_name,
                "path": str(path),
                "snapshot_digest": manifest["snapshot_digest"],
                "observed_hub_sha": manifest["observed_hub_sha"],
                "trust_remote_code": manifest["trust_remote_code"],
                "executed_model_code": False,
            }
        )
    print(
        json.dumps(
            {
                "status": "MATERIALIZED_PINNED_DECISION_CELL_MODELS",
                "models": snapshots,
                "model_code_executed": False,
                "production_activation": False,
            },
            sort_keys=True,
        )
    )
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    rows, path, digest = ensure_dataset(args.output_dir)
    print(
        json.dumps(
            {
                "status": "PREPARED_DECISION_CELL_BAKEOFF_DATASET",
                "path": str(path),
                "sha256": digest,
                "rows": len(rows),
                "source": repository_source(),
            },
            sort_keys=True,
        )
    )
    return 0


def command_run(args: argparse.Namespace) -> int:
    rows, dataset_path, dataset_digest = ensure_dataset(args.output_dir)
    source = repository_source()
    device = resolved_device(args.device)
    receipt = run_model(
        args.model,
        rows,
        dataset_digest,
        args.output_dir,
        args.model_root,
        source,
        sha256_file(Path(__file__)),
        device,
    )
    value, digest = verified_receipt(receipt)
    print(
        json.dumps(
            {
                "status": "COMPLETED_DECISION_CELL_BACKEND_RUN",
                "model": args.model,
                "device": device,
                "dataset_path": str(dataset_path),
                "dataset_sha256": dataset_digest,
                "receipt_path": str(receipt),
                "receipt_sha256": digest,
                "quality_gates": eligibility(value),
                "production_activation": False,
            },
            sort_keys=True,
        )
    )
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    path = summarize_receipts(args.output_dir, args.models)
    data = path.read_bytes()
    print(
        json.dumps(
            {
                "status": "SUMMARIZED_DECISION_CELL_BACKEND_BAKEOFF",
                "path": str(path),
                "sha256": sha256_bytes(data),
                "summary": json.loads(data),
            },
            sort_keys=True,
        )
    )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    print(json.dumps(verify_outputs(args.output_dir, args.models), sort_keys=True))
    return 0


def command_all(args: argparse.Namespace) -> int:
    from bakeoff_panel import run_panel

    if any(model not in MODEL_SPECS for model in args.models):
        raise ValueError("unknown backend in comparison panel")
    source = repository_source()
    panel, execution = run_panel(
        script=Path(__file__), output_dir=args.output_dir,
        model_root=args.model_root, models=args.models,
        device=resolved_device(args.device), source=source,
        timeout_seconds=args.model_timeout_seconds,
    )
    if not execution["all_executed_successfully"]:
        return 1
    if repository_source() != source:
        raise RuntimeError("source changed during backend panel")
    panel_args = argparse.Namespace(**vars(args))
    panel_args.output_dir = panel
    summarized = command_summarize(panel_args)
    return summarized if summarized else command_verify(panel_args)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    args.output_dir = args.output_dir.resolve()
    args.model_root = args.model_root.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.model_root.mkdir(parents=True, exist_ok=True)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
