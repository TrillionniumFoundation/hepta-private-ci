"""Independently authored V6 language evaluation; never a training corpus.

Authored by a separate assistant before model selection. These are synthetic
requests, not independent human observations. Related English/Chinese phrasing
shares a family, so repeated entities, seeds and domains add no language samples.
"""

import hashlib
import json
from pathlib import Path


KNOWN = {
    "current": {
        "families": [
            "latest_record",
            "present_view",
            "recent_observation",
            "head_event",
        ],
        "en": [
            "For {entity}, give me the newest value that actually reached the event log.",
            "Which value is recorded most recently for {entity}?",
            "I need the latest recorded value for {entity}, without a forecast.",
            "Show the value from the most up-to-date event belonging to {entity}.",
            "What value does the present snapshot hold for {entity}?",
            "Read {entity}'s event value in the current view.",
            "Using the active memory snapshot, what is {entity}'s value now?",
            "Tell me the value currently on record for {entity}.",
            "Retrieve the most recent observation value attached to {entity}.",
            "What was the last value observed for {entity}?",
            "Look up {entity}'s freshest observation and return its value.",
            "Of the observations already received for {entity}, return the last one's value.",
            "Read the value at the head of {entity}'s event history.",
            "Give the value in {entity}'s latest event entry.",
            "Follow {entity}'s record history to its newest entry; what value is there?",
            "Take the final recorded event for {entity} and report the value it contains.",
        ],
        "zh": [
            "请读出{entity}已经入账的最新事件值。",
            "{entity}最近一条记录的数值是什么？",
            "我需要{entity}最新保存的值，不需要预测。",
            "查看{entity}最后更新的事件记录，告诉我其中的值。",
            "当前快照里，{entity}的事件值是多少？",
            "按现在有效的记忆版本读取{entity}的值。",
            "{entity}目前记载的数值是什么？",
            "请给出当前视图下{entity}的记录值。",
            "找出{entity}最近一次观测的结果值。",
            "最后一次观测到的{entity}数值是多少？",
            "把{entity}最新收到的观测值取出来。",
            "已经收到的{entity}观测中，最后那条的值是什么？",
            "沿着{entity}的事件历史，读最末条记录的值。",
            "请返回{entity}事件链顶端记录中的数值。",
            "{entity}最新事件条目里写的值是什么？",
            "取{entity}最后入库的事件，只报告它的值。",
        ],
    },
    "history": {
        "families": ["cutoff_lookup", "historical_state", "last_before", "rewind"],
        "en": [
            "As of {at}, what event value was recorded for {entity}?",
            "Give {entity}'s value at the supplied cutoff {at}.",
            "Read the value for {entity} that was effective by {at}.",
            "With {at} as the latest allowed time, what value does {entity}'s history show?",
            "What value would the historical view of {entity} show at {at}?",
            "Open {entity}'s state as it stood at {at} and return its event value.",
            "I need {entity}'s recorded value back at {at}, rather than the current one.",
            "Recover the event value that belonged to {entity}'s {at} snapshot.",
            "Find the last observation of {entity} no later than {at}; what was its value?",
            "Return {entity}'s most recent event value at or before {at}.",
            "Ignore entries later than {at} and read the remaining latest value for {entity}.",
            "Among {entity}'s events up to and including {at}, give the newest value.",
            "Rewind {entity}'s event history to {at} and read its value there.",
            "Roll the lookup back to {at} for {entity}; which value was in effect?",
            "Look backward to {at}, then tell me the value recorded for {entity}.",
            "Use the supplied historical time {at} to retrieve {entity}'s event value.",
        ],
        "zh": [
            "截至{at}，{entity}当时记录的值是多少？",
            "以{at}为截止时间读取{entity}的事件值。",
            "请给出{entity}在{at}时已经生效的记录值。",
            "只考虑不晚于{at}的记录，{entity}的值是什么？",
            "{entity}在{at}的历史视图会显示哪个值？",
            "打开{entity}于{at}时的状态，读出事件值。",
            "我要查{entity}在{at}当时的值，而非当前值。",
            "请恢复{entity}截至{at}的快照所记录的数值。",
            "找{entity}在{at}及以前最后一条观测，返回其值。",
            "{entity}不晚于{at}的最新事件值是什么？",
            "排除{at}之后的条目，再取{entity}剩余记录中的最新值。",
            "在截至{at}的事件中，{entity}最后保存了什么值？",
            "把{entity}的事件历史回溯到{at}，读出当时的值。",
            "将查询时间退回{at}，{entity}那时生效的值是多少？",
            "请往回查到{at}，告诉我当时{entity}记录的数值。",
            "按照给定的历史时点{at}检索{entity}的事件值。",
        ],
    },
    "semantic": {
        "families": [
            "attribute_lookup",
            "stored_description",
            "persistent_property",
            "profile_fact",
        ],
        "en": [
            "Which stable attribute has memory stored for {entity}?",
            "Retrieve the remembered semantic property of {entity}.",
            "What attribute is associated with {entity} in semantic memory?",
            "Read the stored property for {entity}, rather than an event measurement.",
            "What enduring descriptor was saved about {entity}?",
            "Tell me the retained semantic description assigned to {entity}.",
            "Look up the remembered defining property of {entity}.",
            "Give the semantic fact saved in {entity}'s description.",
            "What persistent property does the memory associate with {entity}?",
            "I need {entity}'s learned stable attribute, not its latest observation.",
            "Read back the long-lived property that was stored for {entity}.",
            "Which fixed semantic attribute is attached to {entity}?",
            "Consult {entity}'s semantic profile and return its property.",
            "What fact was retained in the profile of {entity}?",
            "Return the property recorded in {entity}'s semantic entry.",
            "From the stored entity profile, identify {entity}'s attribute.",
        ],
        "zh": [
            "记忆里为{entity}保存了什么稳定属性？",
            "请检索{entity}已记住的语义属性。",
            "语义记忆把哪个属性与{entity}关联起来？",
            "读取{entity}保存的属性，不要返回事件测量值。",
            "关于{entity}，保存下来的长期描述是什么？",
            "告诉我为{entity}保留的语义描述。",
            "查一下{entity}记忆中的定义性属性。",
            "{entity}的描述中保存了哪个语义事实？",
            "记忆把{entity}与什么持久属性联系起来？",
            "我需要{entity}的稳定属性，而非最新观测。",
            "读回之前为{entity}保存的长期属性。",
            "{entity}附带的固定语义属性是什么？",
            "查看{entity}的语义档案，返回其中的属性。",
            "{entity}的档案保留了什么属性事实？",
            "请给出{entity}语义条目记载的属性。",
            "从实体档案中找出{entity}保存的属性。",
        ],
    },
    "procedure": {
        "families": [
            "steps_lookup",
            "recipe_description",
            "workflow_recall",
            "method_specification",
        ],
        "en": [
            "Which saved steps belong to {entity}'s procedure?",
            "Read out the stored instructions for processing {entity}.",
            "What sequence of operations has been remembered for {entity}?",
            "Retrieve {entity}'s saved procedure without executing it.",
            "Show the recipe already stored for {entity}.",
            "What does {entity}'s retained processing recipe say to do?",
            "Describe the saved recipe associated with {entity}.",
            "Give me the procedure that memory keeps for {entity}.",
            "Recall the stored workflow for {entity}.",
            "Which workflow was saved as the one to use for {entity}?",
            "Look up the remembered operation sequence assigned to {entity}.",
            "List the steps of {entity}'s existing workflow from memory.",
            "Return the stored method specification for {entity}.",
            "Which processing method is recorded for {entity}?",
            "I want the saved program for {entity}, not the result of running it.",
            "Inspect the procedural entry for {entity} and report its instructions.",
        ],
        "zh": [
            "{entity}保存的过程包括哪些步骤？",
            "请读出处理{entity}的已有操作说明。",
            "记忆为{entity}保留了什么操作顺序？",
            "检索{entity}已经保存的过程，暂时不要执行。",
            "显示已经为{entity}存下来的处理配方。",
            "{entity}保留的处理配方规定怎样操作？",
            "描述与{entity}关联的已存配方。",
            "把记忆中{entity}的过程内容给我。",
            "回忆一下{entity}保存的工作流程。",
            "之前为{entity}记录的是哪套流程？",
            "查出分配给{entity}的已记住操作序列。",
            "按记忆列出{entity}现有工作流程的步骤。",
            "返回{entity}已经存储的方法说明。",
            "{entity}记载的处理方法是什么？",
            "我要{entity}保存的程序内容，不是运行后的结果。",
            "查看{entity}的过程条目，报告其中的操作指令。",
        ],
    },
    "change": {
        "families": [
            "signed_difference",
            "baseline_delta",
            "current_minus_prior",
            "net_movement",
        ],
        "en": [
            "What is the signed difference between {entity}'s latest value and its value as of {since}?",
            "Subtract {entity}'s value at {since} from its newest recorded value.",
            "Give the current-minus-{since} difference for {entity}.",
            "How much higher or lower is {entity}'s current value than its value at {since}?",
            "Use {since} as the baseline and report {entity}'s signed numeric delta to the latest entry.",
            "Relative to the recorded value at {since}, what signed change has {entity} reached now?",
            "Compare the latest value of {entity} with its baseline at {since}; return the difference in original units.",
            "Compute {entity}'s latest value less its recorded baseline at {since}.",
            "For {entity}, what does today's stored value minus the value effective at {since} equal?",
            "Take the newest event value of {entity} and deduct the one effective at {since}.",
            "Read {entity} now and at {since}, then return now minus then.",
            "Calculate the subtraction of {entity}'s historical {since} value from its present value.",
            "What net increase or decrease has {entity}'s recorded value had since {since}?",
            "Report the signed movement from {entity}'s {since} value to its latest value.",
            "In the value's own units, what signed movement has {entity} made from {since} to the newest record?",
            "Find {entity}'s change since {since}, preserving the sign and avoiding a percentage conversion.",
        ],
        "zh": [
            "{entity}最新值减去截至{since}的值，带符号的差是多少？",
            "从{entity}最新记录值中减去{since}时的值。",
            "给出{entity}当前值与{since}历史值之差，按当前减历史计算。",
            "{entity}当前值比{since}时高或低多少？",
            "以{since}为基准，计算{entity}到最新条目的原单位数值变化。",
            "相对{since}的记录值，{entity}现在的带符号变化是多少？",
            "比较{entity}最新值与{since}的基准值，返回原单位的差。",
            "计算{entity}最新值扣除{since}记录基准后的结果。",
            "{entity}现在保存的值减去{since}时有效的值等于多少？",
            "取{entity}最新事件值，再扣掉{since}时生效的值。",
            "读取{entity}现在和{since}的值，然后返回现在减当时。",
            "请从{entity}当前值里减去其{since}历史值。",
            "自{since}以来，{entity}的记录值净增加或净减少了多少？",
            "报告{entity}从{since}值到最新值的带符号变动。",
            "按数值原有单位，{entity}从{since}到最近记录变化了多少？",
            "求{entity}自{since}以来的变化，保留正负号，不换算百分比。",
        ],
    },
    "apply": {
        "families": [
            "execute_saved",
            "evaluate_recipe",
            "process_measurement",
            "combine_three_memories",
        ],
        "en": [
            "Run {entity}'s saved procedure on its latest event value with its remembered semantic parameter.",
            "Use the stored method for {entity} to process its current value and saved property, then return the result.",
            "Execute the remembered processing steps for {entity} using the newest observation and stored attribute.",
            "Apply {entity}'s existing program to the latest recorded value with the parameter from its semantic entry.",
            "Evaluate the recipe already saved for {entity}, taking its current event and remembered property as inputs.",
            "What result does {entity}'s stored recipe produce from its newest value and saved semantic parameter?",
            "Feed {entity}'s latest measurement and retained attribute into its saved recipe; report the output.",
            "Calculate the outcome of the remembered recipe for {entity} using its current recorded inputs.",
            "Process {entity}'s newest observation according to its stored procedure and semantic property.",
            "Transform the latest value of {entity} using the method and parameter already in memory.",
            "Take {entity}'s current measurement through its saved operation sequence with its remembered property.",
            "Return the processed value for {entity} after running its recorded method on the latest event and saved parameter.",
            "Combine {entity}'s latest event, stored semantic parameter and remembered procedure to produce the procedure's output.",
            "Read all three memories for {entity} and execute the saved procedure with the current value and semantic input.",
            "Using {entity}'s event value, semantic property and procedure from memory, compute the stored procedure's result.",
            "Retrieve {entity}'s current value and remembered parameter, pass both to its saved program, and give its output.",
        ],
        "zh": [
            "用{entity}记住的语义参数，把保存的过程运行在最新事件值上。",
            "按{entity}已存方法处理当前值和保存的属性，返回结果。",
            "对{entity}最新观测执行记住的处理步骤，并使用已存属性。",
            "将{entity}现有程序作用于最新记录值，参数取自它的语义条目。",
            "求{entity}已存配方的结果，输入使用当前事件值和记住的属性。",
            "{entity}保存的配方接收最新值及语义参数后会输出什么？",
            "把{entity}最新测量和保留属性送入已存配方，报告输出。",
            "使用{entity}当前已记录输入，计算记住的配方的执行结果。",
            "依照{entity}保存的过程和语义属性处理最新观测。",
            "用记忆中已有的方法和参数转换{entity}的最新值。",
            "让{entity}当前测量值经过保存的操作序列，并使用记住的属性。",
            "在最新事件值和已存参数上运行{entity}的记录方法，返回处理结果。",
            "组合{entity}的最新事件、语义参数和过程记忆，给出该过程的输出。",
            "读取{entity}的三类记忆，以当前值和语义输入执行已存过程。",
            "利用{entity}记忆中的事件值、语义属性与过程，计算既存过程的结果。",
            "取出{entity}当前值和已记住参数，将二者传给保存的程序，告诉我输出。",
        ],
    },
}


