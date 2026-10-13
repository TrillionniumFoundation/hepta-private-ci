"""Closed, loop-free decision IR -> bounded CPU JIT, for offline qualification.

No raw LLVM/machine-code input, arbitrary pointer, syscall, file, network or GUI
operation is accepted. The result is an integer action *proposal*, never an
execution grant. This is not a sandbox for arbitrary native programs. Production
integration remains the existing Worker/Final-use owner, not this research class.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
import ctypes
import hashlib
import json
import inspect
import math
import statistics
import time


@dataclass(frozen=True)
class Rule:
    weights: tuple[float, ...]
    threshold: float
    action: int


@dataclass(frozen=True)
class DecisionIR:
    width: int
    rules: tuple[Rule, ...]
    default_action: int

    def validate(self):
        def scalar(x):
            return type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1000
        def action(x):
            return type(x) is int and 0 <= x <= 65535
        if (type(self.width) is not int or not 1 <= self.width <= 64
                or type(self.rules) is not tuple or not 1 <= len(self.rules) <= 64
                or not action(self.default_action)):
            raise ValueError("invalid closed decision IR")
        for rule in self.rules:
            if (type(rule) is not Rule or type(rule.weights) is not tuple
                    or len(rule.weights) != self.width or not all(map(scalar, rule.weights))
                    or not scalar(rule.threshold) or not action(rule.action)):
                raise ValueError("invalid bounded affine/select instruction")

    def canonical_bytes(self):
        self.validate()
        return json.dumps({"schema": "hepta.research.decision-ir.v1", **asdict(self)},
                          sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checked_values(width, values):
    """Check every dynamic input; static IR validation belongs to admission."""
    if (type(values) is not tuple or len(values) != width
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1000 for v in values)):
        raise ValueError("invalid bounded numeric inputs")


def checked_inputs(program, values):
    if type(program) is not DecisionIR:
        raise ValueError("typed decision IR required")
    program.validate()
    checked_values(program.width, values)


def _interpret_validated(program, values):
    for rule in program.rules:
        value = 0.0
        for weight, x in zip(rule.weights, values):
            value = value + float(weight) * float(x)
        if value >= rule.threshold:
            return rule.action
    return program.default_action


def interpret(program, values):
    checked_inputs(program, values)
    return _interpret_validated(program, values)


class PreparedDecision:
    """Strong typed control: admits static IR once, validates ALL new inputs.

    This is a private-process immutable program snapshot, not an authorization
    token or a sandbox against arbitrary Python/ctypes access in the process.
    """

    __slots__ = ("_program",)

    def __init__(self, program):
        if type(program) is not DecisionIR:
            raise ValueError("typed decision IR required")
        program.validate()
        self._program = deepcopy(program)

    @property
    def program(self):
        # A caller cannot resize the input buffer by replacing the public IR.
        return deepcopy(self._program)

    def __call__(self, values):
        checked_values(self._program.width, values)
        return _interpret_validated(self._program, values)

    def _check_batch(self, observations):
        if type(observations) is not tuple or not 1 <= len(observations) <= 32:
            raise ValueError("decision batch must contain 1..32 rows")
        for values in observations:
            checked_values(self._program.width, values)

    def run_batch(self, observations):
        self._check_batch(observations)
        return tuple(_interpret_validated(self._program, row) for row in observations)


class _CompiledDecision(PreparedDecision):
    __slots__ = ("_engine", "_function", "_batch_function", "manifest")

    def __init__(self, program, engine, address, batch_address, manifest):
        super().__init__(program)
        self._engine = engine  # Keep allocations alive even after cache eviction.
        f64ptr = ctypes.POINTER(ctypes.c_double)
        self._function = ctypes.CFUNCTYPE(ctypes.c_int32, f64ptr)(address)
        self._batch_function = ctypes.CFUNCTYPE(
            ctypes.c_int32, f64ptr, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))(batch_address)
        self.manifest = manifest

    def __call__(self, values):
        # New inputs are always checked, including nonfinite/type/size/range.
        checked_values(self._program.width, values)
        array = (ctypes.c_double * self._program.width)(*values)
        return int(self._function(array))

    def run_batch(self, observations):
        # Whole-batch preflight precedes ANY native execution, then one FFI call.
        self._check_batch(observations)
        array = (ctypes.c_double * (len(observations) * self._program.width))(
            *(v for row in observations for v in row))
        outputs = (ctypes.c_int32 * len(observations))()
        if self._batch_function(array, len(observations), outputs) != 0:
            raise RuntimeError("bounded native decision batch rejected")
        return tuple(outputs)


class NativeDecisionCache:
    """Bounded process-local trusted compilation cache; not an artifact CAS.

    The object bytes are observed only for digest/size. This class never accepts
    serialized compiled objects, and never treats a content digest as authority.
    """

    def __init__(self, *, capacity=8):
        if type(capacity) is not int or not 1 <= capacity <= 16:
            raise ValueError("invalid compile cache capacity")
        import llvmlite
        from llvmlite import binding
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
        binding.check_jit_execution()
        self._binding = binding
        self.capacity = capacity
        self._cache = OrderedDict()
        self.compilations = self.hits = 0
        self.profile = {"llvmlite": llvmlite.__version__, "llvm": binding.llvm_version_info,
                        "triple": binding.get_default_triple(), "cpu": str(binding.get_host_cpu_name()),
                        "features": binding.get_host_cpu_features().flatten(),
                        "lowering_sha256": hashlib.sha256(inspect.getsource(_lower).encode()).hexdigest(),
                        "abi": "f64-pointer-to-i32-batch32-v2", "fast_math": False}

    def compile(self, program):
        if type(program) is not DecisionIR:
            raise ValueError("typed decision IR required")
        program.validate()
        program = deepcopy(program)
        key = hashlib.sha256(program.canonical_bytes() + json.dumps(
            self.profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if key in self._cache:
            self.hits += 1
            self._cache.move_to_end(key)
            return self._cache[key], True
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        binding = self._binding
        target = binding.Target.from_triple(self.profile["triple"])
        machine = target.create_target_machine(cpu=self.profile["cpu"], features=self.profile["features"], opt=2)
        text = _lower(program, self.profile["triple"], str(machine.target_data))
        module = binding.parse_assembly(text)
        module.verify()
        objects = []
        engine = binding.create_mcjit_compiler(module, machine)
        engine.set_object_cache(lambda module_ref, data: objects.append(bytes(data)))
        engine.finalize_object()
        address = engine.get_function_address("hepta_decision")
        batch_address = engine.get_function_address("hepta_decision_batch")
        if not address or not batch_address or not objects:
            raise RuntimeError("native compilation produced no callable/object receipt")
        manifest = {"cache_key": key, "ir_sha256": hashlib.sha256(program.canonical_bytes()).hexdigest(),
                    "llvm_ir_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "object_sha256": [hashlib.sha256(b).hexdigest() for b in objects],
                    "object_bytes": sum(map(len, objects)), "profile": dict(self.profile),
                    "compile_cpu_ns": time.process_time_ns() - start_cpu,
                    "compile_wall_ns": time.perf_counter_ns() - start_wall,
                    "production_authorized": False, "effects_permitted": False}
        compiled = _CompiledDecision(program, engine, address, batch_address, manifest)
        self.compilations += 1
        self._cache[key] = compiled
        while len(self._cache) > self.capacity:
            self._cache.popitem(last=False)
        return compiled, False


def _lower(program, triple, layout):
    """Construct LLVM from typed bounded operations, never parse model text."""
    from llvmlite import ir
    program.validate()
    module = ir.Module(name="hepta_closed_decision")
    module.triple, module.data_layout = triple, layout
    f64, i32 = ir.DoubleType(), ir.IntType(32)
    function = ir.Function(module, ir.FunctionType(i32, [f64.as_pointer()]), name="hepta_decision")
    block = function.append_basic_block("entry")
    builder = ir.IRBuilder(block)
    for index, rule in enumerate(program.rules):
        value = ir.Constant(f64, 0.0)
        for column, weight in enumerate(rule.weights):
            ptr = builder.gep(function.args[0], [ir.Constant(i32, column)], inbounds=True)
            product = builder.fmul(builder.load(ptr), ir.Constant(f64, float(weight)))
            value = builder.fadd(value, product)
        accepted = function.append_basic_block(f"accepted_{index}")
        following = function.append_basic_block(f"next_{index}")
        condition = builder.fcmp_ordered(">=", value, ir.Constant(f64, float(rule.threshold)))
        builder.cbranch(condition, accepted, following)
        builder.position_at_end(accepted)
        builder.ret(ir.Constant(i32, rule.action))
        builder.position_at_end(following)
    builder.ret(ir.Constant(i32, program.default_action))
    # The only loop is compiler-emitted, with a hard maximum of 32 rows.
    batch = ir.Function(module, ir.FunctionType(i32, [f64.as_pointer(), i32, i32.as_pointer()]),
                        name="hepta_decision_batch")
    entry, loop, step, done, rejected = [batch.append_basic_block(name)
                                       for name in ("entry", "loop", "step", "done", "rejected")]
    b = ir.IRBuilder(entry)
    allowed = b.and_(b.icmp_signed(">=", batch.args[1], ir.Constant(i32, 1)),
                     b.icmp_signed("<=", batch.args[1], ir.Constant(i32, 32)))
    b.cbranch(allowed, loop, rejected)
    b.position_at_end(rejected)
    b.ret(ir.Constant(i32, -1))
    b.position_at_end(loop)
    row = b.phi(i32, "row")
    row.add_incoming(ir.Constant(i32, 0), entry)
    offset = b.mul(row, ir.Constant(i32, program.width))
    result = b.call(function, [b.gep(batch.args[0], [offset], inbounds=True)])
    b.store(result, b.gep(batch.args[2], [row], inbounds=True))
    b.branch(step)
    b.position_at_end(step)
    next_row = b.add(row, ir.Constant(i32, 1))
    row.add_incoming(next_row, step)
    b.cbranch(b.icmp_signed("<", next_row, batch.args[1]), loop, done)
    b.position_at_end(done)
    b.ret(ir.Constant(i32, 0))
    return str(module)


def benchmark_fixed_policy(program, observations, *, repeats=100, warmup=5):
    """Alternating matched observation order, cold compile separate, no padding.

    JSON roundtrip is an in-process serialization CONTROL, NOT an MCP server.
    Native and typed paths include wrapper validation and marshalling. No GUI,
    GPU or Wasm execution is implied. Returned timings are local, unsigned.
    """
    if (type(observations) is not tuple or not 1 <= len(observations) <= 256
            or type(repeats) is not int or not 2 <= repeats <= 10000
            or type(warmup) is not int or not 0 <= warmup <= 100):
        raise ValueError("invalid matched benchmark")
    for observation in observations:
        checked_inputs(program, observation)
    cache = NativeDecisionCache()
    compiled, _ = cache.compile(program)
    def serialized(values):
        payload = json.dumps(values, allow_nan=False, separators=(",", ":"))
        return interpret(program, tuple(json.loads(payload)))
    backends = {"typed_reference": lambda v: interpret(program, v),
                "json_roundtrip_control_not_mcp": serialized, "cpu_native": compiled}
    expected = tuple(interpret(program, o) for o in observations)
    for backend in backends.values():
        for _ in range(warmup):
            for observation in observations:
                backend(observation)
    times = {name: [] for name in backends}
    names = tuple(backends)
    for repeat in range(repeats):
        ordered = names if repeat % 2 == 0 else tuple(reversed(names))
        for name in ordered:
            for row, observation in enumerate(observations):
                start = time.perf_counter_ns()
                action = backends[name](observation)
                elapsed = time.perf_counter_ns() - start
                times[name].append(elapsed)
                if action != expected[row]:
                    raise RuntimeError("same-policy native semantic mismatch")
    def summary(samples):
        ordered = sorted(samples)
        return {"count": len(samples), "p50_ns": statistics.median(ordered),
                "p95_ns": ordered[math.ceil(0.95 * len(ordered))-1],
                "p99_ns": ordered[math.ceil(0.99 * len(ordered))-1]}
    reports = {name: summary(samples) for name, samples in times.items()}
    saving = reports["typed_reference"]["p50_ns"] - reports["cpu_native"]["p50_ns"]
    return {"timings": reports, "raw_timings_ns": times, "compiled": compiled.manifest,
            "warmup_calls_per_backend": warmup * len(observations), "all_actions_equal": True,
            "observation_digest": hashlib.sha256(json.dumps(observations, allow_nan=False).encode()).hexdigest(),
            "amortization_calls_p50": math.ceil(compiled.manifest["compile_wall_ns"] / saving) if saving > 0 else None,
            "mcp_status": "not_run", "wasm_status": "not_run", "gpu_status": "not_run",
            "computer_use_e2e_status": "not_run", "production_authorized": False}
