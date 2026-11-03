"""Reject explicit operations outside the registered six-operation contract.

This layer never chooses a positive intent. It checks requested unsupported
actions, answer arity, temporal versions and subtraction orientation before
statistical intent selection. Entity names are removed by owner resolution.
"""

import re

from .contracts import normalize


FORBIDDEN = {
    "mutation": r"\b(?:delete|erase|overwrite|rewrite|amend|update|modify|replace|append|insert|remove|clear|edit|train)\b|删除|清空|改写|覆盖|更新|修改|替换|新增|增补|移除|写入|训练",
    "prediction-or-missing-data": r"\b(?:forecast|predict|prediction|extrapolate|extrapolation|interpolate|interpolation|guess|estimate|estimating|invent)\b|预测|推断|外推|插值|插补|猜测|猜|估算|估计|编造|发明",
    "unregistered-arithmetic": r"\b(?:logarithm|logarithmic|square|squared|squaring|sqrt|cosine|sine|tangent|reciprocal|ratio|quotient|divide|division|percentage|percent|modulo|modulus|exponential|variance|median|average|mean|standard deviation|rolling|trend|maximum|minimum|highest ever|lowest ever)\b|对数|平方|开方|倒数|比率|比例|比值|相除|除以|百分比|百分数|指数|方差|中位数|平均|标准差|趋势|最大值|最小值|最高读数|最低读数",
    "explanation-or-external": r"\b(?:why|explain|explanation|prove|justify|cause|caused|internet|search the web|different user|another user|another account|all users|outside this scope|different workspace)\b|为什么|为何|解释|论证|证明|原因|互联网|网络搜索|另一个用户|其他用户|所有用户|另一个账户|别人的|跨工作区",
}
NEGATION = re.compile(
    r"\b(?:not|never|without|avoid|don't|do not|doesn't|no need to|rather than|instead of)\b|不要|不做|不必|不需要|无需|不用|别|而不是|不要求"
)
CONTRAST = re.compile(r"\b(?:but|however|instead|then|also)\b|但是|而是|然后|并且|再")


def negated(text, start):
    prefix = text[max(0, start - 100) : start]
    prefix = re.split(r"[.;!?。；！？]", prefix)[-1]
    prefix = CONTRAST.split(prefix)[-1]
    matches = list(NEGATION.finditer(prefix))
    if not matches:
        return False
    tail = prefix[matches[-1].end() :]
    # A bounded grammatical scope handles e.g. "without calculating a mean"
    # and "不要预测，只读取最新值". Distant negation is not an authorization.
    return len(tail) <= 55 and len(tail.split()) <= 8


def active_matches(pattern, value):
    return [
        match
        for match in re.finditer(pattern, value)
        if not negated(value, match.start())
    ]


def capability_violation(value):
    value = normalize(value)
    for name, pattern in FORBIDDEN.items():
        if active_matches(pattern, value):
            return "unregistered-capability:" + name
    counterfactual = r"\b(?:what if|as if|suppose|assuming|pretend|counterfactual)\b|\bif\b.{0,90}\b(?:were|had been|changed|different|replaced|doubled|zero)\b|如果|假如|假定|假设|假装|反事实"
    if active_matches(counterfactual, value):
        return "unregistered-capability:counterfactual"
    arity = r"\b(?:two|three|multiple|separate|independent|both)\s+(?:(?:separate|independent|different)\s+)?(?:outputs|answers|results)\b|(?:两个|三个|多个)(?:独立的?|不同的?|分开的?)?(?:输出|答案|结果)|分别(?:输出|返回|列出|给出)"
    if active_matches(arity, value):
        return "unregistered-capability:multiple-outputs"
    temporal_property = r"\b(?:factor|coefficient|semantic attribute|semantic record|category|property)\b.{0,60}\b(?:historical time|historical date|old version|past date|as of|that .{0,15} had)\b|\b(?:old|former|historical)\b.{0,30}\b(?:factor|coefficient|semantic attribute|semantic record|program|procedure|recipe)\b|(?:过去|历史|旧|以前).{0,20}(?:系数|语义属性|语义记录|程序|流程|过程)|(?:系数|语义属性|语义记录).{0,20}(?:历史时间|过去时间|旧时刻|旧时点|历史版本)"
    if active_matches(temporal_property, value):
        return "unregistered-capability:historical-property-or-program"
    historical_apply = r"\b(?:apply|execute|run|use)\b.{0,70}\b(?:old|past|historical|earlier)\b.{0,20}\b(?:observation|reading|event|input)\b|(?:运行|应用|执行|处理).{0,40}(?:旧事件|过去的事件|历史事件|旧输入|历史观测|较早观测)|(?:旧事件|旧观测|历史观测|较早观测).{0,30}(?:执行|运行|配方|程序)"
    if active_matches(historical_apply, value):
        return "unregistered-capability:historical-procedure-input"
    past_pair = r"\b(?:between|compare|difference|subtract|delta)\b.{0,65}\b(?:two past|two historical|two earlier|two old|first historical)\b|\b(?:two historical|two past|two old)\b.{0,50}\b(?:difference|change|delta|subtract)\b|两个.{0,10}(?:过去|历史|旧).{0,30}(?:差|变化|相减)|两个.{0,10}(?:历史|旧).{0,10}(?:截止|时间|快照)|最早两条.{0,20}(?:差|相减)"
    if active_matches(past_pair, value):
        return "unregistered-capability:two-historical-endpoints"
    reverse_difference = r"\b(?:historical|old|earlier|past)\b.{0,25}\b(?:minus|less)\b.{0,25}\b(?:latest|current|newest|present)\b|\bsubtract\b.{0,25}\b(?:latest|current|newest)\b.{0,25}\bfrom\b.{0,25}\b(?:historical|old|earlier|past)\b|(?:历史|过去|旧).{0,12}(?:减去|减|扣除).{0,12}(?:最新|当前|现在|新值)"
    if active_matches(reverse_difference, value):
        return "unregistered-capability:reverse-difference"
    return None
