"""Public V7 training, selection and calibration language; no held reads.

Calibration wording is excluded from every fit and candidate selection. These
are author-written synthetic families, not a random human population sample.
"""

from .contracts import normalize


TRAIN_EXTRA = {
    "current": """Retrieve entity's latest unprocessed sample.|The newest entry for entity: what number does it contain?|I'd like the last observation we actually saved for entity.|Get entity's raw reading at the end of its log.|Which reading is the freshest one in entity's records?|Just recall entity's present observed quantity.|Without computing anything, return entity's latest event.|Tell me entity's current stored measurement as it is.|查看 entity 目前最新保存的原始数据。|entity 最近一次实际观测结果是什么？|请直接读出 entity 最后一笔事件里的数值。|只查 entity 最新记录，不执行处理步骤。|我需要 entity 时间线上最靠后的那笔读数。|现在记录中 entity 的原始量是多少？|回忆 entity 最近保存的数据点。|输出 entity 最新事件里的观测量。|entity 当下已存的数值是几？|查询 entity 最新一次录入的实际读数。|请把 entity 最后保存的测量结果原样返回。|entity 最近被观测到的数值是多少？""",
    "history": """For entity, recall the reading on file by the supplied cutoff.|Use the as-of boundary to fetch entity's earlier raw value.|At that previous point, what was entity's recorded quantity?|Take entity's last observation within the stated time bound.|Which saved reading would entity's old snapshot expose?|Read entity's observation on or before the provided date.|Find the historical event for entity using the at field.|Recall the last known measurement before that cutoff.|读取 entity 在给定截止时点已存的原始数值。|回到当时，entity 的观测值是什么？|在指定时间以前最后记录的 entity 数值是多少？|从旧快照取出 entity 当时的读数。|查看 entity 截至该时刻的事件值。|按 at 时间界限查询 entity 的历史样本。|entity 在这个过去时间点之前最后一次测到了多少？|请回忆 entity 当时保存的那笔观测。|不要现在的值，我需要 entity 截止给定时间的记录。|以历史截止时刻为界，查找 entity 最后一个数据点。|把 entity 旧时点上的原始测量值返回。|根据提供的时间边界检索 entity 的过往记录。""",
    "semantic": """Recall entity's stored multiplier itself.|What label and factor have we associated with entity?|Retrieve entity's saved calibration metadata.|Give entity's remembered category, with no execution.|Look up the property record attached to entity.|What does memory say entity's stable coefficient is?|Inspect the semantic attributes assigned to entity.|Fetch entity's stored factor, not a transformed observation.|entity 已记住的固定属性有哪些？|查 entity 的分类和倍率记录。|请取出 entity 的语义参数本身。|entity 对应的已存转换系数是多少？|查看 entity 的属性记忆，不要处理事件值。|显示 entity 已保存的校准信息。|返回 entity 的语义标签与因子。|我要知道 entity 记忆中的稳定属性。|请检索 entity 存放在语义单元的参数。|entity 已记录的倍率是什么？|原样读出 entity 的语义属性记录。|查询 entity 与固定系数之间的已存关联。""",
    "procedure": """Describe only the saved steps for entity, without executing them.|I want entity's recipe as stored, rather than its computed output.|Bring back the existing workflow definition for entity.|Which transformation instructions are on file for entity?|Inspect the stored method that entity would use.|Read out entity's registered program, stopping before evaluation.|What saved processing sequence belongs to entity?|Return the code of entity's remembered procedure as data.|Show me how the existing recipe says to process entity.|Recall what the procedure says, not the answer obtained by using it.|List the instructions already associated with entity.|Give me the stored plan itself for entity.|Which algorithm is already recorded for entity?|Display entity's workflow steps verbatim from its procedural memory.|Retrieve entity's existing program definition for inspection.|What are the remembered instructions for processing entity?|列出 entity 当前记住的工作流程步骤。|我只想查看 entity 保存的处理方法。|把 entity 的程序定义读出来，先别运行。|entity 现有的操作规则具体是什么？|请显示 entity 的流程文本本身。|回忆 entity 以前存下的算法步骤。|按记忆列出 entity 当前流程，不要求计算结果。|给我 entity 保存的处理指令，作为数据返回。|entity 的过程单元里存了哪些步骤？|查出用于 entity 的已有方案定义。|读取 entity 已经登记的程序内容。|展示 entity 的已存操作序列。|目前记忆里 entity 应按什么流程处理？|entity 对应的程序原本是怎样定义的？|只取 entity 的过程记录，不将它作用于输入。|请回忆 entity 那个已保存的方法本身。""",
    "change": """Read entity's current and earlier values, then return current minus earlier.|Subtract entity's as-of value from its newest observation.|How far has entity moved since the given historical cutoff, in raw units?|What signed delta links entity's old snapshot to its latest sample?|Take the stored value now less the value at the since timestamp.|Read both endpoints for entity and report the new-minus-old amount.|Entity's latest reading minus the old reading: what is the result?|Find the net numeric change from the provided past cutoff to now.|Return the increase or decrease in entity's recorded value since then.|Compute the current-to-historical difference for entity.|Compare entity's latest sample with its as-of sample by subtraction.|What's the signed gap from entity's previous cutoff to the present record?|读取 entity 现在和当时的值，再返回现在减当时。|请用 entity 最新值扣去 since 时点的旧值。|从这个过去截止点到最新记录，entity 增减了多少？|entity 当前读数与历史读数相差多少，按新减旧计算？|先读 entity 两端记录，再计算最新减历史。|计算 entity 当前记录相对于给定旧时点的净增量。|entity 最新值减去当时保存的数值等于多少？|只求 entity 从旧快照到当前的有符号变化量。|把 entity 旧读数从新读数中减去。|返回 entity 现在比给定过去时刻多出或减少的数量。|比较 entity 的当前与过去，只输出新旧差额。|用减法算出 entity 截止时刻以来的变化。|entity 自 since 指定的时间起变化了几单位？|求 entity 历史值到最新值之间的净变化。|当前减过去，算 entity 的两次读数差。|entity 的最新观测相对旧快照增加了多少原始单位？""",
    "apply": """Use entity's saved recipe to produce a result from its latest observation.|Run the existing program for entity on the remembered input and coefficient.|Evaluate entity's stored transformation with its current event and attributes.|I need the numerical output of entity's remembered workflow.|Carry out the recorded procedure for entity with the available memories.|Take the current sample through entity's saved processing steps.|Apply entity's on-file program and return the resulting quantity.|Compute what entity's existing recipe produces with its stored data.|请实际执行 entity 已保存的流程并返回结果。|把 entity 当前事件与固定参数交给已存程序求值。|不是查看步骤，请运行 entity 的现有方法。|按 entity 的已有处理规则算出当前输出。|调用 entity 记住的变换处理最新观测。|用 entity 目前的读数和语义属性计算流程结果。|执行 entity 的程序记录，得到变换后的数值。|将三个记忆单元组合起来，为 entity 运行流程。|现在按 entity 保存的指令完成计算。|给出 entity 的当前数据经过已存程序处理后的输出。|按照 entity 记住的配方加工最新输入。|从 entity 的记忆数据求出已登记程序的执行结果。""",
}

