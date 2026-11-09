"""PRED-1 training/development-only post-hoc diagnostic, using stdlib only.

This reader never imports the experiment runner, opens checkpoints, generates
samples, or reads confirmation results.  It reports descriptive evidence and
consumed fit costs; it cannot change the original qualification decision.
"""

import argparse
import ast
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import stat
import statistics


VARIANTS = (
    "single_step",
    "gru",
    "diag_ssm",
    "dual_timescale",
    "gru_reset",
    "gru_no_action",
)
FAMILIES = ("gru", "diag_ssm", "dual_timescale")
MAX_INPUT_BYTES = 1_048_576
RECORD_FIELDS = {
    "variant",
    "seed",
    "parameters",
    "hidden_dim",
    "best_epoch",
    "epochs_consumed",
    "optimizer_steps_consumed",
    "selected_checkpoint_steps",
    "training_examples_consumed",
    "train_wall_seconds",
    "train_process_cpu_seconds",
    "checkpoint",
    "checkpoint_sha256",
    "curve",
    "dev",
    "metering",
}


def canonical(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_bound(path, manifest, role):
    path = Path(path).absolute()
    try:
        before = path.lstat()
    except OSError as error:
        raise ValueError(f"expected ordinary non-symlink input: {path}") from error
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"expected ordinary non-symlink input: {path}")
    if before.st_size > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds one MiB: {path}")
    # NOFOLLOW rejects a replaced symlink on supporting platforms; NONBLOCK
    # prevents a replaced FIFO from blocking before the descriptor is checked.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"expected ordinary non-symlink input: {path}") from error
    with os.fdopen(descriptor, "rb", buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ValueError(f"input changed or is not an ordinary file: {path}")
        if opened.st_size > MAX_INPUT_BYTES:
            raise ValueError(f"input exceeds one MiB: {path}")
        # A file can grow after either stat. Never issue an unbounded read.
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds one MiB: {path}")
    manifest.append(
        {
            "path": str(path),
            "role": role,
            "sha256": sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    )
    return raw.decode("utf-8")


def read_json(path, manifest, role):
    return json.loads(
        read_bound(path, manifest, role),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"nonfinite JSON number: {value}")
        ),
    )


def finite(value, name, nonnegative=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be finite numeric data")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def source_wiring(source):
    """Inspect syntax as data; do not import or execute the supplied source."""
    tree = ast.parse(source)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if not {"train_one", "run"}.issubset(functions):
        raise ValueError("source must contain archived train_one and run functions")
    model, shuffle, datasets, selection = [], [], {}, []
    for node in ast.walk(functions["train_one"]):
        if isinstance(node, ast.Call):
            if (
                ast.unparse(node.func) == "Model"
                and node.args
                and ast.unparse(node.args[-1]) == "seed"
            ):
                model.append(ast.get_source_segment(source, node))
            if (
                ast.unparse(node.func) == "np.random.default_rng"
                and len(node.args) == 1
            ):
                if ast.dump(node.args[0]) == ast.dump(
                    ast.parse("seed + 911", mode="eval").body
                ):
                    shuffle.append(ast.get_source_segment(source, node))
        if isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(
            ast.parse("dev_loss < best", mode="eval").body
        ):
            selection.append(ast.get_source_segment(source, node.test))
    for node in ast.walk(functions["run"]):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "generate_dataset"
            and len(node.args) >= 3
        ):
            split = node.args[2]
            if isinstance(split, ast.Constant) and split.value in ("train", "dev"):
                if ast.unparse(node.args[1]) != "seed":
                    raise ValueError(
                        "dataset seed wiring differs from archived coupled protocol"
                    )
                if split.value in datasets:
                    raise ValueError("ambiguous dataset generation call")
                datasets[split.value] = ast.get_source_segment(source, node)
    if (
        len(model) != 1
        or len(shuffle) != 1
        or len(selection) != 1
        or set(datasets) != {"train", "dev"}
    ):
        raise ValueError(
            "unsupported source wiring; audit the changed protocol before interpreting seeds"
        )
    return {
        "data_sampling": datasets,
        "initialization": model[0],
        "batch_order": shuffle[0],
        "checkpoint_selection": selection[0],
        "factors_independently_varied": False,
        "interpretation": "A seed labels a coupled data/initialization/batch-order realization; causal factor attribution is unavailable.",
    }


