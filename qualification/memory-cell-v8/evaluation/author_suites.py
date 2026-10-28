"""Create-once author-separated native fixtures; never imported by model fitting.

These are constructed task families, not IID population samples or external
third-party evaluation. Repeated wrappers share a family and are reported so.
The V8 fitting author must not inspect this module or its generated inputs.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OPERATIONS = ("current", "history", "semantic", "procedure", "change", "apply")

CALIBRATION = {
    "current": (
        ["Show the newest raw observation kept for {entity}.", "What value did {entity} record most recently?",
         "I need {entity}'s last measurement, before any stored recipe is applied.",
         "Look up the current entry in {entity}'s observation log.", "Return the latest event value available for {entity}."],
        ["取出{entity}最近一次保存的原始观测。", "{entity}最后记录的数值是多少？",
         "请查{entity}的最新读数，暂时不要执行保存的程序。", "我要{entity}观测日志中当前最后一条的值。", "返回{entity}最近的事件值。"]),
    "history": (
        ["What reading had been recorded for {entity} by {date}?", "Find {entity}'s last observation no later than {date}.",
         "Look back to {date} and retrieve the reading then on file for {entity}.",
         "As of {date}, what was the most recent raw value of {entity}?", "Use the {date} cutoff to recover {entity}'s archived observation."],
        ["截至{date}，{entity}保存的最后一个读数是多少？", "找出{entity}不晚于{date}的最近观测。",
         "回到{date}这个截止点，取当时档案里的{entity}读数。", "请查{entity}在{date}时已存的原始数值。", "按{date}截断历史记录，返回{entity}的末条观测。"]),
    "semantic": (
        ["Which semantic multiplier is stored for {entity}?", "Retrieve {entity}'s saved semantic parameters without computing a result.",
         "Show the remembered coefficient and label belonging to {entity}.",
         "Read {entity}'s semantic entry itself.", "I want the stored factor of {entity}, not a transformed observation."],
        ["{entity}保存的语义乘数是什么？", "调出{entity}的语义参数，先不计算结果。",
         "显示{entity}记住的系数和标签。", "读取{entity}的语义记录本身。", "请给出{entity}已存的因子，不要变换观测值。"]),
    "procedure": (
        ["Retrieve the saved procedure for {entity} without running it.", "Which sequence of stored instructions belongs to {entity}?",
         "Show {entity}'s remembered calculation recipe itself.",
         "Inspect the operation, bias and limit kept in {entity}'s program.", "Tell me the stored steps for processing {entity}, leaving them unexecuted."],
        ["取出{entity}保存的过程，但不要运行。", "{entity}记住的步骤是什么？",
         "显示{entity}的计算配方本身。", "查看{entity}程序中保存的操作、偏置和限值。", "给我{entity}已存的处理步骤，暂不执行。"]),
    "change": (
        ["Subtract {entity}'s reading at {date} from its latest reading.", "How much has {entity}'s raw value changed since {date}, in the original units?",
         "Return current minus the observation of {entity} on file by {date}.",
         "Calculate the signed difference between {entity}'s latest value and its {date} baseline.", "Compare {entity} now with {date} by subtraction only."],
        ["用{entity}最新读数减去{date}时已存的读数。", "从{date}至今，{entity}原始值增加或减少了多少，保留原单位？",
         "返回{entity}当前值减去截至{date}的观测值。", "计算{entity}最新值相对{date}基线的有符号差额。", "把{entity}现在与{date}的数值做减法比较。"]),
    "apply": (
        ["Execute {entity}'s stored procedure on its latest observation using the saved semantic parameters.",
         "Run the remembered recipe for {entity} and return its output on the current recorded value.",
         "Combine {entity}'s newest event, semantic factor and procedure to compute the result.",
         "Process {entity}'s latest sample with the procedure already stored for it.", "Use the saved parameters and saved program to transform {entity}'s latest observation."],
        ["把{entity}最新观测送入已存过程，并使用已存语义参数。", "执行{entity}记住的配方，给出当前记录值对应的输出。",
         "组合{entity}的最新事件、语义因子和过程，算出结果。", "使用{entity}已有的过程处理最新样本。", "用保存的参数和程序变换{entity}最新的观测。"]),
}

HELD = {
    "current": (
        ["For {entity}, fetch the observation at the tail of the record.", "Report the freshest unmodified sample of {entity} that you have kept.",
         "What number is in the newest raw entry for {entity}?", "Open {entity}'s measurement history and give me only its final recorded value.",
         "The handover needs the last logged observation of {entity}, before processing."],
        ["请读出{entity}记录末尾那次观测的值。", "交班表需要{entity}保留的最新未加工样本。",
         "{entity}原始记录中最新一项填了什么数？", "打开{entity}的测量历史，只给我最后记下的值。", "我要{entity}最近落档的观测，不做程序运算。"]),
    "history": (
        ["Recover the last entry for {entity} that existed when the clock reached {date}.",
         "The audit stops at {date}; which raw observation of {entity} was then the newest?",
         "Ignore observations after {date} and report the remaining latest value for {entity}.",
         "Read {entity} from the historical record truncated at {date}.", "On the {date} reporting boundary, what recorded reading was available for {entity}?"],
        ["时钟到达{date}时，{entity}已有记录的末项是多少？", "审计截在{date}，当时{entity}最新的原始观测是什么？",
         "忽略{date}之后的观测，返回{entity}剩余记录中的最新值。", "将{entity}历史截到{date}，读出当时最后的值。", "在{date}这个报表边界，{entity}已有的读数是多少？"]),
    "semantic": (
        ["Which factor-and-label pair have you retained for {entity}?", "Return the semantic information assigned to {entity}, as stored.",
         "I am checking {entity}'s remembered coefficient, with no calculation requested.",
         "Fetch the semantic settings on file for {entity}.", "Expose the stored multiplier metadata of {entity} by itself."],
        ["{entity}保留下来的因子与标签这一对是什么？", "原样返回分配给{entity}的语义信息。",
         "我在核对{entity}记住的系数，不要求计算。", "调出{entity}档案里的语义设置。", "单独显示{entity}保存的乘数元数据。"]),
    "procedure": (
        ["What operation recipe is currently remembered for {entity}? Leave it idle.",
         "Read back {entity}'s instruction record, including its bias and bound.",
         "I need the program definition saved for {entity}, rather than an execution result.",
         "List the recipe already attached to {entity}; do not evaluate a sample.", "Retrieve the dormant processing instructions of {entity}."],
        ["目前给{entity}记住了什么操作配方？先让它保持未运行。", "读回{entity}的指令记录，包括偏置和界限。",
         "我要{entity}保存的程序定义，不要求执行结果。", "列出附在{entity}上的现有配方，先不计算样本。", "取回{entity}尚未执行的处理指令。"]),
    "change": (
        ["Take the newest number for {entity} and deduct the number on record by {date}.",
         "Give the additive displacement of {entity} from the {date} reading to the newest reading.",
         "For {entity}, report a signed raw-unit delta against the record as of {date}.",
         "The reconciliation is latest less the archived {date} value of {entity}; return that number.",
         "How many units separate {entity}'s newest observation from its {date} baseline, keeping the sign?"],
        ["取{entity}最新的数，扣除截至{date}记下的那个数。", "给出{entity}从{date}读数到最新读数的加法位移。",
         "对{entity}，报告相对{date}记录的带符号原单位差值。", "核对式是{entity}最新值扣掉{date}档案值，请返回这个数。", "{entity}最新观测与{date}基线相隔多少个单位？保留正负号。"]),
    "apply": (
        ["Evaluate the recipe on file for {entity} against its newest recorded input, with its retained parameters.",
         "Produce the processed output for {entity} from the three stored pieces: observation, semantics and instructions.",
         "Carry out the remembered computation for {entity} using the most recent observation already in memory.",
         "Feed the last logged sample of {entity} through its own saved transformation.",
         "Resolve {entity}'s saved program with its current recorded event and semantic settings, then give the result."],
        ["用{entity}保留的参数，对最新已记输入求值档案中的配方。", "用{entity}存下的观测、语义和指令这三部分产生处理输出。",
         "使用记忆里最近的观测，完成{entity}记住的计算。", "让{entity}最后落档的样本通过它自己的已存变换。", "把{entity}当前已记事件和语义设置代入保存的程序，给出结果。"]),
}

CALIBRATION_REJECT = (
    ["What percentage did {entity} change since {date}?", "Divide {entity}'s current reading by its {date} reading.",
     "Explain why {entity} changed since {date}.", "Forecast the next observation of {entity}.",
     "Run {entity}'s program on a hypothetical input of 33.", "What is the square of {entity}'s stored factor?",
     "Replace the saved procedure of {entity} with a new one.", "Average all readings of {entity} since {date}.",
     "Recover the semantic parameters {entity} had on {date}.", "Calculate {entity}'s change between two past dates, {date} and 2025-05-01.",
     "Show the maximum historical observation of {entity}.", "How often has {entity}'s procedure run?",
     "Convert the latest reading of {entity} to another unit.", "Give a confidence interval for the next value of {entity}.",
     "Merge every stored event of {entity} into a prose account.", "Return the reciprocal of {entity}'s factor.",
     "Compare {entity}'s program with a program that was never saved.", "Delete the oldest event of {entity}.",
     "Tell me who caused the last change in {entity}.", "Simulate {entity}'s recipe repeatedly for ten steps."],
    ["{entity}自{date}以来变化了百分之几？", "把{entity}当前读数除以{date}读数。", "解释{entity}自{date}以来变化的原因。",
     "预测{entity}下一次观测。", "用虚构输入33运行{entity}的程序。", "{entity}保存的因子的平方是多少？",
     "将{entity}的已存过程替换成新的。", "求{entity}从{date}以来全部读数的平均值。", "找回{entity}在{date}使用的历史语义参数。",
     "计算{entity}在两个过去日期{date}和2025-05-01之间的变化。", "给出{entity}历史观测的最大值。", "{entity}的过程执行过多少次？",
     "将{entity}最新读数换算为另一种单位。", "给出{entity}下一次值的置信区间。", "把{entity}的全部事件合成一段文字叙事。",
     "返回{entity}因子的倒数。", "把{entity}程序与从未保存的另一程序比较。", "删除{entity}最早的事件。", "谁导致了{entity}最后的变化？",
     "模拟{entity}的配方，连续迭代十步。"])

HELD_REJECT = (
    ["Express {entity}'s latest-versus-{date} difference as a fraction of the old reading.",
     "How many times the {date} baseline is the newest value of {entity}?", "Identify the drivers behind {entity}'s latest increase.",
     "Estimate what {entity} will read tomorrow.", "For {entity}, retain the saved recipe but substitute an invented sample of 81.",
     "Cube the semantic coefficient kept for {entity}.", "Edit the bias inside {entity}'s stored program.",
     "Sum every observation of {entity} recorded after {date}.", "Which procedure version belonged to {entity} at {date}?",
     "Subtract {entity}'s 2025-01-01 record from its {date} record, without using the current value.",
     "Rank all historical values of {entity} from largest to smallest.", "Count the saved events of {entity}.",
     "Normalize the latest observation of {entity} by the historical standard deviation.",
     "What probability does {entity} have of crossing 50 next week?", "Compose a causal narrative of {entity}'s full history.",
     "Take the logarithm of the factor stored for {entity}.", "Invent a better algorithm to replace {entity}'s recipe.",
     "Undo the most recent write to {entity}.", "Determine whether a hardware fault explains {entity}'s change since {date}.",
     "Apply {entity}'s procedure twice, using its own first output as the second input."],
    ["将{entity}最新值相对{date}的差额表示为旧值的比例。", "{entity}最新值是{date}基线的多少倍？", "查明{entity}最近上涨的驱动因素。",
     "估计{entity}明天会读到什么数。", "保留{entity}的配方，但将输入换成虚构样本81。", "对{entity}保存的语义系数求立方。",
     "修改{entity}已存程序里的偏置。", "将{entity}在{date}之后的所有观测相加。", "{entity}在{date}对应哪个历史过程版本？",
     "用{entity}的{date}记录减去2025-01-01记录，不使用当前值。", "把{entity}全部历史值从大到小排序。", "数一数{entity}保存了几个事件。",
     "用历史标准差归一化{entity}的最新观测。", "{entity}下周超过50的概率是多少？", "为{entity}完整历史写出因果叙事。",
     "对{entity}已存因子取对数。", "发明更好的算法来替代{entity}的配方。", "撤销{entity}最近一次写入。", "判断{entity}自{date}的变化是否由硬件故障造成。",
     "运行{entity}过程两次，将第一次输出作为第二次输入。"])


def unix(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def entities(split):
    pairs = ([("Cedar gauge", "雪松计"), ("Harbor valve", "港湾阀"), ("Quartz meter", "石英表"), ("Delta probe", "三角探头"),
              ("Willow pump", "柳叶泵"), ("Maple sensor", "枫木传感器")]
             if split == "calibration" else
             [("Aurora gauge", "极光计"), ("Lotus valve", "莲花阀"), ("Basalt meter", "玄武表"), ("Cobalt probe", "钴蓝探头"),
              ("Tundra pump", "冻原泵"), ("Saffron sensor", "藏红传感器")])
    out = []
    for i in range(12):
        en, zh = pairs[i % len(pairs)]
        aliases = [f"{en} {i + 1}", f"{zh}{i + 1}号"]
        if i < 2:
            aliases += ["Shared station", "共用站"]
        records = [{"kind": "event", "effective_at": unix(day), "value": value + i}
                   for day, value in [("2024-10-01", 4), ("2025-02-01", 12), ("2025-07-01", 30)]]
        records += [{"kind": "semantic", "effective_at": unix("2025-02-01"), "value": {"factor": 2 + i % 3, "label": f"{split}-owner-value-{i}"}},
                    {"kind": "procedure", "effective_at": unix("2025-02-01"), "value": {"opcode": ["identity", "add_bias", "multiply", "affine", "clamp"][i % 5], "bias": i - 5, "limit": 25 + i}}]
        out.append({"entity": f"meter:v8-{split}-{i:02d}", "aliases": aliases, "records": records})
    return out


def suite(split):
    owners = entities(split)
    source = CALIBRATION if split == "calibration" else HELD
    rejects = CALIBRATION_REJECT if split == "calibration" else HELD_REJECT
    date = "2025-02-01" if split == "calibration" else "2025-04-01"
    now, cutoff = unix("2025-07-02"), unix(date)
    rows = []

    def append(family, language, entity, text, operation, category, at=None, since=None):
        rows.append({"id": f"{split}-{len(rows):04d}", "family": family, "language": language,
                     "entity": entity, "text": text, "at": now if at is None else at,
                     "since": cutoff if since is None else since, "expected_operation": operation, "category": category})

    for op_index, operation in enumerate(OPERATIONS):
        for lang_index, language in enumerate(("en", "zh")):
            for template_index, template in enumerate(source[operation][lang_index]):
                for variant in range(2):
                    item = owners[(op_index + template_index + 5 * variant) % len(owners)]
                    text = template.format(entity=item["aliases"][lang_index], date=date)
                    if variant:
                        text = ("For the inspection record: " if language == "en" else "用于检查记录：") + text
                    append(f"{split}.known.{operation}.{language}.{template_index}", language, item["entity"], text,
                           operation, "known", cutoff if operation == "history" else now)
    for lang_index, language in enumerate(("en", "zh")):
        for template_index, template in enumerate(rejects[lang_index]):
            for variant in range(2):
                item = owners[(template_index + 3 * variant) % len(owners)]
                append(f"{split}.unsupported.{language}.{template_index}", language, item["entity"],
                       template.format(entity=item["aliases"][lang_index], date=date), None, "unsupported")
        for i in range(8):
            unknown = f"Unregistered unit {i}" if language == "en" else f"未登记单元{i}"
            text = source["current"][lang_index][i % 5].format(entity=unknown, date=date)
            append(f"{split}.unknown.{language}.{i}", language, f"meter:v8-unknown-{split}-{i}", text, None, "unknown_entity")
        for i in range(6):
            text = source["current"][lang_index][i % 5].format(entity="Shared station" if language == "en" else "共用站", date=date)
            append(f"{split}.ambiguous.{language}.{i}", language, owners[i % 2]["entity"], text, None, "ambiguous_alias")
        for i in range(6):
            item = owners[i]
            operation = "history" if i % 2 == 0 else "change"
            text = source[operation][lang_index][i % 5].format(entity=item["aliases"][lang_index], date=date)
            wrong = cutoff + (3600 if i < 2 else 86400 if i < 4 else -86400)
            append(f"{split}.time-conflict.{language}.{i}", language, item["entity"], text, None, "time_conflict",
                   wrong if operation == "history" else now, min(wrong, cutoff) if operation == "history" else wrong)
    return {"schema": "hepta.memory.v8.language-suite.v1", "split": split, "entities": owners, "rows": rows}


def main():
    inputs = ROOT / "inputs"
    inputs.mkdir(exist_ok=True)
    manifest = {"schema": "hepta.memory.v8.author-suite-lock.v1", "author": "root evaluator, separate from addressing implementer",
                "fitting_author_allowed_to_read_before_model_selection": False, "external_third_party": False,
                "iid_sampling_established": False, "wrapper_variants_share_family": True,
                "expected_fields_sent_to_worker": False, "native_cell_budget": 8, "native_hop_budget": 8,
                "author_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "files": {}}
    for split in ("calibration", "held"):
        value = suite(split)
        raw = encoded(value)
        path = inputs / f"{split}.json"
        with path.open("xb") as stream:
            stream.write(raw)
        counts = {category: sum(row["category"] == category for row in value["rows"])
                  for category in sorted({row["category"] for row in value["rows"]})}
        manifest["files"][path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                       "rows": len(value["rows"]), "categories": counts,
                                       "families": len({row["family"] for row in value["rows"]}), "entities": len(value["entities"])}
    with (ROOT / "INPUT_LOCK.json").open("xb") as stream:
        stream.write(encoded(manifest))
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