NEGATIVE_TRAIN = {
    "arithmetic": """Take the logarithm of entity's current reading.|Return the square root of the latest event.|Divide entity's current value by its historical value.|Compute entity's percentage rise since the cutoff.|Raise the latest reading to the power of the semantic factor.|Convert the saved procedure's output to a percentage.|Multiply the latest reading by an arbitrary number I supply.|Calculate the reciprocal of the semantic coefficient.|计算 entity 当前读数的对数。|返回 entity 最新数值的平方根。|求 entity 最新与历史数值的比率。|把 entity 的变化量换算成百分比。|对 entity 的系数取倒数。|把程序结果按我给的新公式重新计算。|计算 entity 的指数增长率。|将 entity 当前值除以过去值。""",
    "counterfactual": """What would entity's latest reading have been under a different factor?|Run the saved recipe as if the latest observation were twice as large.|What output would entity have produced without the last event?|If the calibration had been different, how would the current result change?|Assume entity had no historical record and invent the value.|What would the procedure return if I replaced its stored input?|如果 entity 的系数不同，当前结果会是多少？|假设 entity 最新读数翻倍，运行程序会怎样？|如果没有最后一次事件，entity 现在应该是什么值？|假定 entity 的过去观测不存在，猜测当前数值。|把 entity 的历史改成另一种情况再求输出。|如果当时采用新流程，entity 会得到什么结果？""",
    "time_composition": """Subtract one historical reading of entity from another historical reading.|What was entity's change between two past cutoffs, excluding the latest event?|Apply the current recipe to entity's old observation.|Run entity's former procedure with its newest event.|Calculate the difference between entity's two oldest observations.|Give the old semantic attribute as it was at a past date.|Compute a historical program using the semantic factor from another time.|Compare entity's event at the first supplied past date to its event at the second.|计算 entity 两个过去时间点之间的差值，不用最新值。|把 entity 当前程序应用到旧事件上。|用 entity 以前的流程处理当前数据。|求 entity 最早两条历史记录之差。|返回 entity 在旧时点上的语义属性版本。|将 entity 两个历史截止时间的读数相减。|用另一个日期的系数执行 entity 的历史程序。|比较 entity 两个旧快照之间的变化。""",
    "multiple_outputs": """Return entity's latest value and the complete program definition as two outputs.|Show both the historical reading and the semantic attributes separately.|Give me the current value, its delta, and the recipe text.|Read entity's latest observation and also explain why it changed.|List the raw event and then forecast the next event.|Return entity's saved program and overwrite its first instruction.|Show the factor and then change its value.|Give two independent answers: the latest reading and the old reading.|同时返回 entity 的最新值和完整程序，分别输出。|把 entity 的历史读数和语义属性都列出来。|给我 entity 当前值、变化量以及步骤文本三个结果。|读取 entity 的最新事件，再解释为什么变化。|返回 entity 的程序后改写第一条指令。|既查询 entity 的系数，又把它改成新数值。|输出 entity 最新与过去的两个原始读数，不要相减。|先显示 entity 的属性，再预测下一次事件。""",
}

