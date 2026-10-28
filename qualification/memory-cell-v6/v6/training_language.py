"""Public author-written language data; held evaluation is authored separately.

Every pipe-separated item is one authored semantic template. No held file is read.
English and Chinese are reported separately across the two pinned base choices.
"""

from .encoder import normalize_request


TRAIN = {
    "current": """What is the latest recorded value for entity?|Give me the most recent observation.|Read the current measurement.|What value is stored now?|Look up the newest event for this entity.|Show the final reading in the event history.|Retrieve the presently valid observation.|Which number was recorded most recently?|Return the last known value, not a forecast.|I need the newest saved data point.|What is our latest measurement of this item?|Fetch the value from the most recent event.|Look at the end of the timeline and read its value.|Tell me the latest stored observation for entity.|Use the newest record to report the value.|Read the present event value without applying any rules.|What did we last observe for this object?|Show me the most up-to-date value we have.|Select the latest event and return its measurement.|What reading is at the current frontier?|Retrieve the newest entry's number.|Read the current count from memory.|Find the most recent saved quantity.|What is the last reported reading?|Return the current raw measurement.|Which value appears in the latest event?|How much was recorded at the last observation?|Get the latest stored sample.|Read today's most recently stored state.|I only want the raw value from the newest observation.|Show the present recorded reading for this entity.|What is the freshest event value in the store?|读取这个实体的最新事件值。|最新记录的数值是多少？|返回目前保存的最近一次观测。|查一下现在最新的测量值。|这个对象最后一次记录了多少？|只要最新原始读数，不做计算。|取时间线上最后一条事件的值。|当前已知的观测数值是什么？|给我最近保存的那条记录。|这个实体最新的原始量是多少？|读取最新样本的数值。|查询当前事件记录。""",
    "history": """What value was recorded as of date?|Read the observation at the supplied historical cutoff.|Show the latest event no later than the requested time.|What was the value back then?|Retrieve the stored state at that past date.|Look up the historical reading for entity.|Read the value that was valid at the cutoff.|Which observation was available by that time?|Give me the event immediately before or at the specified time.|What did we know about the value at date?|Restore the recorded value from the earlier snapshot.|Find the last reading before the requested cutoff.|Return the old value, not today's latest entry.|Which number was stored by the historical deadline?|Read entity's event as it stood then.|Show me its earlier measurement.|What was the observation at the chosen past moment?|I need the historical value for this entity.|Retrieve the value from the requested time in the event history.|Go back to date and read the stored event.|What quantity had been recorded at that point?|Find the most recent reading within the supplied time boundary.|Read the raw measurement from the earlier date.|Return the value known at the supplied as-of time.|Which stored reading preceded the time limit?|What was the last event value before that date?|Fetch the old snapshot's observation.|Read the past record using the given cutoff.|Give the historical count as of the specified date.|What did the record say at the earlier time?|读取截止给定时间的事件值。|那个历史时间点的数值是多少？|返回指定日期之前最近的一次观测。|查一下当时保存的读数。|这个对象过去的记录值是什么？|按给定的历史截止时间查询。|读取旧版本的观测，不要当前值。|截止那个时刻我们记录了多少？|查询该日期的历史事件。|回到给定时间取当时的数值。|给我历史快照里的测量值。|读取过去那一时刻有效的记录。""",
    "semantic": """What semantic attribute is stored for entity?|Look up this entity's stable property.|Read the saved category for this object.|What calibration factor belongs to entity?|Retrieve the remembered semantic parameter.|What is the stored multiplier for this item?|Tell me this entity's learned classification.|Read its persistent attribute from semantic memory.|Which factor is associated with this object?|What does the semantic cell remember about this entity?|Get the attribute value, not an event reading.|Look up the stable metadata associated with entity.|What is the remembered property of this item?|Return its stored semantic value.|Which category has been assigned to this entity?|Read the calibration coefficient from memory.|Retrieve the fixed scale factor.|What stable relation is known for this object?|Give me the saved meaning or class for entity.|I need the attribute stored in the semantic cell.|Look up the entity's descriptive property.|Read the remembered conversion factor without applying it.|What is this entity's stored semantic coefficient?|Which static property is associated with it?|Fetch the semantic record for this object.|What multiplier was learned for this entity?|Return the class label assigned in memory.|Read the classification value stored for entity.|Tell me the stable characteristic saved for this item.|What semantic parameter should be recalled?|读取这个实体的语义属性。|它保存的稳定属性是什么？|查询该对象的类别。|这个实体的校准系数是多少？|取出记住的倍率，不要计算。|语义记忆里保存的参数是什么？|读取该对象关联的固定属性。|查询这个实体的分类标签。|返回已保存的语义数值。|这个对象记住的转换因子是多少？|查它的稳定特征，不是事件读数。|读取语义单元里的系数。""",
    "procedure": """Which procedure is stored for entity?|Read the remembered sequence of steps.|Show the saved instructions without running them.|What operation should be used for this entity?|Retrieve the stored recipe.|List the procedure associated with this object.|What steps does its procedural memory contain?|Tell me the stored workflow.|Which program is assigned to this entity?|Read the procedure code from memory.|Give me the remembered instructions, not their result.|What is the saved method for handling this item?|Look up the operations in the procedural cell.|Show the stored algorithm for this object.|Which sequence should I follow according to memory?|Retrieve the previously saved action recipe.|What procedure has been learned for entity?|Display its stored transformation steps.|Read the saved plan without applying it.|I want to inspect the procedure itself.|Tell me how memory says to process this entity.|Which ordered operations are stored for it?|Get the workflow definition.|What does the procedural cell remember?|Show me the assigned method.|Look up the remembered program.|Return the stored steps as a sequence.|Read the rule sequence, do not compute the answer.|Which saved instructions apply to this object?|Give me the procedure's definition from memory.|读取这个实体保存的过程。|它记住的操作步骤是什么？|查看流程，不要运行。|这个对象对应哪个程序？|返回存储的指令序列。|查一下过程记忆中的方法。|列出已经保存的步骤。|读取操作规则本身，不要计算结果。|程序单元记住了什么流程？|查询该实体适用的步骤定义。|显示记住的处理方案。|告诉我已存的操作顺序。""",
    "change": """How much has the value changed since the supplied date?|Subtract the earlier reading from the latest one.|What is the difference between the current and historical values?|Compute the change since the cutoff.|Give me the latest value minus the value as of date.|How far has the reading moved since then?|Compare the two specified times and report the delta.|Return the increase or decrease from the historical reading.|Find the numerical difference from the old observation to the newest.|What is the net change in this entity's value?|Calculate the latest-minus-earlier difference.|How much higher or lower is the current reading than the old one?|Read both values and subtract the past from the present.|Compute the signed change since the given time.|What difference separates the newest and earlier observations?|Report the amount by which the value has changed.|Find the delta relative to the supplied historical cutoff.|How much did the stored quantity rise or fall?|Compare now with then and return their difference.|I need the current raw value minus its historical counterpart.|What changed numerically between the cutoff and the latest event?|Calculate the difference without applying the saved procedure.|Return the subtraction of the past observation from the latest record.|What is the change from the earlier snapshot to the current one?|How large is the signed difference between those readings?|What is the difference in count since that time?|Give me the net movement since the earlier observation.|Compute the new-minus-old value.|Report the change in the recorded measurement.|How much did the reading increase since the supplied cutoff?|计算最新值与历史值的差。|从给定时间到现在变化了多少？|用当前观测减去当时观测。|这个实体的数值增减了多少？|返回新值减旧值的结果。|比较现在和过去，给我差值。|读取两个时间点并计算变化量。|截止时间以来的净变化是多少？|求最新读数和旧读数之间的差。|不要运行程序，只计算两次记录的差。|这个数值比当时高了还是低了多少？|计算当前减历史的有符号差值。""",
    "apply": """Apply the stored procedure to the latest value using the semantic parameter.|Run the remembered recipe on the current observation and saved factor.|Compute the result of the stored transformation.|Execute this entity's saved program with its event and semantic memories.|Use the latest measurement, calibration factor, and remembered steps to calculate the answer.|Carry out the stored workflow on the recalled data.|Combine the event value and semantic parameter through the saved procedure.|What is the output after applying its remembered process?|Run the stored sequence on the newest reading.|Calculate the processed value using this entity's saved instructions.|Apply the remembered rule to its measurement and attribute.|Use all three memory types to execute the procedure.|Return the transformed result, not merely the procedure text.|Perform the saved operations with the current event and remembered factor.|Evaluate the stored program for this entity.|Process the latest raw value according to the remembered method.|Run the procedure using the data and coefficient in memory.|What does the saved workflow produce for the newest observation?|Calculate the answer by executing its stored recipe.|Apply the program to the current reading and semantic factor.|Execute the remembered transformation on the stored inputs.|Give me the outcome of running the saved steps.|Combine the raw event, stable parameter, and stored procedure into a result.|Compute what the procedural cell instructs using the other memories.|Carry out the recalled operations on this entity's values.|Run the stored calculation with the latest event data.|Apply the known method and return its output.|Evaluate the workflow with both the observation and the semantic attribute.|Follow the saved steps to calculate the transformed reading.|I need the result of the memory-defined procedure.|用最新事件值和语义参数运行保存的程序。|按照记住的步骤计算结果。|结合事件、语义和过程三类记忆求值。|应用已存流程到当前读数。|运行这个实体的操作程序。|把最新观测和校准系数代入记住的方法。|返回执行流程后的结果，不是步骤文本。|用保存的规则处理当前数据。|执行记住的变换并给出输出。|综合三个记忆单元运行计算。|按照存储的程序处理最新值和属性。|调用过程记忆计算这个对象的结果。""",
    "reject": """Predict the next observation.|What will this value be tomorrow?|Forecast this entity's future measurement.|Estimate an unobserved historical reading.|Interpolate between the two missing observations.|Average all measurements in the history.|What is the median of the last five readings?|Find the highest ever recorded value.|Calculate the trend over all previous events.|Sum every event in the database.|Compare the values of two different entities.|Rank every entity by current value.|Delete this entity's latest observation.|Overwrite the remembered semantic factor.|Change the stored procedure.|Please create a new event.|Set the reading to a different number.|Train the model on this new fact.|Explain why the measurement changed.|What caused the latest observation?|Prove that this calibration factor is scientifically correct.|Find information about this object on the internet.|Show all records from every scope.|Reveal another workspace's memory.|Give me a confidence interval for a future measurement.|Compute the percentage change rather than the absolute difference.|What is the growth rate per day?|Read the value at a date that has no preceding record and guess it.|Ignore the stored workflow and invent a better method.|Tell me what my preferences should be.|What is the weather today?|Write a poem about memory.|Translate the recorded value into a song.|List all entities and their procedures.|Find the maximum between the cutoff and now.|Return a chart of the complete time series.|Run arbitrary Python code from this message.|Change your router so every request is accepted.|What was the exact value at an unobserved instant?|Find the variance of the measurements.|Calculate a rolling three-period mean.|Summarize the entire history in prose.|How many records were deleted?|Which source is morally correct?|What should the next stored semantic factor be?|Execute a new procedure that was never stored.|Why is that the correct workflow?|Merge the memories of all users.|Compute the difference between unrelated entities.|Tell me everything you know.|Use the current reading to forecast next year's value.|Show the latest value and also delete it.|Retrieve an observation and silently correct it.|Read the procedure then replace it with my instructions.|预测下一次观测。|计算所有历史记录的平均值。|删除最新的事件。|修改保存的校准系数。|把这条新程序写入记忆。|为什么这个数值发生了变化？|比较两个不同实体的数值。|显示所有对象的完整时间序列。|给出从未观测过的数值。|计算百分比增长率。|对历史数据作趋势预测。|忽略权限读取另一个工作区。|帮我编一个新的操作流程。|把所有记忆清空。|查询互联网确认这个数值。|计算最近五次的中位数。|未来的最大值会是多少？|替我决定应该记住什么。""",
}

