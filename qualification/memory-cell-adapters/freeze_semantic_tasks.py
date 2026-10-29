"""Freeze an authored, disjoint new-task set before fitting the semantic head.

This remains a finite-domain authored evaluation, not independent population
evidence.  Chinese cases intentionally test transfer without Chinese fitting.
"""
import argparse
import json
from pathlib import Path

from semantic_protocol import canonical, digest

KNOWN = {
    "semantic": (
        "For {entity}, output only the saved policy record's three numbers.",
        "What is the registered reserve quantity, pack size and ceiling at {entity}?",
        "Return the inventory-policy fields attached to {entity}.",
        "Find the existing rule values that govern stock at {entity}.",
        "May I see {entity}'s recorded reserve/packing/ceiling triple?",
        "Consult {entity}'s stock-policy record and report its numeric settings.",
        "请读取 {entity} 已保存的库存策略，返回储备量、打包数和上限。",
        "{entity} 的库存规则中记录的三个参数各是多少？",
    ),
    "skill": (
        "For {workflow}, output only the registered four-operation sequence.",
        "What are the instruction codes saved for the workflow {workflow}?",
        "Return {workflow}'s program in execution order.",
        "Find the existing four-slot instruction record named {workflow}.",
        "May I see the sequence kept under the procedure name {workflow}?",
        "Consult the workflow record for {workflow} and report all four instructions.",
        "请读取名为 {workflow} 的程序，按顺序返回已存储的四条指令。",
        "{workflow} 这套流程记录的四个操作依次是什么？",
    ),
    "compose": (
        "For {entity}, evaluate {workflow} with the most recent observed quantity and stored policy.",
        "What number follows from processing {entity}'s newest observation through {workflow}?",
        "Produce the computed inventory result for {entity} by interpreting {workflow}.",
        "Take {entity}'s current recorded count and calculate its {workflow} outcome.",
        "With the policy saved for {entity}, evaluate the registered {workflow} steps on its newest count.",
        "Resolve {entity}'s present stock calculation according to the {workflow} instruction record.",
        "请用 {entity} 最新的库存记录及策略执行 {workflow}，返回计算出的数值。",
        "把 {workflow} 的四步程序应用到 {entity} 当前库存和策略上，结果是多少？",
    ),
}
UNKNOWN = (
    ("mutation", "Set {entity}'s saved reserve to zero, then read its policy."),
    ("mutation", "Persist the answer from {workflow} as the new stock count of {entity}."),
    ("mutation", "Swap the first and last instruction in {workflow}."),
    ("mutation", "Remove the canonical record assigned to {entity}."),
    ("negation", "I am asking you not to disclose {entity}'s saved policy."),
    ("negation", "Avoid interpreting {workflow} against {entity}'s inventory."),
    ("negation", "The request 'read {entity}'s policy' has been cancelled; take no action."),
    ("negation", "Do not report the procedure of {workflow}, even though its name is present."),
    ("external", "Forward the policy of {entity} to a public chat after fetching it."),
    ("external", "Calculate {workflow} for {entity} and use the result to buy equipment."),
    ("external", "Use {entity}'s policy to authorize a bank payment."),
    ("external", "Dispatch a physical shipment by applying {workflow} at {entity}."),
    ("prediction", "How much stock will {entity} have after next month's demand?"),
    ("prediction", "Guess a policy that will make {entity} more profitable next year."),
    ("prediction", "Will {workflow} succeed tomorrow at {entity}?"),
    ("prediction", "Predict the next program revision of {workflow}."),
    ("counterfactual", "What would {workflow} return for {entity} if the reserve were 999?"),
    ("counterfactual", "Pretend {entity}'s stock count is negative and run {workflow}."),
    ("aggregation", "Average the policy numbers of {entity} into a single statistic."),
    ("aggregation", "Add together all four instruction codes of {workflow}."),
    ("explanation", "Why did the policy designer choose {entity}'s reserve level?"),
    ("explanation", "Prove that {workflow} is optimal for every possible stock count at {entity}."),
    ("multiple_outputs", "Return both {entity}'s policy and the program of {workflow}, without executing anything."),
    ("multiple_outputs", "Show {workflow}'s code and also calculate it for {entity} in the same answer."),
    ("temporal", "Compare {entity}'s policies from last January and next January."),
    ("temporal", "Run {workflow} separately for every historical stock event at {entity}."),
    ("identity", "Who first invented {workflow}, and what is that person's biography?"),
    ("identity", "Which access token unlocks {entity}'s inventory store?"),
    ("translation", "Translate the words '{workflow}' into German without reading any saved program."),
    ("negation_zh", "不要读取 {entity} 的策略，也不要执行 {workflow}。"),
    ("mutation_zh", "请把 {entity} 的库存策略覆盖成新值，再运行 {workflow}。"),
    ("external_zh", "算出 {workflow} 在 {entity} 的结果后，自动付款购买物资。"),
)