SELECTION_EXTRA = {
    "procedure": """Recall the recipe itself that was previously saved for entity.|Which steps are in entity's existing instruction record?|Inspect entity's stored program as a definition.|Bring up the workflow on file without evaluation.|请按记忆展示 entity 已有流程的内容。|entity 曾保存过怎样的程序定义？|查询 entity 的步骤记录本身。|先不要运行，我想看 entity 记住的方法。""",
    "change": """Retrieve the newest and cutoff readings for entity and subtract the latter.|Find entity's raw-unit movement from the requested past point to its last event.|Compute latest less historical for entity.|What amount separates entity's current record from the older cutoff record?|取出 entity 现在与过去的记录，然后算现在减过去。|给我 entity 从指定旧快照到最新事件的差额。|用 entity 最新读数减去截止时间的读数。|entity 相比给定的历史点净增加或减少多少？""",
    "arithmetic": """What is the ratio of entity's newest value to its old value?|Take the cosine of entity's saved factor.|计算 entity 的绝对百分比变化。|将 entity 最新数值开平方。""",
    "counterfactual": """What would the latest result be if entity's remembered factor were one larger?|Suppose entity's last event were missing; what should the value be?|假如 entity 的程序用另一种运算，结果会怎样？|如果 entity 的最新记录是另一个值，请预测输出。""",
    "time_composition": """How much did entity change between the two supplied historical dates?|Use a historical recipe for entity's historical observation.|返回 entity 过去两个截止点之间的差。|用 entity 的旧过程计算旧输入。""",
    "multiple_outputs": """Give entity's latest reading and its stable parameter as separate results.|Read entity's current event, then edit the workflow.|同时列出 entity 的最新值和语义系数。|给出 entity 旧值、新值和流程三个独立答案。""",
}