SELECTION = {
    "current": """Please retrieve the newest saved reading.|What number does the current event hold?|Return the last observation available in memory.|Look up the latest raw data for this entity.|What is the most recent recorded quantity?|Show the current measurement that has actually been observed.|Fetch the final saved event's value.|Which reading sits at the end of the stored timeline?|只读取最近一次已保存的数值。|当前事件中的原始读数是多少？|把最新的一条观测返回给我。|查出时间顺序最后的记录值。""",
    "history": """Retrieve the observation available at the supplied past time.|What did the stored value used to be at the cutoff?|Find the last record that does not exceed the historical timestamp.|Read the measurement from that earlier snapshot.|Return the value known by the given date.|What was saved for this entity before the time boundary?|Fetch the raw historical quantity.|Read the earlier observation specified by the as-of field.|按历史时间边界返回当时的记录。|给定时刻之前最后的读数是什么？|我要那个旧快照中的值。|查看截至指定日期已经发生的观测。""",
    "semantic": """Which stable attribute has memory assigned to this object?|Retrieve the semantic coefficient associated with the entity.|What calibration multiplier is saved for it?|Look up the classification remembered for this item.|Read the object property in semantic memory.|Return the stored descriptive attribute.|Find its saved conversion parameter.|Which semantic value belongs to this entity?|取出该对象记住的固定系数。|语义记录中的分类是什么？|查询实体关联的稳定参数。|返回这个对象的语义属性值。""",
    "procedure": """Retrieve the saved sequence of operations for this entity.|Show the remembered processing instructions without executing them.|Which workflow is kept in procedural memory?|Return the program definition stored for this object.|Read the steps that memory associates with it.|What recipe was saved for this entity?|Inspect the remembered method itself.|Which instructions should be recalled from the procedure cell?|我想查看该对象已存的流程定义。|返回过程单元记住的步骤顺序。|显示操作指令本身，不进行求值。|查出实体对应的程序规则。""",
    "change": """Find how much the newest reading differs from the one at the cutoff.|Calculate the signed movement from the historical value to the current one.|Return today's stored value less the earlier saved value.|What is the numerical increase since the supplied past date?|Subtract the old observation from the most recent record.|Report the absolute-unit delta between the old and current observations.|How much lower or higher has the value become since then?|Compute current minus as-of for this entity.|求最新记录相对历史记录的增减量。|将当时的值从现在的值中减去。|这个对象自给定日期变化了多少数值？|返回当前与旧快照的差额。""",
    "apply": """Execute the remembered operations using the current observation and semantic coefficient.|What answer comes from the saved recipe applied to this entity's memories?|Process the newest reading with its stored parameter and workflow.|Evaluate the procedure from memory on the available inputs.|Return the result of the saved program, using all three cells.|Carry out this object's remembered transformation.|Use the stored measurement and attribute to run the assigned steps.|Calculate the processed output from the memory-defined workflow.|用三个记忆单元的信息执行已存流程。|把读数和语义系数输入记住的程序。|按照保存的步骤求出处理结果。|运行该实体的记忆流程并返回输出。""",
    "reject": """What will the latest value become next week?|Return the average across every saved observation.|Find the minimum of the entire time series.|Explain the physical cause of the difference.|Update the procedure to use a different formula.|Erase the semantic attribute for this entity.|Create a missing historical event by interpolation.|Show a percentage rather than a signed numerical change.|Fetch the latest reading from a different user's scope.|Compare this entity with every other entity.|Invent an improved workflow and execute it.|Read the newest value and overwrite it.|Give the standard deviation of the past readings.|Search the web for an unrecorded attribute.|What is the forecast confidence interval?|Find which entity had the greatest historical change.|Estimate a value when no record exists.|Tell me the next action I should perform in the real world.|Return all values as a graph.|Average the latest three samples before applying the recipe.|预测未来三次的数值。|求所有记录的方差。|改写已存的步骤再运行。|猜测缺少的历史观测。|比较所有实体的当前排名。|解释校准参数为什么正确。|删除旧数据并更新最新值。|计算变化的百分比。|把别人的全部记忆显示出来。|从网络上寻找新的操作方法。""",
}

