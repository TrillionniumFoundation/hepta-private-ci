"""Freeze an explicit bilingual continuation before fitting or held scoring.

Historical known queries may enter marked replay. New held text never overlaps
the historical 480 cases, training, or development. Template declarations are
the finite capability contract; this is not open-domain language evaluation.
"""
import argparse
import copy
import json
from pathlib import Path
import time

from semantic_protocol import BOUNDED_SCHEMA, INTENTS, bounded_address, canonical, digest, gold


SCHEMA = "hepta.memory.inventory-semantic-bilingual-study.v1"
SOURCES = ("bilingual_semantic_protocol.py", "train_bilingual_semantic.py", "semantic_protocol.py",
           "train_semantic_router.py", "semantic_encoder_worker.py")
TEMPLATES = {
    ("semantic", "zh"): (
        "请读取{entity}的库存策略", "请查询{entity}的库存策略", "展示{entity}的库存策略记录",
        "帮我查询{entity}的库存策略", "请给出{entity}的库存策略信息", "我需要查看{entity}的库存策略内容"),
    ("semantic", "en"): (
        "Please read the inventory policy for {entity}", "Show the inventory policy stored at {entity}",
        "Retrieve the inventory policy of {entity}", "Please show the inventory policy for {entity}",
        "Give me the inventory policy recorded for {entity}", "I need the inventory policy of {entity}"),
    ("skill", "zh"): (
        "请读取{workflow}的操作步骤", "请查询{workflow}的操作步骤", "展示{workflow}的操作步骤记录",
        "帮我查询{workflow}的操作步骤", "请给出{workflow}的操作步骤信息", "我需要查看{workflow}的操作步骤内容"),
    ("skill", "en"): (
        "Please read the stored steps for {workflow}", "Show the stored procedure steps of {workflow}",
        "Retrieve the stored steps of {workflow}", "Please show the stored steps for {workflow}",
        "Give me the procedure steps recorded for {workflow}", "I need the stored steps of {workflow}"),
    ("compose", "zh"): (
        "请将{workflow}应用到{entity}并计算结果", "请用{workflow}计算{entity}的结果", "计算{workflow}在{entity}上的结果",
        "帮我用{workflow}计算{entity}的结果", "请给出{workflow}应用到{entity}后的计算结果", "我需要{workflow}在{entity}上的计算结果"),
    ("compose", "en"): (
        "Please apply {workflow} to {entity} and compute the result", "Calculate the result of {workflow} for {entity}",
        "Use {workflow} to calculate a result for {entity}", "Please calculate the result of {workflow} for {entity}",
        "Give me the result calculated with {workflow} at {entity}", "I need the computed result of {workflow} for {entity}"),
}
NEGATIVES = {
    ("mutation", "zh"): ("删除{entity}的库存记录", "请清除{entity}的全部库存记录", "把{entity}的库存资料删除"),
    ("mutation", "en"): ("Delete the inventory records at {entity}", "Erase every inventory record for {entity}", "Remove the stored inventory records at {entity}"),
    ("external", "zh"): ("将{entity}的库存发给外部用户", "把{entity}的库存发送到互联网", "向外部邮箱发送{entity}的库存信息"),
    ("external", "en"): ("Email the inventory of {entity} to an outside recipient", "Upload the inventory of {entity} to a public website", "Send the stock information of {entity} to an external mailbox"),
    ("prediction", "zh"): ("预测{entity}下周的库存", "猜测{entity}明天的库存变化", "预测{entity}未来的库存数量"),
    ("prediction", "en"): ("Predict next week's stock at {entity}", "Guess tomorrow's stock changes at {entity}", "Forecast future inventory quantities for {entity}"),
    ("negation", "zh"): ("不要读取{entity}的策略", "请勿查询{entity}的库存策略", "禁止查看{entity}的库存策略记录"),
    ("negation", "en"): ("Do not read the policy at {entity}", "Do not retrieve the inventory policy for {entity}", "Never show the stored inventory policy at {entity}"),
    ("other", "zh"): ("解释{entity}名称的由来", "介绍{entity}的地理位置", "写一首关于{entity}的诗"),
    ("other", "en"): ("Explain the origin of the name {entity}", "Describe the geographic location of {entity}", "Write a poem about the name {entity}"),
}


