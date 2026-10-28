"""Explicit negative contracts for operations the six-operation ABI cannot do.

These checks never select a positive operation or inspect entity values. They
recognize requested output arity, temporal direction, parameter substitution,
cross-owner composition and side effects. Learned heads choose among the
remaining execution hypotheses. The inherited bounded negation scope applies.
"""

import re

from addressing.capabilities import active_matches, negated
from addressing.capabilities import capability_violation as previous_violation
from addressing.contracts import normalize


RULES = (
    ("unregistered-scalar-transform",
     r"\b(?:absolute (?:size|value|difference|change)|magnitude|twice (?:as|that)|half of|per hundred|how many times)\b|\b(?:double|halve)\b|绝对(?:值|大小|差)|去掉正负号|翻一番|扩大为两倍|一半|每一百|几倍"),
    ("forward-event-selection",
     r"\bfirst\b.{0,80}\b(?:after|following)\b|\b(?:strictly after|earliest after)\b|(?:以后|之后|晚于).{0,30}(?:第一|首个|最早)|(?:第一|首个).{0,50}(?:晚于|以后|之后)"),
    ("historical-property-or-program",
     r"\b(?:label|tag|factor|coefficient|attribute|property|recipe|routine|program)\b.{0,90}\b(?:historical|old version|past cutoff|past instant|prior revision|previous revision)\b|\b(?:historical|past|previous|former|old)\b.{0,65}\b(?:label|tag|factor|coefficient|attribute|property|recipe|routine|program)\b|(?:历史|过去|旧|以前|修订之前).{0,45}(?:标签|类别|属性|系数|因子|配方|流程|例程|程序)|(?:标签|类别|属性|系数|因子|配方|流程|例程|程序).{0,35}(?:历史截止|过去时点|旧版本|修订之前)"),
    ("reverse-event-difference",
     r"\b(?:earlier|old|historical|past)\b.{0,35}\b(?:less|minus)\b.{0,35}\b(?:latest|current|newest|present)\b|(?:较早|以前|历史|旧).{0,20}(?:减|扣除).{0,20}(?:最新|当前|现在)"),
    ("causal-or-explanatory-answer",
     r"\b(?:brought about|led to|responsible for|driver behind|mechanism behind|circumstances that)\b|(?:带来|导致|造成).{0,30}(?:条件|因素|机制)|(?:什么|哪些).{0,30}(?:带来|导致|造成)|(?:由什么|是如何).{0,30}(?:带来|决定|产生)|背后.{0,15}(?:机制|推动因素)"),
    ("future-or-missing-observation",
     r"\bnext (?:value|reading|sample|observation|coefficient)\b|\b(?:likely to|probably have|missing event|missing observation)\b|(?:接下来|下一次|将来).{0,30}(?:值|读数|记录|样本|系数)|(?:填补|补出).{0,30}(?:缺失|从未记录)"),
    ("requested-memory-mutation",
     r"(?:^|[.;!?]\s*|\b(?:then|and|please|to)\s+)(?:store|persist|discard|forget|rename)\b|\bsave\b.{0,55}\b(?:new|fresh|different|output)\b|\b(?:then|afterwards|and)\s+(?:increment|decrement|increase|decrease)\b.{0,40}\b(?:saved|stored)\b|(?:丢弃|忘掉|重命名|设置新)|(?:把|将).{0,60}(?:保存|存入|持久化).{0,20}(?:新|另一)(?:的)?(?:事件|观测|样本)|(?:然后|接着|再).{0,12}(?:增加|减少|调大|调小).{0,20}(?:保存|已存|存储)"),
    ("external-or-cross-entity-input",
     r"\b(?:another|other|different)\b.{0,25}\b(?:entity|owner)\b|\b(?:web|online source|external database)\b|(?:另一个|另一|其他|不同).{0,12}(?:实体|所有者)|(?:上网|外部数据库|网上)"),
    ("multiple-record-output",
     r"\b(?:enumerate|list)\b.{0,30}\b(?:history|events|observations|samples|versions)\b|\b(?:every|all)\b.{0,30}\b(?:versions|events|observations|samples)\b|\b(?:return|give|fetch|show)\b.{0,15}\bboth\b.{0,90}\band\b|(?:枚举|列出).{0,35}(?:事件|观测|历史|版本)|(?:每一个|所有|全部).{0,20}(?:旧版本|历史事件)|(?:同时|分别)(?:返回|给出|展示).{0,70}(?:和|与|以及)|(?:事件|观测|读数).{0,25}(?:和|与|以及).{0,25}(?:语义|属性|流程|程序).{0,15}(?:同时|分别)(?:返回|给出|展示)|(?:语义|属性|流程|程序).{0,25}(?:和|与|以及).{0,25}(?:事件|观测|读数).{0,15}(?:同时|分别)(?:返回|给出|展示)"),
    ("substituted-or-repeated-procedure",
     r"\b(?:input|coefficient|factor)\b.{0,30}\b(?:chosen|supplied|specified) by (?:this|the) (?:request|message)\b|\b(?:use|with)\s+-?\d+(?:\.\d+)?\b.{0,35}\b(?:input|instead of)\b|\b(?:twice in succession|two times|two successive|program twice|routine twice)\b|(?:本请求|本消息|这条消息).{0,20}(?:指定|给出|选择).{0,15}(?:数|输入|系数)|用-?\d+.{0,20}(?:替代|代替|作输入)|(?:连续|执行|运行).{0,15}(?:两次|两遍|二次)"),
)


def capability_violation(value):
    text = normalize(value)
    text = re.sub(r"不许|禁止|不准|勿", "不要", text)
    text = re.sub(r"不(执行|运行|采用|使用|返回|读取|检索|展示|计算)", r"不要\1", text)
    previous = previous_violation(text)
    if previous is not None:
        return previous
    for name, pattern in RULES:
        if any(not negated(text, match.end() - 1) for match in active_matches(pattern, text)):
            return "unregistered-capability:" + name
    return None