CALIBRATION_KNOWN = {
    "current": """What is the newest observed figure kept for entity?|Consult entity's last saved sample and repeat its value.|Fetch the end-of-log observation for entity.|I need entity's freshest raw number on file.|Read back the most recently entered measurement for entity.|Look at entity's final event and return its unprocessed quantity.|Retrieve the observation currently at entity's recorded frontier.|What number did we save most recently for entity?|Give the value from entity's newest measurement record.|Which raw observation is the last one recorded for entity?|entity 最后一次被保存的观测量是多少？|请查阅 entity 事件日志末尾的原始数字。|复述 entity 最新一笔测量记录的值。|我想取回 entity 最近日志里的观测量。|从 entity 最靠后的事件读出数值。|告诉我 entity 已记录的最新那次数量。|查询 entity 当前记录前沿的原始值。|entity 最近落盘的测量数是多少？|检索 entity 最新已知且确实保存的读数。|只回读 entity 最新一项事件数据。""",
    "history": """As of the supplied past cutoff, what figure was on record for entity?|Consult the last event for entity that had occurred by that time.|Recover entity's raw measurement from the chosen earlier snapshot.|What observation was available for entity at the requested time boundary?|Look backward to the supplied cutoff and fetch entity's reading.|Find entity's final saved sample preceding or matching that time.|Read back entity's event using the historical at boundary.|What was entity's last recorded quantity by the given past date?|Use the earlier cutoff to retrieve entity's then-current event.|Return the raw reading exposed by entity's historical snapshot.|截至给出的旧时间边界，entity 记录了什么值？|请取回 entity 在那个过往时点已知的观测量。|查 entity 在历史截止点以前的最后一笔数据。|回读 entity 指定旧快照暴露的原始数值。|用过去的 at 边界定位 entity 当时记录。|entity 到给定日期为止最后保存的测量量是多少？|以那个历史时刻为限检索 entity 的读数。|找出 entity 在所述旧时间点已发生的最近事件值。|返回 entity 截至过去截止线的原始观测。|请恢复 entity 当时快照中的测量数。""",
    "semantic": """Read back the stable coefficient remembered for entity.|What semantic metadata is already on file for entity?|Retrieve the calibration property that memory associates with entity.|Which remembered factor and label describe entity?|Consult entity's semantic record and return its attribute value.|I want entity's saved category information itself.|Fetch the persistent semantic parameter attached to entity.|What is entity's on-file conversion coefficient?|Return the recorded property from entity's semantic cell.|Recall the fixed attribute stored against entity's identity.|请回读 entity 已记忆的属性参数。|entity 的语义记录里登记了什么系数？|检索附在 entity 身上的固定倍率信息。|我需要 entity 已保存的类别属性本身。|取回 entity 所关联的稳定语义特征。|entity 在记忆中的校准属性是什么？|查看 entity 现有的语义元数据。|给出与 entity 身份绑定的转换参数。|把 entity 属性单元里保存的记录读出来。|回忆 entity 当前登记的语义标签和系数。""",
    "procedure": """What instruction sequence was previously recorded for entity?|Read back entity's on-file processing recipe as data.|Which existing program definition can memory recall for entity?|Consult entity's procedural record and display its steps.|Return the remembered workflow itself without evaluation.|Bring up entity's already registered instructions for inspection.|What does entity's stored algorithm tell us to do?|Show the saved transformation definition associated with entity.|Retrieve the procedure that was on file, keeping it unevaluated.|I want to read entity's remembered method rather than execute it.|entity 先前登记的指令序列是什么？|请回读 entity 已存的配方内容，暂不求值。|调出 entity 记住的流程定义供我查看。|从 entity 的过程记录中列出已有步骤。|回忆 entity 曾经保存的处理方法。|把 entity 已登记的变换规则作为数据返回。|entity 的记忆中原有程序怎么写的？|查看 entity 已存的操作方法而不执行。|请展示 entity 当前记得的指令内容。|取回 entity 保存的程序，保持它未运行。""",
    "change": """How many raw units separate entity's old cutoff value from its latest event?|Return the latest saved figure for entity less the one known at the since boundary.|Find entity's signed movement from the supplied historical point to the current record.|Use entity's two endpoint readings to calculate new minus old.|What is the net rise or fall in entity's observation since the stated cutoff?|Subtract the remembered earlier number from entity's newest recorded number.|Compare entity's current snapshot with the supplied past snapshot by difference.|Compute entity's latest-to-old signed gap without applying a recipe.|Give the net change from the since record to the newest record for entity.|Read both values for entity and output their latest-minus-historical difference.|entity 从指定历史点到最新事件净变动了几个单位？|用 entity 最新保存的量减去 since 边界处的量。|请计算 entity 旧截止值到当前记录的有符号差额。|读取 entity 新旧两端的数据并输出新减旧。|entity 自所述历史界限起净上升或下降多少？|从 entity 最新测量数中扣除记住的较早测量数。|按减法比较 entity 当前快照与给定旧快照。|求 entity 最新到历史的数值差，不应用配方。|给出 entity 从 since 记录到末条记录的净变化量。|先查 entity 两端的值，再返回最新减历史的差。""",
    "apply": """Produce the output of entity's remembered recipe using its present memories.|Evaluate the on-file program with entity's latest event and saved attributes.|Take entity's current raw sample through the recorded transformation.|Execute the existing instructions on the event and coefficient saved for entity.|What result does entity's stored workflow yield on its newest input?|Run the remembered processing method using all three cells for entity.|Calculate the output prescribed by entity's saved program.|Use entity's recorded recipe to transform its latest observed quantity.|Carry out the existing workflow using entity's remembered measurement and parameter.|Return the numeric result after executing entity's on-file steps.|用 entity 当前的记忆数据产生已存配方的输出。|将 entity 最新事件和属性代入登记好的程序求值。|让 entity 的当前原始样本经过已记录的变换。|对 entity 保存的事件和系数执行已有指令。|entity 现存流程对最新输入会给出什么计算结果？|调用三个记忆单元运行 entity 已记住的处理方法。|求 entity 已保存程序所规定的输出数值。|用 entity 记录中的配方处理其最新观测量。|结合 entity 的记忆读数与参数完成已有流程。|执行 entity 已登记的步骤后返回最终数值。""",
}