def normalized(text):
    return " ".join(text.split()).translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def source_pins():
    return {name: digest(Path(__file__).with_name(name).read_bytes()) for name in SOURCES}


def weight_digest(model):
    return digest({name + suffix: model[name + suffix] for name in ("intent", "shape") for suffix in ("_weights", "_bias")})


def corpus(model, baseline, replay=True):
    if model["schema"] != BOUNDED_SCHEMA:
        raise ValueError("requires the unchanged bounded v2 baseline")
    expanded = copy.deepcopy(model)
    declarations = [{"operation": {"semantic":"semantic", "skill":"procedure", "compose":"apply"}[role], "template": template}
                    for (role, _), templates in TEMPLATES.items() for template in templates]
    expanded["query_templates"].extend(declarations)
    if len(expanded["query_templates"]) > 64 or len({normalized(row["template"]) for row in expanded["query_templates"]}) != len(expanded["query_templates"]):
        raise ValueError("declared capability template bound or duplicate")
    names = {}
    for row in model["aliases"]:
        index = int(row["key"].split(":")[-1])
        for language in ("en", "zh"):
            selected = [phrase for phrase in row["phrases"] if phrase.isascii() == (language == "en")]
            if not selected:
                raise ValueError("existing bilingual alias required")
            names[(row["kind"], language, index)] = selected[0]
    if len(names) != 32:
        raise ValueError("complete existing eight-entity/eight-workflow aliases required")
    sets = {phase: [] for phase in ("train", "development", "held")}
    for (role, language), templates in TEMPLATES.items():
        for family, template in enumerate(templates):
            phase = "train" if family < 3 else "development" if family == 3 else "held"
            for index in range(8):
                workflow = (index + family + 1) % 8
                fields = {"entity": names[("entity", language, index)], "workflow": names[("workflow", language, workflow)]}
                row = {"id":f"bilingual:{phase}:{role}:{language}:{family}:{index}", "text":template.format(**fields),
                       "role":role, "intent":role, "language":language, "family":f"{phase}:{role}:{language}:{family}",
                       "entity":None if role == "skill" else index, "workflow":None if role == "semantic" else workflow}
                sets[phase].append(row)
                if phase != "train":
                    active = ("workflow",) if role == "skill" else ("entity",) if role == "semantic" else ("entity", "workflow")
                    bad = [template.format(**{**fields, kind:fields[kind] + ("外区" if language == "zh" else " outpost")}) for kind in active]
                    bad.append(row["text"] + ("，并删除全部记录" if language == "zh" else " and delete everything"))
                    for number, text in enumerate(bad):
                        sets[phase].append({**row, "id":row["id"] + f":boundary:{number}", "text":text,
                                           "role":"unknown", "intent":"reject:other", "family":"unknown-address-or-extra-capability",
                                           "entity":None, "workflow":None})
    for (category, language), templates in NEGATIVES.items():
        for phase, template in zip(sets, templates, strict=True):
            for index in range(8):
                sets[phase].append({"id":f"bilingual:{phase}:negative:{category}:{language}:{index}",
                    "text":template.format(entity=names[("entity", language, index)]), "role":"unknown",
                    "intent":"reject:" + category, "language":language, "family":f"{phase}:reject:{category}:{language}",
                    "entity":None, "workflow":None})
    historical = {normalized(row["text"]) for row in baseline}
    if any(normalized(row["text"]) in historical for phase in sets for row in sets[phase]):
        raise ValueError("new wording overlaps an observed historical query")
    replay_rows = [{**row, "id":"historical-replay:" + row["id"], "intent":row["role"], "family":"historical-known-replay"}
                   for row in baseline if row["role"] != "unknown"] if replay else []
    sets["train"].extend(replay_rows)
    seen = set()
    for phase, rows in sets.items():
        for row in rows:
            text = normalized(row["text"])
            if text in seen or bounded_address(row["text"], expanded["aliases"], expanded["query_templates"]) != gold(row):
                raise ValueError("split overlap or capability/gold mismatch: " + row["id"])
            seen.add(text)
    if {row["intent"] for row in sets["train"]} != set(INTENTS):
        raise ValueError("every original intent head class requires training rows")
    return expanded, sets, len(replay_rows)


