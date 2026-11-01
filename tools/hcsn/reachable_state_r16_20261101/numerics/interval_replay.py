"""Directed-rounding replay for the exact integer-weight fixture, not expm.

This optional high-precision fallback deliberately lives outside the frozen
pure-Q24 implementation. No future observation or latent world state is read.
"""

from decimal import Context, Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
from decimal import Underflow, localcontext
import hashlib
import json

from .validate_q24 import SCALE, quantize_python


ZERO, ONE = Decimal(0), Decimal(1)
PRECISION = 80


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def signed_payload(value):
    body = dict(value)
    body["sha256"] = hashlib.sha256(canonical(value).encode()).hexdigest()
    return body


class IntervalModel:
    def __init__(self, source, precision=PRECISION):
        if precision != PRECISION:
            raise ValueError("This profile fixes 80-digit precision")
        self.precision = precision
        self.down = Context(prec=precision, rounding=ROUND_FLOOR)
        self.up = Context(prec=precision, rounding=ROUND_CEILING)
        self.near = Context(prec=precision, rounding=ROUND_HALF_EVEN)
        for context in (self.down, self.up, self.near):
            context.traps[Underflow] = True
        self.identity = hashlib.sha256(source).hexdigest()
        tokens = iter(source.decode("utf-8").split())
        if next(tokens) != "HCSN_Q24_MODEL_V1":
            raise ValueError("Unsupported fixture")
        self.source_identity = next(tokens)
        self.states, self.addresses, self.classes, transitions, emissions = (
            int(next(tokens)) for _ in range(5))
        if (not 1 <= self.states <= 512 or not 1 <= self.addresses <= 64
                or not 1 <= self.classes <= self.states
                or self.states % self.classes or not 0 <= transitions <= 256
                or not 0 <= emissions <= 64):
            raise ValueError("Invalid fixture dimensions")
        self.initial = self._matrix(tokens, self.addresses, self.states)
        self.ticks, self.transitions, self.emissions = [], [], []
        for _ in range(transitions):
            ticks = int(next(tokens))
            if not 0 <= ticks <= 2 ** 64 - 1:
                raise ValueError("Invalid ticks")
            self.ticks.append(ticks)
            self.transitions.append(self._matrix(tokens, self.states, self.states))
        for _ in range(emissions):
            columns = int(next(tokens))
            if not 1 <= columns <= 512:
                raise ValueError("Invalid observation alphabet")
            self.emissions.append(self._matrix(tokens, self.states, columns))
        if next(tokens, None) is not None:
            raise ValueError("Trailing fixture data")

    def _matrix(self, tokens, rows, columns):
        lower, upper, support = [], [], []
        for _ in range(rows):
            weights = [int(next(tokens)) for _ in range(columns)]
            if min(weights) < 0 or not sum(weights):
                raise ValueError("Invalid exact integer weights")
            denominator = Decimal(sum(weights))
            with localcontext(self.down):
                lower.append([Decimal(weight) / denominator for weight in weights])
            with localcontext(self.up):
                upper.append([Decimal(weight) / denominator for weight in weights])
            support.append([weight > 0 for weight in weights])
        return lower, upper, support