UNSUPPORTED = {
    "forecast": {
        "en": [
            "Predict the next event value for {entity}.",
            "What value will {entity} probably have next week?",
            "Extrapolate {entity}'s recorded observations into the future.",
            "Forecast {entity}'s next ten values using its event history.",
        ],
        "zh": [
            "预测{entity}下一次事件的值。",
            "{entity}下周大概会是多少？",
            "根据历史观测外推{entity}未来的数值。",
            "利用事件历史预报{entity}接下来十个值。",
        ],
    },
    "causal_attribution": {
        "en": [
            "What caused {entity}'s latest value to change?",
            "Explain why {entity} had the recorded value at {at}.",
            "Which hidden factor is responsible for {entity}'s current observation?",
            "Did the saved procedure cause the last observed change in {entity}?",
        ],
        "zh": [
            "是什么原因造成{entity}最新值变化？",
            "解释{entity}为何在{at}出现那个记录值。",
            "{entity}当前观测是由哪个隐藏因素引起的？",
            "保存的过程是否导致了{entity}上次观测变化？",
        ],
    },
    "unsupported_statistics": {
        "en": [
            "Find the median of every recorded value for {entity}.",
            "Compute the variance of {entity}'s event values over its entire history.",
            "Return the ninety-fifth percentile of {entity}'s recorded measurements.",
            "Smooth {entity}'s value history with a seven-observation moving average.",
        ],
        "zh": [
            "求{entity}全部记录值的中位数。",
            "计算{entity}整个事件历史的数值方差。",
            "返回{entity}历史测量的第九十五百分位数。",
            "用七次观测的移动平均平滑{entity}的历史值。",
        ],
    },
    "new_arithmetic": {
        "en": [
            "Take the square root of {entity}'s latest value, regardless of its saved program.",
            "Report the logarithm of {entity}'s current observation.",
            "Convert {entity}'s change since {since} into a percentage of its baseline.",
            "Raise {entity}'s current value to the power of its remembered parameter.",
        ],
        "zh": [
            "不管已有程序，直接计算{entity}最新值的平方根。",
            "报告{entity}当前观测值的对数。",
            "将{entity}自{since}以来的变化换算成相对基准的百分比。",
            "以{entity}记住的参数为指数，求当前值的幂。",
        ],
    },
    "historical_pair": {
        "en": [
            "Subtract {entity}'s value at {since} from its value at {at}, excluding the current value.",
            "Compare the two historical snapshots {since} and {at} for {entity} and return their difference.",
            "How much did {entity} change between {since} and {at}, before the latest observation?",
            "Find the signed movement between {entity}'s two supplied historical times, not from history to now.",
        ],
        "zh": [
            "用{entity}在{at}的值减去{since}的值，不使用当前值。",
            "比较{entity}在{since}与{at}两个历史快照，返回差值。",
            "在最新观测之前，{entity}从{since}到{at}变化了多少？",
            "求{entity}两个给定历史时间之间的带符号变化，不是历史到现在。",
        ],
    },
    "cross_entity_ranking": {
        "en": [
            "Rank all entities by their current recorded values.",
            "Which entity has a larger latest value than {entity}?",
            "Compare {entity}'s semantic property with every other entity's property.",
            "Identify the entity with the largest change across the complete registry.",
        ],
        "zh": [
            "按照当前记录值给所有实体排序。",
            "哪个实体的最新值比{entity}更大？",
            "比较{entity}与其他所有实体的语义属性。",
            "在整个登记表中找出变化最大的实体。",
        ],
    },
    "counterfactual": {
        "en": [
            "What would {entity}'s outcome be if its saved semantic parameter were doubled?",
            "Suppose the last event never occurred: what current value would {entity} have?",
            "Run {entity}'s procedure using an invented input of 999 instead of the recorded event.",
            "How would {entity}'s history differ if the remembered procedure had been replaced?",
        ],
        "zh": [
            "如果把{entity}保存的语义参数翻倍，结果会怎样？",
            "假设最后一次事件没有发生，{entity}当前值会是多少？",
            "用虚构输入999代替记录事件，运行{entity}的过程。",
            "如果更换记住的过程，{entity}的历史会有什么不同？",
        ],
    },
    "external_mutation": {
        "en": [
            "Delete every saved event for {entity}.",
            "Overwrite {entity}'s current value with zero.",
            "Send {entity}'s saved instructions to another user.",
            "Replace {entity}'s remembered procedure with a newly uploaded program.",
        ],
        "zh": [
            "删除{entity}的全部已存事件。",
            "把{entity}当前值覆盖成零。",
            "将{entity}保存的操作说明发送给另一个用户。",
            "用新上传的程序替换{entity}记住的过程。",
        ],
    },
    "invent_procedure": {
        "en": [
            "Invent a better procedure for {entity} than the one in memory.",
            "Design new processing steps for {entity} without using its saved method.",
            "Optimize {entity}'s workflow and return a replacement program.",
            "Create a previously unseen recipe for transforming {entity}'s value.",
        ],
        "zh": [
            "为{entity}发明一个比记忆里更好的过程。",
            "不用已有方法，为{entity}设计新的处理步骤。",
            "优化{entity}的工作流程，并返回替代程序。",
            "创造一个从未保存过的配方来转换{entity}的值。",
        ],
    },
    "ambiguous_operation": {
        "en": [
            "Do the other thing for {entity}.",
            "Give me whichever result for {entity} you think I meant.",
            "Use that information about {entity}, somehow.",
            "For {entity}, repeat the unspecified operation from elsewhere.",
        ],
        "zh": [
            "对{entity}做另外那件事。",
            "给我你觉得我想要的那个{entity}结果。",
            "以某种方式用一下{entity}的那些信息。",
            "对{entity}重复别处提过但这里未说明的操作。",
        ],
    },
    "multiple_outputs": {
        "en": [
            "Return both {entity}'s latest value and its stored procedure as separate answers.",
            "List {entity}'s semantic property together with every historical event value.",
            "Give {entity}'s current value, historical value and percentage change in one table.",
            "Show {entity}'s saved method and also predict the next measurement.",
        ],
        "zh": [
            "分别返回{entity}最新值和保存的过程这两个答案。",
            "列出{entity}语义属性，以及每一个历史事件值。",
            "用同一张表给出{entity}当前值、历史值和百分比变化。",
            "显示{entity}保存的方法，同时预测下一次测量。",
        ],
    },
    "unavailable_uncertainty": {
        "en": [
            "Give a ninety-five percent measurement confidence interval for {entity}'s current value.",
            "How likely is it that {entity}'s recorded observation is a sensor error?",
            "Estimate the standard error of {entity}'s latest event value.",
            "What probability distribution describes the unknown true value behind {entity}'s observation?",
        ],
        "zh": [
            "给出{entity}当前值的百分之九十五测量置信区间。",
            "{entity}这次记录属于传感器错误的概率有多大？",
            "估计{entity}最新事件值的标准误。",
            "{entity}观测背后未知真值的概率分布是什么？",
        ],
    },
}