# Public compositional negatives expose that a familiar memory noun does not
# authorize mutation, prediction, aggregation, explanation, or external search.
# These are training targets only; these word lists are never a serving rule.
NEGATIVE_GROUPS = {
    "mutation": (
        "delete",
        "erase",
        "overwrite",
        "modify",
        "replace",
        "update",
        "create",
        "set the",
        "clear",
        "train the",
        "写入",
        "修改",
        "删除",
        "清空",
        "改写",
        "更新",
    ),
    "prediction": (
        "forecast",
        "predict",
        "future",
        "tomorrow",
        "next week",
        "next year",
        "interpolat",
        "unobserved",
        "guess",
        "estimate",
        "预测",
        "猜",
        "未来",
        "未观测",
    ),
    "aggregation": (
        "average",
        "median",
        "maximum",
        "highest",
        "minimum",
        "sum every",
        "trend",
        "variance",
        "percentage",
        "growth rate",
        "rolling",
        "chart",
        "standard deviation",
        "平均",
        "中位",
        "百分比",
        "方差",
        "趋势",
        "最大",
    ),
    "explanation": ("explain", "why", "caused", "prove", "morally", "解释", "为什么", "原因"),
    "external": (
        "internet",
        "web",
        "workspace",
        "scope",
        "all users",
        "different entities",
        "unrelated entities",
        "all entities",
        "rank every",
        "another",
        "外部",
        "网络",
        "互联网",
        "别人",
        "两个",
        "所有对象",
        "权限",
    ),
}