def validate_config(config):
    if config.get("schema") != "pred1-experiment-v1":
        raise ValueError("unsupported registered configuration")
    groups = []
    for name in ("selection_seeds", "seeds"):
        values = config.get(name)
        if (
            not isinstance(values, list)
            or not values
            or any(
                isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in values
            )
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"{name} must contain unique nonnegative integer seeds")
        groups.append(values)
    if set(groups[0]) & set(groups[1]):
        raise ValueError("selection and evaluation training seed sets overlap")
    for key in ("train_episodes", "dev_episodes", "epochs", "batch_size"):
        positive_int(config.get(key), key)
    if config.get("checkpoint_selection") != "minimum development observed-label NLL":
        raise ValueError("unsupported checkpoint selection rule")


def validate_record(record, variant, seed, config):
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise ValueError(
            "expected only the archived training-record fields; result/confirmation inputs are refused"
        )
    if (
        record["variant"] != variant
        or record["seed"] != seed
        or isinstance(record["seed"], bool)
    ):
        raise ValueError("training filename and payload identity disagree")
    curve = record["curve"]
    epochs, examples, batch = (
        config["epochs"],
        config["train_episodes"],
        config["batch_size"],
    )
    steps = math.ceil(examples / batch)
    if not isinstance(curve, list) or len(curve) != epochs:
        raise ValueError("missing training epochs")
    for i, point in enumerate(curve, 1):
        if (
            not isinstance(point, dict)
            or set(point) != {"epoch", "train_nll", "dev_observed_nll"}
            or point["epoch"] != i
            or isinstance(point["epoch"], bool)
        ):
            raise ValueError(
                "curve must have complete ordered epochs and only train/dev losses"
            )
        finite(point["train_nll"], "train_nll", True)
        finite(point["dev_observed_nll"], "dev_observed_nll", True)
    expected_best = min(range(epochs), key=lambda i: curve[i]["dev_observed_nll"]) + 1
    required = {
        "epochs_consumed": epochs,
        "optimizer_steps_consumed": epochs * steps,
        "training_examples_consumed": epochs * examples,
        "best_epoch": expected_best,
        "selected_checkpoint_steps": expected_best * steps,
    }
    for key, value in required.items():
        if record[key] != value or isinstance(record[key], bool):
            raise ValueError(
                f"{variant}/{seed}: inconsistent {key}: expected {value}, got {record[key]}"
            )
    for key in ("parameters", "hidden_dim"):
        positive_int(record[key], key)
    for key in ("train_wall_seconds", "train_process_cpu_seconds"):
        finite(record[key], key, True)
    if (
        not isinstance(record["checkpoint"], str)
        or Path(record["checkpoint"]).name != record["checkpoint"]
    ):
        raise ValueError(
            "checkpoint metadata must be a basename; no checkpoint is opened"
        )
    digest = record["checkpoint_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("invalid declared checkpoint digest")
    dev = record["dev"]
    if not isinstance(dev, dict) or dev.get("episodes") != config["dev_episodes"]:
        raise ValueError("development denominator differs from registration")

    def inspect_nested(value):
        if isinstance(value, dict):
            if any("confirm" in str(key).lower() for key in value):
                raise ValueError(
                    "confirmation fields are forbidden in a training record"
                )
            for item in value.values():
                inspect_nested(item)
        elif isinstance(value, list):
            for item in value:
                inspect_nested(item)
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            finite(value, "nested training metadata")

    inspect_nested(record)
    for key in (
        "net_utility",
        "inference_wall_seconds",
        "inference_process_cpu_seconds",
        "planning_wall_seconds",
        "planning_process_cpu_seconds",
    ):
        finite(dev.get(key), f"dev.{key}", key != "net_utility")
    return record


def fit_row(record, role):
    curve, epochs = record["curve"], record["epochs_consumed"]
    anchor = max(1, 2 * epochs // 3)
    minimum = curve[record["best_epoch"] - 1]["dev_observed_nll"]
    return {
        "seed": record["seed"],
        "seed_role": role,
        "variant": record["variant"],
        "parameters": record["parameters"],
        "best_epoch": record["best_epoch"],
        "best_at_budget_boundary": record["best_epoch"] == epochs,
        "tail_anchor_epoch": anchor,
        "tail_end_epoch": epochs,
        "tail_dev_nll_improvement": curve[anchor - 1]["dev_observed_nll"]
        - curve[-1]["dev_observed_nll"],
        "tail_train_nll_improvement": curve[anchor - 1]["train_nll"]
        - curve[-1]["train_nll"],
        "minimum_dev_nll": minimum,
        "final_dev_nll_minus_minimum": curve[-1]["dev_observed_nll"] - minimum,
        "dev_net_utility": record["dev"]["net_utility"],
        "consumed_optimizer_steps": record["optimizer_steps_consumed"],
        "selected_checkpoint_steps": record["selected_checkpoint_steps"],
        "consumed_examples": record["training_examples_consumed"],
        "train_wall_seconds": record["train_wall_seconds"],
        "train_process_cpu_seconds": record["train_process_cpu_seconds"],
    }


def audit(campaign, config_path, source_path):
    manifest = []
    config = read_json(config_path, manifest, "registered_configuration")
    validate_config(config)
    wiring = source_wiring(
        read_bound(source_path, manifest, "archived_runner_source_not_executed")
    )
    records, rows = {}, []
    for role, seeds in (
        ("family_selection_training", config["selection_seeds"]),
        ("evaluation_training_development_only", config["seeds"]),
    ):
        for seed in seeds:
            for variant in VARIANTS:
                # Explicit names only: no glob, directory traversal, or confirm/result opening.
                path = Path(campaign) / f"{variant}-{seed}-training.json"
                record = validate_record(
                    read_json(path, manifest, "training_record"), variant, seed, config
                )
                records[(variant, seed)] = record
                rows.append(fit_row(record, role))
    means = {
        v: statistics.mean(
            records[(v, s)]["dev"]["net_utility"] for s in config["selection_seeds"]
        )
        for v in FAMILIES
    }
    selected = max(FAMILIES, key=lambda variant: (means[variant], variant))
    paired = []
    for seed in config["seeds"]:
        base = records[("single_step", seed)]["dev"]["net_utility"]
        selected_dev = records[(selected, seed)]["dev"]["net_utility"]
        paired.append(
            {
                "seed": seed,
                "selected_minus_single_step_dev_net_utility": selected_dev - base,
                "gru_minus_single_step_dev_net_utility": records[("gru", seed)]["dev"][
                    "net_utility"
                ]
                - base,
                "gru_minus_gru_reset_dev_net_utility": records[("gru", seed)]["dev"][
                    "net_utility"
                ]
                - records[("gru_reset", seed)]["dev"]["net_utility"],
                "gru_minus_gru_no_action_dev_net_utility": records[("gru", seed)][
                    "dev"
                ]["net_utility"]
                - records[("gru_no_action", seed)]["dev"]["net_utility"],
            }
        )
    costs = {}
    for variant in VARIANTS:
        group = [r for (v, _), r in records.items() if v == variant]
        costs[variant] = {
            "fits": len(group),
            **{
                key: sum(r[key] for r in group)
                for key in (
                    "optimizer_steps_consumed",
                    "selected_checkpoint_steps",
                    "training_examples_consumed",
                    "train_wall_seconds",
                    "train_process_cpu_seconds",
                )
            },
            "dev_inference_wall_seconds": sum(
                r["dev"]["inference_wall_seconds"] for r in group
            ),
            "dev_inference_process_cpu_seconds": sum(
                r["dev"]["inference_process_cpu_seconds"] for r in group
            ),
            "dev_planning_wall_seconds": sum(
                r["dev"]["planning_wall_seconds"] for r in group
            ),
            "dev_planning_process_cpu_seconds": sum(
                r["dev"]["planning_process_cpu_seconds"] for r in group
            ),
        }
    totals = {
        key: sum(row[key] for row in costs.values())
        for key in next(iter(costs.values()))
    }
    return {
        "schema": "pred1-training-dev-diagnostic-v1",
        "status": "POSTHOC_DIAGNOSTIC_ONLY",
        "original_qualification": "HOLD_UNCHANGED",
        "confirmation_data_read": False,
        "confirmation_samples_generated": 0,
        "training_executed": False,
        "cause": "The seed-202 investigation was motivated by an already observed original result; these are retrospective development diagnostics, not an independent test.",
        "checkpoint_bytes_verified": False,
        "training_budget": {
            key: config[key]
            for key in ("epochs", "train_episodes", "dev_episodes", "batch_size")
        },
        "source_wiring": wiring,
        "input_manifest": manifest,
        "input_manifest_sha256": sha256(canonical(manifest).encode()).hexdigest(),
        "record_count": len(rows),
        "fit_rows": rows,
        "registered_family_rule_recomputed": {
            "selection_seeds": config["selection_seeds"],
            "development_means": means,
            "selected_family": selected,
            "new_family_or_checkpoint_selected": False,
        },
        "evaluation_training_seed_development_comparisons": paired,
        "costs": {
            "per_variant": costs,
            "original_fit_totals": totals,
            "physical_cost_complete": False,
            "included": "All six arms and all eight registered training seeds; 48 original fits and their saved development inference/planning metrics.",
            "excluded": [
                "dataset generation",
                "confirmation",
                "failed/interrupted attempts without training records",
                "recovery fits",
                "audit",
                "publication",
                "energy",
                "financial cost",
            ],
            "wall_scope": "Sum of reported phase durations; not elapsed campaign or project time.",
            "selected_checkpoint_steps_are_not_consumed_cost": True,
        },
        "limits": [
            "Training metadata and archived source hashes bind this report's inputs but do not independently attest the original execution.",
            "Checkpoint digests are declared metadata, not verified weight bytes.",
            "Development utility and NLL differ; NLL selected checkpoints, while utility selected the family only on the three family-selection seeds.",
            "Coupled seeds do not identify initialization, sampling or order causally.",
            "No independence claim, hypothesis test, new model choice, or confirmation qualification follows from these diagnostics.",
        ],
    }


def markdown(report):
    totals = report["costs"]["original_fit_totals"]
    family = report["registered_family_rule_recomputed"]
    epochs = report["training_budget"]["epochs"]
    anchor = max(1, 2 * epochs // 3)
    lines = [
        "# PRED-1 训练／开发诊断",
        "",
        "**状态：事后诊断完成；原 HOLD 保持。**",
        "",
        "输入只包括注册配置、归档 runner 和 48 份训练记录。未读取确认结果、生成样本或执行训练。",
        "",
        "## 已核查的训练分母",
        "",
        f"全部 {totals['fits']} 次原始拟合消费 {totals['optimizer_steps_consumed']:,} 个优化器步骤、{totals['training_examples_consumed']:,} 个训练样本呈现。",
        f"被选 checkpoint 共包含 {totals['selected_checkpoint_steps']:,} 步；该数量不能替代实际训练成本。",
        f"原始拟合训练耗时之和 {totals['train_wall_seconds']:.6f} 秒，CPU {totals['train_process_cpu_seconds']:.6f} 秒。",
        "恢复、失败、数据生成、确认、审核与发布不在这组原始训练记录的分母内；物理及货币成本未补齐。",
        "",
        "## seed 诊断",
        "",
        "原 runner 用同一 seed 生成训练／开发数据和初始化模型，并以 seed+911 产生批次顺序。现有记录无法拆开这三个因素。",
        "",
        f"仅按原三个 selection seeds 复算的家族规则仍指向 {family['selected_family']}，不构成新的模型选择。",
        "",
        f"| seed | GRU 最佳 epoch | 第 {anchor}→{epochs} epoch 开发 NLL 改善 | 开发净效用差：GRU−single_step | GRU−reset | GRU−no_action |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    pairs = {
        row["seed"]: row
        for row in report["evaluation_training_seed_development_comparisons"]
    }
    for row in report["fit_rows"]:
        if row["variant"] == "gru" and row["seed"] in pairs:
            p = pairs[row["seed"]]
            lines.append(
                f"| {row['seed']} | {row['best_epoch']} | {row['tail_dev_nll_improvement']:.6f} | {p['gru_minus_single_step_dev_net_utility']:.6f} | {p['gru_minus_gru_reset_dev_net_utility']:.6f} | {p['gru_minus_gru_no_action_dev_net_utility']:.6f} |"
            )
    lines += [
        "",
        "正的末期 NLL 差表示末期改善；它支持进一步诊断训练预算与耦合 seed 的关系，不能支持增加 epoch 后重用旧确认集。",
        "本问题由已观察的原结果触发，因此上述开发观察本身也属于事后诊断。新确认必须在诊断结束、模型与预算冻结后独立登记。",
        "",
        "## 输入身份与限制",
        "",
        f"输入清单 SHA-256：`{report['input_manifest_sha256']}`。逐文件路径、字节摘要、全部模型及种子行见 companion JSON。",
        "归档源码仅作 AST 静态检查；checkpoint 权重未打开，报告不能重新证明历史运行或 checkpoint 正确性。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory; never overwrite a diagnostic",
    )
    args = parser.parse_args()
    report = audit(args.campaign, args.config, args.source)
    report["diagnostic_implementation_sha256"] = sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "DIAGNOSTIC.json").write_text(canonical(report), encoding="utf-8")
    (args.output / "RESULTS.zh-CN.md").write_text(markdown(report), encoding="utf-8")
    print(
        canonical(
            {
                "status": report["status"],
                "records": report["record_count"],
                "input_manifest_sha256": report["input_manifest_sha256"],
                "output": str(args.output.absolute()),
            }
        ),
        end="",
    )


if __name__ == "__main__":
    main()