class IntervalMemory:
    def __init__(self, model):
        self.model = model
        self.lower, self.upper, self.support = ([row.copy() for row in matrix]
                                                for matrix in model.initial)
        self.completed, self.clock_ticks = 0, 0
        self._intersect_simplex()

    def _validate(self):
        for low, high, support in zip(self.lower, self.upper, self.support):
            if any(not lo.is_finite() or not hi.is_finite() or not ZERO <= lo <= hi <= ONE
                   or (not possible and (lo != ZERO or hi != ZERO))
                   for lo, hi, possible in zip(low, high, support)):
                raise ValueError("Invalid interval probability bounds")
            with localcontext(self.model.down):
                total_low = sum(low, ZERO)
            with localcontext(self.model.up):
                total_high = sum(high, ZERO)
            if not total_low <= ONE <= total_high:
                raise ValueError("Interval normalization is impossible")

    def _intersect_simplex(self):
        for key in range(self.model.addresses):
            low, high = self.lower[key], self.upper[key]
            with localcontext(self.model.down):
                sum_low = sum(low, ZERO)
            with localcontext(self.model.up):
                sum_high = sum(high, ZERO)
            if sum_low > ONE or sum_high < ONE:
                raise ArithmeticError("Interval lost normalized probability")
            next_low, next_high = [], []
            for index in range(self.model.states):
                other_high = self.model.up.subtract(sum_high, high[index])
                other_low = self.model.down.subtract(sum_low, low[index])
                lo = max(ZERO, low[index], self.model.down.subtract(ONE, other_high))
                hi = min(ONE, high[index], self.model.up.subtract(ONE, other_low))
                if (not lo.is_finite() or not hi.is_finite() or lo > hi
                        or (not self.support[key][index] and (lo != ZERO or hi != ZERO))):
                    raise ArithmeticError("Invalid probability enclosure")
                next_low.append(lo)
                next_high.append(hi)
            self.lower[key], self.upper[key] = next_low, next_high
        self._validate()

    def apply(self, operation):
        fields = operation.split()
        if fields[0] == "T" and len(fields) == 2:
            index = int(fields[1])
            if not 0 <= index < len(self.model.transitions):
                raise ValueError("Unknown transition")
            matrix_low, matrix_high, edges = self.model.transitions[index]
            next_bounds = []
            for values, matrix, context in ((self.lower, matrix_low, self.model.down),
                                            (self.upper, matrix_high, self.model.up)):
                columns = list(zip(*matrix))
                with localcontext(context):
                    next_bounds.append([[sum((p * rate for p, rate in zip(row, column)), ZERO)
                                         for column in columns] for row in values])
            self.lower, self.upper = next_bounds
            self.support = [[any(possible[i] and edges[i][j] for i in range(self.model.states))
                             for j in range(self.model.states)] for possible in self.support]
            self.clock_ticks += self.model.ticks[index]
        elif fields[0] == "O" and len(fields) == 4:
            key, emission_index, token = map(int, fields[1:])
            if not (0 <= key < self.model.addresses and 0 <= emission_index < len(self.model.emissions)):
                raise ValueError("Invalid observation")
            low_e, high_e, possible_e = self.model.emissions[emission_index]
            if not 0 <= token < len(low_e[0]):
                raise ValueError("Invalid observation token")
            with localcontext(self.model.down):
                lower = [value * low_e[index][token] for index, value in enumerate(self.lower[key])]
                evidence_lower = sum(lower, ZERO)
            with localcontext(self.model.up):
                upper = [value * high_e[index][token] for index, value in enumerate(self.upper[key])]
                evidence_upper = sum(upper, ZERO)
            if evidence_lower <= ZERO:
                raise ArithmeticError("Observation evidence lacks a positive interval lower bound")
            with localcontext(self.model.down):
                self.lower[key] = [value / evidence_upper for value in lower]
            with localcontext(self.model.up):
                self.upper[key] = [value / evidence_lower for value in upper]
            self.support[key] = [possible and possible_e[index][token]
                                 for index, possible in enumerate(self.support[key])]
        elif fields[0] == "W" and len(fields) == 3:
            key, content = map(int, fields[1:])
            if not 0 <= key < self.model.addresses or not 0 <= content < self.model.classes:
                raise ValueError("Invalid public write")
            classes = self.model.classes
            for values, context in ((self.lower, self.model.down), (self.upper, self.model.up)):
                with localcontext(context):
                    phase = [sum(values[key][i:i + classes], ZERO)
                             for i in range(0, self.model.states, classes)]
                values[key] = [ZERO] * self.model.states
                values[key][content::classes] = phase
            phases = [any(self.support[key][i:i + classes])
                      for i in range(0, self.model.states, classes)]
            self.support[key] = [False] * self.model.states
            self.support[key][content::classes] = phases
        else:
            raise ValueError("Unsupported event")
        self.completed += 1
        if self.completed >= 2 ** 64 or self.clock_ticks >= 2 ** 64:
            raise OverflowError("Native counter range exceeded")
        self._intersect_simplex()

    def radii(self, counts):
        radii = []
        with localcontext(self.model.up):
            for row, lower, upper in zip(counts, self.lower, self.upper):
                if len(row) != self.model.states or min(row) < 0 or sum(row) != SCALE:
                    raise ValueError("Invalid Q24 center")
                center = [Decimal(value) / Decimal(SCALE) for value in row]
                error = sum((max(point - lo, hi - point)
                             for point, lo, hi in zip(center, lower, upper)), ZERO)
                radii.append(min(2 * SCALE, int((error * SCALE).to_integral_value(rounding=ROUND_CEILING))))
        return radii

    def quantized(self, maximum_error):
        counts = []
        for lower, upper in zip(self.lower, self.upper):
            with localcontext(self.model.near):
                midpoint = [(lo + hi) / 2 for lo, hi in zip(lower, upper)]
            exponent = max(0, max(-value.as_tuple().exponent for value in midpoint))
            weights = []
            for value in midpoint:
                parts = value.as_tuple()
                coefficient = int("".join(map(str, parts.digits)))
                weights.append(coefficient * 10 ** (parts.exponent + exponent))
            counts.append(quantize_python(weights)[0])
        radii = self.radii(counts)
        if max(radii) > maximum_error:
            raise ArithmeticError("Interval fallback still exceeds fixed precision budget")
        return dict(completed=self.completed, clock_ticks=self.clock_ticks,
                    counts=counts, support=[row.copy() for row in self.support], l1_bound_units=radii)

    def export(self):
        return signed_payload(dict(schema="hcsn-r16-interval-cache-v1", model=self.model.identity,
            precision=self.model.precision, completed=self.completed, clock_ticks=self.clock_ticks,
            lower=[[str(value) for value in row] for row in self.lower],
            upper=[[str(value) for value in row] for row in self.upper], support=self.support))

    @classmethod
    def restore(cls, model, payload):
        body = dict(payload)
        checksum = body.pop("sha256", None)
        if checksum != hashlib.sha256(canonical(body).encode()).hexdigest():
            raise ValueError("Interval cache checksum mismatch")
        if (body["schema"] != "hcsn-r16-interval-cache-v1" or body["model"] != model.identity
                or body["precision"] != model.precision):
            raise ValueError("Interval cache model/schema/precision mismatch")
        result = cls(model)
        for name in ("completed", "clock_ticks"):
            if type(body[name]) is not int or not 0 <= body[name] < 2 ** 64:
                raise ValueError("Invalid cache counter")
            setattr(result, name, body[name])
        for name in ("lower", "upper", "support"):
            matrix = body[name]
            if len(matrix) != model.addresses or any(len(row) != model.states for row in matrix):
                raise ValueError("Invalid interval dimensions")
            if name == "support":
                if any(type(value) is not bool for row in matrix for value in row):
                    raise ValueError("Invalid support type")
                setattr(result, name, [row.copy() for row in matrix])
            else:
                setattr(result, name, [[Decimal(value) for value in row] for row in matrix])
        result._validate()
        return result
