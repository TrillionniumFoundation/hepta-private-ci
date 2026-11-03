"""Bind an existing fitted head to explicit bilingual query capabilities.

Weights and calibration thresholds remain unchanged. Generated cases measure
declared grammar coverage, not blind natural-language generalization.
"""

import argparse
import copy
import json
from pathlib import Path

from semantic_protocol import BOUNDED_SCHEMA, SCHEMA, canonical, digest

ENTITIES_ZH = ("雪松港", "枫树码头", "白桦草地", "柳树山脊", "杜松湾", "白杨林", "榆树路口", "松树台地")
WORKFLOWS_ZH = ("琥珀路线", "钴蓝路径", "靛蓝计划", "玉石流程", "珊瑚程序", "白银轨道", "紫罗兰方案", "赭石流程")
TEMPLATES = (
    ("semantic", "zh", "读取{entity}的策略"),
    ("semantic", "zh", "查看{entity}的库存策略"),
    ("procedure", "zh", "读取{workflow}的步骤"),
    ("procedure", "zh", "查看{workflow}的操作步骤"),
    ("apply", "zh", "用{workflow}计算{entity}的结果"),
    ("apply", "zh", "将{workflow}应用到{entity}"),
    ("semantic", "en", "Read the reserve pack and limit policy at {entity}"),
    ("semantic", "en", "Read the policy for {entity}"),
    ("procedure", "en", "Retrieve the four stored operations of {workflow}"),
    ("procedure", "en", "Read the steps for {workflow}"),
    ("apply", "en", "Compute {workflow} using latest stock and policy at {entity}"),
    ("apply", "en", "Apply {workflow} to {entity}"),
    ("semantic", "en", "Read the reserve, pack and limit settings of {entity}."),
    ("procedure", "en", "Retrieve the stored program called {workflow}."),
    ("apply", "en", "Execute {workflow} on the latest stock count for {entity}."),
)


def prepare(model):
    if model["schema"] != SCHEMA:
        raise ValueError("requires an unchanged v1 fitted head")
    model = copy.deepcopy(model)
    english = {}
    for alias in model["aliases"]:
        parts = alias["key"].split(":")
        if len(parts) != 3 or parts[0] != "inventory" or parts[1] != alias["kind"]:
            raise ValueError("alias is outside the existing inventory registry")
        index = int(parts[2])
        names = ENTITIES_ZH if alias["kind"] == "entity" else WORKFLOWS_ZH
        if not 0 <= index < len(names) or not 1 <= len(alias["phrases"]) < 8:
            raise ValueError("alias capacity or known index differs")
        english[(alias["kind"], index)] = alias["phrases"][0]
        alias["phrases"].append(names[index])
    if set(english) != {(kind, i) for kind in ("entity", "workflow") for i in range(8)}:
        raise ValueError("complete original eight-entity/eight-workflow registry required")
    model["schema"] = BOUNDED_SCHEMA
    model["query_templates"] = [{"operation": operation, "template": template} for operation, _, template in TEMPLATES]
    cases = []
    for family, (operation, language, template) in enumerate(TEMPLATES):
        for index in range(8):
            workflow = (index + 3) % 8
            entity_name = ENTITIES_ZH[index] if language == "zh" else english[("entity", index)]
            workflow_name = WORKFLOWS_ZH[workflow] if language == "zh" else english[("workflow", workflow)]
            row = {"id": f"declared:{family}:{index}", "role": {"semantic":"semantic", "procedure":"skill", "apply":"compose"}[operation],
                   "text": template.format(entity=entity_name, workflow=workflow_name), "language": language,
                   "family": f"declared-template-{family}", "entity": None if operation == "procedure" else index,
                   "workflow": None if operation == "semantic" else workflow}
            cases.append(row)
            unknowns = [row["text"] + ("并删除所有记录" if language == "zh" else " and delete all records")]
            if operation != "procedure":
                unknowns.extend([template.format(entity=entity_name + ("新区" if language == "zh" else "view"), workflow=workflow_name),
                                 template.format(entity="未知港" if language == "zh" else "Unknown Port", workflow=workflow_name)])
            if operation != "semantic":
                unknowns.append(template.format(entity=entity_name, workflow="未知流程" if language == "zh" else "Unknown Workflow"))
            for negative, text in enumerate(unknowns):
                cases.append({**row, "id": f"negative:{family}:{index}:{negative}", "role":"unknown",
                              "family":"unknown-name-or-extra-capability", "text":text, "entity":None, "workflow":None})
    return model, cases


def run(args):
    raw = args.model.read_bytes()
    if digest(raw) != args.model_sha256:
        raise ValueError("source fitted head digest differs")
    model, cases = prepare(json.loads(raw))
    args.output.mkdir(parents=True, exist_ok=False)
    model_bytes, case_bytes = canonical(model), canonical(cases)
    (args.output / "semantic-router.json").write_bytes(model_bytes)
    (args.output / "queries.json").write_bytes(case_bytes)
    receipt = {"schema":"hepta.semantic-bounded-addressing-preparation.v2", "source_model_sha256":digest(raw),
               "model_sha256":digest(model_bytes), "queries_sha256":digest(case_bytes), "rows":len(cases),
               "training_or_thresholds_changed":False, "source_sha256":digest(Path(__file__).read_bytes()),
               "scope":"declared bilingual grammar and exact Unicode aliases; existing learned head may abstain; no fresh blind generalization claim"}
    (args.output / "PREPARE.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