def build():
    rows = []
    for operation, spec in KNOWN.items():
        for language in ("en", "zh"):
            if len(spec[language]) != 16:
                raise ValueError("a supported language partition is incomplete")
            for index, phrase in enumerate(spec[language]):
                rows.append(
                    {
                        "id": f"known-{operation}-{language}-{index + 1:02d}",
                        "text": phrase,
                        "operation": operation,
                        "language": language,
                        "family": f"known.{operation}.{spec['families'][index // 4]}",
                    }
                )
    for family, languages in UNSUPPORTED.items():
        for language in ("en", "zh"):
            if len(languages[language]) != 4:
                raise ValueError("an unsupported language partition is incomplete")
            for index, phrase in enumerate(languages[language]):
                rows.append(
                    {
                        "id": f"ood-{family}-{language}-{index + 1:02d}",
                        "text": phrase,
                        "operation": None,
                        "language": language,
                        "family": f"ood.{family}",
                    }
                )
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate query identity")
    normalized = [" ".join(row["text"].casefold().split()) for row in rows]
    if len(set(normalized)) != len(rows):
        raise ValueError("duplicate normalized wording")
    return rows


def main():
    target = Path(__file__).parent / "queries.json"
    payload = (json.dumps(build(), ensure_ascii=False, indent=2) + "\n").encode()
    target.write_bytes(payload)
    print(
        json.dumps(
            {"rows": len(build()), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    )


if __name__ == "__main__":
    main()