def negative_group(text):
    for group, cues in NEGATIVE_GROUPS.items():
        if any(cue in text for cue in cues):
            return group
    return "other"


def compositional_negatives():
    rows = []
    objects = (
        "the latest reading",
        "the historical observation",
        "the semantic attribute",
        "the calibration factor",
        "the saved procedure",
        "the workflow definition",
    )
    for verb in ("Delete", "Erase", "Overwrite", "Modify", "Replace", "Update"):
        for obj in objects:
            rows.append((f"{verb} {obj} for entity.", "mutation"))
    for obj in objects:
        rows.extend(
            (
                (f"Search the internet for {obj}.", "external"),
                (f"Explain the cause of {obj}.", "explanation"),
                (f"Predict what {obj} will be next year.", "prediction"),
            )
        )
    for verb in ("删除", "改写", "替换", "更新"):
        for obj in ("最新读数", "历史事件", "语义属性", "校准参数", "保存的程序", "已存流程"):
            rows.append((f"{verb}该实体的{obj}。", "mutation"))
    for obj in ("最新读数", "历史数值", "语义属性", "操作方法"):
        rows.extend(
            (
                (f"从互联网搜索这个对象的{obj}。", "external"),
                (f"解释这个对象的{obj}为什么正确。", "explanation"),
                (f"预测这个对象未来的{obj}。", "prediction"),
            )
        )
    return rows


def corpus(partition):
    source = {"train": TRAIN, "selection": SELECTION}[partition]
    rows = []
    for operation, packed in source.items():
        for index, text in enumerate(packed.strip().split("|")):
            text = normalize_request(text)
            rows.append(
                {
                    "id": f"{partition}:{operation}:{index:03}",
                    "text": text,
                    "operation": operation,
                    "language": "zh" if any("\u3400" <= char <= "\u9fff" for char in text) else "en",
                    "negative_group": negative_group(text) if operation == "reject" else None,
                    "authorship": "training-agent; synthetic author template",
                }
            )
    if partition == "train":
        for index, (text, group) in enumerate(compositional_negatives()):
            text = normalize_request(text)
            rows.append(
                {
                    "id": f"train:compositional-negative:{index:03}",
                    "text": text,
                    "operation": "reject",
                    "negative_group": group,
                    "language": "zh" if any("\u3400" <= char <= "\u9fff" for char in text) else "en",
                    "authorship": "training-agent; compositional negative derived from public templates",
                }
            )
    if len({row["text"] for row in rows}) != len(rows):
        raise ValueError("duplicate authored language rows")
    return rows
