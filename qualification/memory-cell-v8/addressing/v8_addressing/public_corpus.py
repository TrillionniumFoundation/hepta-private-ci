"""Public training augmentation; original V7 selection remains separate."""

import re

from addressing.contracts import normalize
from addressing.corpus import corpora


POSITIVE = {
    "current": {
        "en": ("Give me the last observation stored for entity, with no processing.",
               "What raw value is currently on record for entity?",
               "Fetch the newest recorded sample belonging to entity.",
               "I need entity's most recent event value as it was written.",
               "Read the present observation of entity directly from memory.",
               "Return the latest measured number for entity; leave the recipe unused."),
        "zh": ("把entity最近一次记录的原始观测给我。", "entity目前留存的最新读数是什么？",
               "取出entity最后写入的事件数值，不进行加工。", "我只需要entity当前已记录的观测本身。",
               "读取entity现在保存着的最近一条测量值。", "请原样返回entity最新的数值，暂不调用流程。"),
    },
    "history": {
        "en": ("Recall entity's event value at the given past cutoff.",
               "What reading had been recorded for entity by date?",
               "Return the newest observation for entity that was already present at date.",
               "Look back to date and retrieve entity's recorded sample then.",
               "Read entity's last event no later than the supplied historical instant.",
               "Use the historical cutoff to find the stored observation of entity."),
        "zh": ("按给定的历史截止时刻回看entity的事件值。", "到date为止，entity当时保存的读数是多少？",
               "找出entity在date及之前最后出现的观测。", "回到date，读取entity那时记录的样本。",
               "请取entity不晚于所给历史时刻的最后一条事件。", "按历史截止点检索entity已保存的观测数值。"),
    },
    "semantic": {
        "en": ("Retrieve the stored semantic record for entity without applying it.",
               "What multiplier and label are saved as entity's attributes?",
               "Read entity's current coefficient entry itself.",
               "Show me the remembered property record belonging to entity.",
               "I need entity's saved factor, not a computed event result.",
               "Fetch the current semantic attributes associated with entity."),
        "zh": ("取出entity保存的语义属性记录，不应用它。", "entity的属性里存了什么系数和标签？",
               "读取entity当前系数条目本身。", "把entity记住的属性记录展示给我。",
               "需要的是entity保存的因子，不是计算后的事件结果。", "检索entity当前关联的语义属性。"),
    },
    "procedure": {
        "en": ("Retrieve the stored procedure for entity without running it.",
               "Which recipe is saved for entity? Return the program itself.",
               "Read the remembered instructions associated with entity.",
               "Show entity's current stored transformation steps, leaving them unexecuted.",
               "I need the saved program definition for entity.",
               "Fetch entity's procedure record instead of its output."),
        "zh": ("取出entity保存的流程，但不运行。", "entity存的是哪份配方？返回程序本身。",
               "读取entity关联的已记住的执行指令。", "展示entity当前保存的转换步骤，保持未执行。",
               "我需要entity的已存程序定义。", "检索entity的过程记录本身，不求输出值。"),
    },
    "change": {
        "en": ("Return entity's current observation minus its recorded value at date.",
               "How many units separate entity's latest value from its earlier cutoff value? Use latest minus earlier.",
               "Calculate the absolute-unit change of entity since date.",
               "Subtract entity's saved baseline observation from its latest observation.",
               "Use entity's earlier and current samples to report the signed increase in units.",
               "What is the latest-minus-historical difference for entity at the supplied baseline?"),
        "zh": ("返回entity当前观测减去date时的已存读数。", "entity最新值相对历史截止值变化了多少个单位？用最新减历史。",
               "计算entity自date以来按原单位计的变化。", "从entity最新观测中扣除已存的基准观测。",
               "用entity历史样本和当前样本报告带正负号的单位增量。", "按给定基准返回entity最新减历史的差值。"),
    },
    "apply": {
        "en": ("Run entity's saved procedure using its latest observation and stored attributes.",
               "Produce the output of entity's remembered recipe on the current recorded input.",
               "Apply the stored transformation for entity to its newest sample.",
               "Combine entity's present event, saved coefficient and procedure to calculate the result.",
               "Execute the program already remembered for entity with its current memory values.",
               "Return the computed result from entity's stored recipe and latest event."),
        "zh": ("用entity最新观测和已存属性运行保存的流程。", "用entity当前记录的输入求出已记住配方的输出。",
               "将entity已存的转换应用于最新样本。", "结合entity当前事件、已存系数和流程计算结果。",
               "把entity现有记忆值交给已经记住的程序执行。", "返回entity保存的配方处理最新事件得到的结果。"),
    },
}