def freeze(args):
    began, cpu = time.perf_counter(), time.process_time()
    preparation = json.loads((args.baseline_root / "prepared/PREPARE.json").read_bytes())
    raw_model = (args.baseline_root / "prepared/semantic-router.json").read_bytes()
    raw_queries = (args.baseline_root / "prepared/queries.json").read_bytes()
    if digest(raw_model) != preparation["model_sha256"] or digest(raw_queries) != preparation["queries_sha256"]:
        raise ValueError("historical baseline pins differ")
    baseline = json.loads(raw_queries)
    if len(baseline) != 480:
        raise ValueError("requires the retained 480-case baseline")
    expanded, sets, replay_count = corpus(json.loads(raw_model), baseline, not args.no_historical_replay)
    args.output.mkdir(parents=True, exist_ok=False)
    payloads = {phase + ".json": canonical(rows) for phase, rows in sets.items()}
    payloads["baseline-expanded.json"] = canonical(expanded)
    files = {}
    for name, payload in payloads.items():
        (args.output / name).write_bytes(payload)
        files[name] = {"sha256":digest(payload), "bytes":len(payload)}
    protocol = {"schema":SCHEMA, "files":files, "source_sha256":source_pins(),
        "baseline_model_sha256":digest(raw_model), "historical_queries_sha256":digest(raw_queries),
        "baseline_weights_sha256":weight_digest(expanded), "rows":{phase:len(rows) for phase, rows in sets.items()},
        "historical_known_replay_rows":replay_count, "historical_unknown_rows_used":0,
        "templates":len(expanded["query_templates"]), "template_families_disjoint":True,
        "held_normalized_text_disjoint_from_history_training_development":True,
        "fit":{"C":8.0, "max_iter":2000, "tol":1e-7, "seed":731, "threads":1, "cpu_budget_seconds":90, "wall_budget_seconds":240},
        "calibration":{"thresholds":[i / 20 for i in range(20)] + [.99, 1.01],
                       "margins":[0., .05, .1, .15, .2, .25, .3, .4, .5],
                       "selection":"zero unknown accepts and zero known wrong; maximize known correct, then threshold, then margin"},
        "comparison":{"cpu_budget_seconds":90, "wall_budget_seconds":240, "held_evaluations_per_model":1,
                      "known_accuracy_minimum":.95, "language_accuracy_minimum":.95, "operation_accuracy_minimum":.90,
                      "unknown_false_accept_maximum":0, "known_wrong_maximum":0},
        "authority":"candidate artifact only; existing native parity and actual owner gates remain required",
        "scope":"finite declared bilingual template-family continuation; capability templates are public, held features/labels never enter fit",
        "original_480_baseline_replaced":False, "original_model_weights_or_thresholds_changed":False,
        "freeze_cpu_seconds":time.process_time()-cpu, "freeze_wall_seconds":time.perf_counter()-began}
    raw = canonical(protocol); (args.output / "PROTOCOL.json").write_bytes(raw)
    print(json.dumps({"protocol_sha256":digest(raw), "rows":protocol["rows"], "templates":protocol["templates"],
                      "historical_known_replay_rows":replay_count, "output":str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-historical-replay", action="store_true")
    freeze(parser.parse_args())