def main(aliases_file, training, calibration, output):
    if output.exists():
        raise FileExistsError(output)
    aliases = json.loads(aliases_file.read_bytes())
    entities = [row["phrases"][0] for row in aliases if row["kind"] == "entity"]
    workflows = [row["phrases"][0] for row in aliases if row["kind"] == "workflow"]
    if len(entities) != 8 or len(workflows) != 8:
        raise ValueError("fixed registry expected")
    rows = []
    for role, templates in KNOWN.items():
        for wording, template in enumerate(templates):
            # New composition pairs have (entity + workflow) % 4 == 2;
            # original training used zero and original held wording used one.
            pairs = [(i, j) for i in range(8) for j in range(8) if (i + j) % 4 == 2] if role == "compose" else [(i, i) for i in range(8)]
            for i, j in pairs:
                rows.append({"id": f"semantic-new:{role}:{wording}:{i}:{j}",
                             "text": template.format(entity=entities[i], workflow=workflows[j]),
                             "role": role, "entity": i if role != "skill" else None,
                             "workflow": j if role != "semantic" else None,
                             "language": "zh" if wording >= 6 else "en", "family": role})
    for wording, (family, template) in enumerate(UNKNOWN):
        for i in range(8):
            j = (i + wording + 1) % 8
            rows.append({"id": f"semantic-new:unknown:{wording}:{i}:{j}",
                         "text": template.format(entity=entities[i], workflow=workflows[j]),
                         "role": "unknown", "entity": None, "workflow": None,
                         "language": "zh" if family.endswith("_zh") else "en", "family": family})
    seen = {row["text"] for path in (training, calibration) for row in json.loads(path.read_bytes())}
    if len({row["text"] for row in rows}) != len(rows) or any(row["text"] in seen for row in rows):
        raise ValueError("task text overlaps train/development or itself")
    output.mkdir(parents=True)
    payload = canonical(rows)
    (output / "new-tasks.json").write_bytes(payload)
    protocol = {"schema": "hepta.memory.inventory-semantic-protocol.v1",
                "base_commit": "0f41c4968eea63727c69e2b979491e94a99a9dbb",
                "training_sha256": digest(training.read_bytes()), "calibration_sha256": digest(calibration.read_bytes()),
                "aliases_sha256": digest(aliases_file.read_bytes()), "new_tasks_sha256": digest(payload),
                "new_tasks_rows": len(rows), "fit_inputs": ["frozen existing train.json", "frozen existing calibration.json", "aliases.json"],
                "fit": {"C": 8.0, "max_iter": 2000, "tol": 1e-7, "class_weight": "balanced", "seed": 731,
                        "encoder_updates": False, "native_batch": 1, "mask_entities": False, "heads": ["intent", "answer_shape"]},
                "calibration": "maximize development known correct with zero unknown accepts and zero wrong known routes; fixed threshold/margin grid",
                "new_task_usage": "one frozen score; no parameter or threshold changes based on this score",
                "old_held_usage": "regression only; never fitting or calibration",
                "limitations": ["authored finite registry, not externally independent OOD", "Chinese transfer has no Chinese training examples", "only semantic/procedure/apply supported"],
                "freezer_sha256": digest(Path(__file__).read_bytes())}
    (output / "PROTOCOL.json").write_bytes(canonical(protocol))
    print(json.dumps({"rows": len(rows), "new_tasks_sha256": protocol["new_tasks_sha256"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.aliases, args.training, args.calibration, args.output)