NEGATIVE = {
    "arithmetic": {
        "en": ("Express entity's change as a fraction of its baseline.", "Give entity's relative increase in hundredths of the starting value.",
               "Normalize entity's latest reading by its earlier observation.", "Return the middle value among entity's past events."),
        "zh": ("把entity的变化写成相对于基准的份额。", "entity比起始值上涨了百分之几？",
               "用entity的较早观测归一化最新读数。", "返回entity历史事件中排在中间的那个数。"),
    },
    "explanation": {
        "en": ("Identify what drove entity's latest change.", "What mechanism accounts for entity's present reading?",
               "Tell me the reasons behind entity's recorded increase.", "Establish which factors are responsible for entity's event."),
        "zh": ("找出推动entity最近变化的因素。", "entity现在读数背后的机制是什么？",
               "说出entity已记录增量背后的缘由。", "确定哪些因素导致了entity的事件。"),
    },
    "counterfactual": {
        "en": ("Feed an artificial value of 33 into entity's stored recipe.", "Run entity's procedure on an input supplied by this message.",
               "Evaluate entity's program using a replacement observation of 7.", "Use a hypothetical factor of 2 for entity's current recipe."),
        "zh": ("给entity已存配方送入人为构造的数值33。", "用这条消息指定的输入执行entity的流程。",
               "用数值7代替观测来求entity程序的输出。", "让entity当前配方采用假想系数2。"),
    },
    "time_composition": {
        "en": ("Compare entity's two earlier readings, leaving the latest one unused.", "Use entity's previous coefficient version for the saved recipe.",
               "Recall the procedure entity used before its last revision.", "Compute entity's old observation less its newest one."),
        "zh": ("比较entity两次较早的读数，不使用最新读数。", "使用entity上一个系数版本运行已存配方。",
               "回忆entity最后一次修订之前的程序。", "计算entity旧观测减去最新观测。"),
    },
}


def public_rows():
    original = corpora()
    def transport_text(value):
        value = re.sub(r"(?<![a-z])(?:entity|date)(?![a-z])", lambda match: " " + match.group() + " ", normalize(value))
        return " ".join(value.split())

    rows = {name: [{**row, "text": transport_text(row["text"])} for row in original[name]]
            for name in ("train", "selection")}
    seen = {normalize(row["text"]) for values in rows.values() for row in values}
    if len(seen) != sum(len(values) for values in rows.values()):
        raise ValueError("transport normalization collapses distinct public partitions")
    for group, definitions in (("supported", POSITIVE), ("unsupported", NEGATIVE)):
        for label, languages in definitions.items():
            for language, phrases in languages.items():
                for index, phrase in enumerate(phrases):
                    phrase = transport_text(phrase)
                    if normalize(phrase) in seen:
                        raise ValueError("public augmentation overlaps the preserved corpus")
                    seen.add(normalize(phrase))
                    row = {"id": f"v8-public-{group}-{label}-{language}-{index}",
                           "family": f"v8.public.{group}.{label}.{index}", "language": language,
                           "operation": label if group == "supported" else "reject", "text": phrase,
                           "provenance": "public V8 development augmentation; never independent evaluation"}
                    if group == "unsupported":
                        row["negative_group"] = label
                    rows["train"].append(row)
    return rows