CALIBRATION_REJECT = {
    "mutation": """Replace entity's stored multiplier with a new number.|Remove the event at entity's current frontier.|Rewrite entity's registered program before recalling it.|Append a fresh observation for entity.|Change entity's remembered label.|请将 entity 的校准参数换成新值。|把 entity 最新事件从记录中移除。|先重写 entity 的程序再返回它。|为 entity 增补一条新的观测。|修改 entity 的已存分类标签。""",
    "prediction": """Tell me entity's likely next observation.|Forecast the reading entity will have next month.|Extrapolate entity's current measurement into the future.|Which value should entity record tomorrow?|Estimate entity's next event from its latest one.|预测 entity 接下来最可能的观测值。|推断 entity 下个月会有什么读数。|把 entity 当前测量外推到未来。|entity 明天应该记录多少？|根据 entity 最近事件估算下一笔数据。""",
    "aggregation": """Find the median across entity's entire event log.|Compute the greatest reading entity has ever saved.|Average entity's most recent five observations.|Return the variance of entity's past measurements.|Rank all of entity's historical readings.|求 entity 整个事件日志的中位数。|计算 entity 曾记录过的最高读数。|对 entity 最近五次观测取平均。|返回 entity 过往测量的方差。|把 entity 所有历史读数按大小排序。""",
    "explanation": """Why did entity's stored quantity increase?|Explain the mechanism behind entity's latest reading.|Prove that entity's remembered factor is scientifically valid.|What caused entity's historical change?|Justify why entity's saved procedure is optimal.|为什么 entity 的已存数值增加了？|解释 entity 最新读数背后的机制。|证明 entity 记住的系数在科学上成立。|entity 历史变化的原因是什么？|论证 entity 保存的程序为何最优。""",
    "external": """Look up entity's current observation on the internet.|Read entity's values from a different user's workspace.|Combine entity's memories with another account's records.|Search outside this scope for entity's factor.|Fetch every user's procedure for entity.|到互联网上查 entity 的当前观测值。|读取另一个用户工作区中 entity 的数值。|合并 entity 与另一个账户的记忆记录。|在这个 scope 之外搜索 entity 的系数。|获取所有用户为 entity 保存的程序。""",
    "arithmetic": """Compute the logarithm of entity's saved event value.|Return entity's latest-to-old ratio.|Calculate entity's percentage change since the cutoff.|Square entity's stable factor.|Divide the procedure output by my supplied constant.|求 entity 保存事件值的对数。|返回 entity 最新与旧值的比率。|计算 entity 从截止点到现在的百分比变化。|把 entity 的稳定系数平方。|将程序输出除以我提供的常数。""",
    "counterfactual": """What would the result be if entity's stored factor were zero?|Assume entity's latest measurement doubled and recompute.|What observation would entity have without the most recent event?|If entity had used another program, what would the output be?|Pretend entity's historical value differed and calculate the change.|如果 entity 保存的系数为零，结果会是多少？|假设 entity 最新测量翻倍后重新计算。|没有最近事件的话 entity 会有怎样的观测？|若 entity 采用另一个程序，输出是什么？|假定 entity 的旧值不同，再求变化量。""",
    "time_composition": """Find entity's delta between two historical cutoffs rather than the latest event.|Execute entity's latest recipe on its earlier observation.|Return the factor that entity had at a historical time.|Use an old program with entity's newest measurement.|Subtract entity's first historical observation from its second one.|求 entity 两个历史截止点之间的变化，不涉及最新事件。|对 entity 的较早观测执行当前配方。|返回 entity 在某个旧时刻拥有的系数。|用 entity 的旧程序处理最新测量。|将 entity 第二个历史观测减去第一个历史观测。""",
    "multiple_outputs": """Return both entity's current event and its program definition.|Give entity's latest value, historical value and semantic record separately.|Show entity's current measurement and then predict the next one.|Read entity's factor and also overwrite it.|Provide two outputs: entity's procedure and its computed result.|同时返回 entity 的当前事件和程序定义。|分别给出 entity 最新值、历史值和语义记录。|展示 entity 当前测量后再预测下一次测量。|读取 entity 系数并顺便覆盖它。|给出两个输出：entity 的程序和该程序计算结果。""",
    "other": """Compose a poem about entity's measurements.|Invent an improved procedure for entity.|Translate entity's complete memory into a new language.|Execute arbitrary code supplied in my message.|Choose what entity ought to remember next.|围绕 entity 的测量值写一首诗。|为 entity 发明一个改进的程序。|把 entity 的全部记忆翻译成另一种语言。|执行我在消息中给出的任意代码。|替 entity 决定接下来应当记住什么。""",
    "missing": """Invent entity's value at an unobserved time.|Fill an empty historical slot with a plausible reading.|Guess entity's coefficient when no semantic record exists.|Interpolate a missing observation before applying entity's recipe.|Create an answer even if entity has no saved program.|编造 entity 在未观测时间的数值。|用一个合理读数填补空的历史位置。|没有语义记录时猜 entity 的系数。|先插补缺失观测再运行 entity 的配方。|即使 entity 没有保存程序也给出结果。""",
    "cross_entity": """Subtract another object's current reading from entity's value.|Which of entity and a second object has the larger factor?|Combine two different entities' programs into one answer.|Rank entity against all other objects by latest value.|Use one object's procedure with a different object's measurement.|从 entity 的值中减去另一个对象的当前读数。|比较 entity 与第二个对象谁的系数更大。|把两个不同实体的程序组合成一个答案。|按最新值比较 entity 与所有其他对象的排名。|使用一个对象的程序处理另一个对象的测量。""",
}


def add(rows, packed, split, label, family_prefix):
    for index, value in enumerate(packed.strip().split("|")):
        operation = label if label in TRAIN_EXTRA else "reject"
        negative = label if operation == "reject" else None
        if negative in {"missing", "cross_entity"}:
            negative = "prediction" if negative == "missing" else "external"
        language = (
            "zh"
            if any("\u3400" <= character <= "\u9fff" for character in value)
            else "en"
        )
        rows.append(
            {
                "id": f"{split}:{family_prefix}:{label}:{index:03}",
                "family": f"{family_prefix}:{label}:{language}",
                "split": split,
                "text": normalize(value),
                "operation": operation,
                "negative_group": negative,
                "language": language,
                "authorship": "V7 addressing author; public synthetic language",
            }
        )


def corpora():
    from v6.training_language import corpus as old_corpus

    result = {name: [] for name in ("train", "selection", "calibration")}
    for split in ("train", "selection"):
        for row in old_corpus(split):
            result[split].append(
                {
                    **row,
                    "id": "v6-public:" + row["id"],
                    "family": "v6-public:" + row["operation"] + ":" + row["language"],
                    "split": split,
                }
            )
    for label, packed in TRAIN_EXTRA.items():
        add(result["train"], packed, "train", label, "contrast")
    for label, packed in NEGATIVE_TRAIN.items():
        add(result["train"], packed, "train", label, "unsupported-composition")
    for label, packed in SELECTION_EXTRA.items():
        add(result["selection"], packed, "selection", label, "selection-new")
    for label, packed in CALIBRATION_KNOWN.items():
        add(result["calibration"], packed, "calibration", label, "calibration-known")
    for label, packed in CALIBRATION_REJECT.items():
        add(
            result["calibration"],
            packed,
            "calibration",
            label,
            "calibration-unsupported",
        )
    seen = {}
    for split, rows in result.items():
        for row in rows:
            key = normalize(row["text"])
            if key in seen:
                raise ValueError(
                    "duplicate language across declared partitions: "
                    + repr((seen[key], row["id"], key))
                )
            seen[key] = row["id"]
    return result
