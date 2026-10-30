"""Context-reconstructed seed-producer adapter; isolated metadata APIs only.

Fixed source SHAs and exact-once AST expressions bound every specialization.
Original modules, numerical code objects, scientific seals and state bytes remain.
"""

import ast
import copy
from pathlib import Path
import types
from operational.parameter_field_recovery05 import ancestry

require = ancestry.require
MODULE_SHA = {
    "run_v2": "291218547484a01ac0213c06f1b6bbd16104955348b818014a66f4d3a0ce3561",
    "analysis_launch_v2": "708003e123a97dbf17f8ba1fd2f7086ec70fc52f2f6a1dc41bf88c6882d4fdbb",
    "register_followups_v2": "915e7a012b321add3db081367796c0d8eb22555a5bd429da8ebc8c99828b9112",
    "endpoint_v2": "0780cf261944dbdb6a47597c1294f4f9c9f761e3131d4a76e51b634cf7f15da2",
    "register_summary_v2": "b20351ee0a242bf25352d67a912af3a3dcb6d7503c8e38f9973a437bb3d20184",
    "report_results": "ccfe0f9fa555906f9cda0834424a5396c7146f523a47a4cd8696134d007e614f",
    "finalize_v2": "6fbf4a7a994120b6c0ae577a10d9ba992ad483d253ff0afb9aea42af8bb705ac",
    "postseal_supplement": "1b705285b99fc7185c20155fa85f3a5d370b473196eaf59c8ae1d6bb2941a633",
}
REWRITES = {
    "analysis_launch_v2": {"child": [('importlib.import_module(freeze["report_module"])',
        '_producer.for_report(importlib.import_module(freeze["report_module"]))')]},
    "register_followups_v2": {
        "register": [('matching and all(r["freeze_sha256"] == parents[phase]["sha256"] and Path(arguments(r["argv"])["--freeze"]).resolve() == Path(parents[phase]["path"]).resolve() for r in matching)',
            '_producer.training_jobs_match(matching, parents[phase], phase)'),
            ('freeze.get("actual_source_A") == parents["A"]', '_producer.followup_parent_matches(freeze, parents["A"])')],
        "diagnostic_population": [('replay["source_stage_identity"]["source_freeze_sha256"] == sources["A"]["sha256"]',
            'replay["source_stage_identity"]["source_freeze_sha256"] == _producer.source(seed)["sha256"]')]},
    "register_summary_v2": {
        "source_closure": [('list(freeze.get("training_parents", {}).values())',
            'list(freeze.get("training_parents", {}).values()) + _producer.additional_parents(freeze)')],
        "collect": [('read(root / "controller" / (job["id"] + ".START.json"))["job"] == job',
            '_producer.controller_start_matches(root, job, result, read)'),
            ('all(j["freeze_sha256"] == training["sha256"] and Path(arguments(j["argv"])["--freeze"]).resolve() == Path(training["path"]).resolve() for j in matches)',
            '_producer.training_jobs_match(matches, training, phase, freeze)'),
            ('operation.get("operational_amendment_sha256") == registration["_sha256"]',
            '_producer.operation_profile_matches(operation, phase, job.get("seed"), registration)')]},
    "report_results": {"assemble": [('all(op["operational_amendment_sha256"] == amendment["sha256"] for op in operations.values())',
        '_producer.report_profiles(operations, spec)')]},
    "postseal_supplement": {"gate": [('op.get("operational_amendment_sha256") == binding["operational_amendment_sha256"]',
        '_producer.postseal_profile(op, phase, seed, store, binding)')]},
}


def isolated_module(module, owner):
    name = Path(module.__file__).stem
    require(name in MODULE_SHA, "Unregistered adapter module")
    ancestry.hash_checked(Path(module.__file__).resolve(), MODULE_SHA[name])
    namespace = types.ModuleType(module.__name__)
    namespace.__dict__.update(module.__dict__)
    namespace._producer = owner
    for key, value in module.__dict__.items():
        if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__:
            cloned = types.FunctionType(value.__code__, namespace.__dict__, value.__name__, value.__defaults__, value.__closure__)
            cloned.__kwdefaults__, cloned.__annotations__, cloned.__doc__ = value.__kwdefaults__, value.__annotations__, value.__doc__
            namespace.__dict__[key] = cloned
    definitions = {node.name: node for node in ast.parse(Path(module.__file__).read_text()).body if isinstance(node, ast.FunctionDef)}
    audit = {}
    for function, replacements in REWRITES.get(name, {}).items():
        target = copy.deepcopy(definitions[function])
        for previous, replacement in replacements:
            expected = ast.dump(ast.parse(previous, mode="eval").body, include_attributes=False)
            new, matches = ast.parse(replacement, mode="eval").body, []
            class ReplaceExact(ast.NodeTransformer):
                def visit(self, node):
                    if ast.dump(node, include_attributes=False) == expected:
                        matches.append(node)
                        return ast.copy_location(copy.deepcopy(new), node)
                    return super().visit(node)
            target = ReplaceExact().visit(target)
            require(len(matches) == 1, "Frozen metadata expression missing/duplicated: " + function)
        ast.fix_missing_locations(target)
        exec(compile(ast.Module(body=[target], type_ignores=[]), str(Path(__file__)) + "::" + name + "." + function, "exec"), namespace.__dict__)
        audit[function] = {"original_source_sha256": MODULE_SHA[name], "metadata_expressions_replaced": len(replacements)}
    namespace.producer_adapter_audit = audit
    return namespace


class ProducerAdapter:
    def __init__(self, map_descriptor, import_receipt_descriptor, fresh_registration):
        self.map_descriptor, self.import_receipt = copy.deepcopy(map_descriptor), copy.deepcopy(import_receipt_descriptor)
        self.mapping = ancestry.archive.read(ancestry.checked(map_descriptor))
        require(self.mapping == ancestry.producer_map(import_receipt_descriptor, fresh_registration),
                "External producer map differs from independently validated ancestry")
        self.raw = Path(fresh_registration["raw_root"])
        self.current_profile, self.old_profile = self.mapping["29"]["profile"], self.mapping["17"]["profile"]
        self.receipt = ancestry.archive.read(ancestry.checked(self.import_receipt))
        self.profiles = {}
        for seed in (17, 29, 43):
            item = self.mapping[str(seed)]["profile"]
            self.profiles[seed] = {**ancestry.archive.read(ancestry.checked(item)), "_sha256": item["sha256"]}
        from operational.parameter_field_recovery05.controller import ControllerCore
        self.controller = ControllerCore(import_receipt_descriptor)

    def source(self, seed):
        require(type(seed) is int and seed in (17, 29, 43), "Unknown A producer seed")
        row = self.mapping[str(seed)]
        return {**row["source_freeze"], "registered_commit": row["registered_commit"],
                "protocol_sha256": row["protocol_sha256"], "source_root": row["source_root"]}

    def source_map(self):
        return {str(seed): self.source(seed) for seed in (17, 29, 43)}

    def require_current(self, registration):
        require(registration["_sha256"] == self.current_profile["sha256"] and registration["raw_root"] == str(self.raw),
                "Adapter invoked with another current registration")

    def require_bound(self, freeze):
        require(freeze.get("producer_map") == self.map_descriptor and freeze.get("actual_sources_A_by_seed") == self.source_map(),
                "Freeze does not bind full actual A producer map")
        require(freeze.get("artifacts", {}).get(self.map_descriptor["path"]) == self.map_descriptor["sha256"]
                and freeze["artifacts"].get(self.import_receipt["path"]) == self.import_receipt["sha256"], "Unfrozen producer/import artifacts")
        ancestry.checked(self.map_descriptor)
        ancestry.checked(self.import_receipt)

    def bind_freeze(self, value):
        result = copy.deepcopy(value)
        result["producer_map"], result["actual_sources_A_by_seed"] = self.map_descriptor, self.source_map()
        result["actual_source_A_scope"] = "Primary execution05 A producer; complete seed map includes imported execution04 A17."
        for item in (self.map_descriptor, self.import_receipt, self.old_profile, self.mapping["17"]["source_freeze"]):
            require(item["path"] not in result["artifacts"] or result["artifacts"][item["path"]] == item["sha256"], "Conflicting producer artifact")
            result["artifacts"][item["path"]] = item["sha256"]
        return result

    def encoding(self, original):
        def encode(value):
            if isinstance(value, dict) and value.get("schema") == "hepta.fullstudy.source-freeze.1":
                value = self.bind_freeze(value)
                if value.get("execution_kind") == "evidence_finalization":
                    require(value.get("evidence_id", "verification05") == "verification05"
                            and value.get("evidence_relative", "evidence_v2/verification05") == "evidence_v2/verification05",
                            "Finalizer destination cannot drift from execution05")
                    value.update({"evidence_id": "verification05", "evidence_relative": "evidence_v2/verification05"})
            elif isinstance(value, dict) and value.get("schema") == "hepta.fullstudy.checkpoint-metadata-preview.1":
                value = {**value, "producer_map": self.map_descriptor, "actual_sources_A_by_seed": self.source_map(),
                    "training_parent_scope": "Primary phase producer; A checkpoints use their own registered seed producers."}
            return original(value)
        return encode

    def verify_job(self, original):
        def checked_job(job, registration):
            self.require_current(registration)
            if job.get("id") != "A-17":
                return original(job, registration)
            require(job == self.controller.imported_job, "Imported job differs from sole accepted historical definition")
            ancestry.verify_producer(17, ancestry.archive.descriptor(self.raw / job["completion"]), self.mapping)
            return original(job, self.profiles[17])
        return checked_job

    def training_jobs_match(self, jobs, primary, phase, freeze=None):
        if phase != "A":
            return bool(jobs) and all(job["freeze_sha256"] == primary["sha256"] and
                Path(job["argv"][job["argv"].index("--freeze") + 1]).resolve() == Path(primary["path"]).resolve() for job in jobs)
        require(primary == self.source(29), "Primary current A producer differs")
        if freeze is not None:
            self.require_bound(freeze)
        require(len(jobs) == 3 and {job.get("seed") for job in jobs} == {17, 29, 43}, "A job population differs")
        for job in jobs:
            source = self.source(job["seed"])
            require(job["freeze_sha256"] == source["sha256"] and job["argv"][job["argv"].index("--freeze") + 1] == source["path"], "A job actual producer differs")
            if job["seed"] == 17:
                require(job == self.controller.imported_job, "Imported A17 job differs")
        return True

    def followup_parent_matches(self, freeze, primary):
        self.require_bound(freeze)
        return freeze.get("actual_source_A") == primary == self.source(29)

    def additional_parents(self, freeze):
        if "producer_map" not in freeze:
            return []
        self.require_bound(freeze)
        return [self.source(17), self.source(29)]

    def controller_start_matches(self, root, job, result, read):
        if job["id"] != "A-17":
            return read(root / "controller" / (job["id"] + ".START.json"))["job"] == job
        require(Path(root) == self.raw and job == self.controller.imported_job and not (root / "controller/A-17.START.json").exists(),
                "Historical A17 must not have a fabricated new START")
        require(read(root / "controller/A-17.IMPORT.json") == self.controller.import_record and result == self.controller.imported_result,
                "A17 controller import/result provenance differs")
        return True

    def operation_profile_matches(self, operation, phase, seed, registration):
        self.require_current(registration)
        if phase == "A":
            item = ancestry.archive.descriptor(self.raw / f"operations/A-seed-{seed}.COMPLETE.json")
            ancestry.verify_producer(seed, item, self.mapping)
            require(ancestry.archive.read(item["path"]) == operation, "Operation value differs from actual bytes")
            return operation.get("operational_amendment_sha256") == self.mapping[str(seed)]["profile"]["sha256"]
        return operation.get("operational_amendment_sha256") == registration["_sha256"]

    def for_followups(self, module):
        result = isolated_module(module, self)
        result.verify_job = self.verify_job(result.verify_job)
        original_operation = result.operation
        def operation(root, phase, seed, source, registration):
            self.require_current(registration)
            if phase == "A":
                require(Path(root) == self.raw and source == self.source(29), "Wrong A population root/primary")
                ancestry.verify_producer(seed, ancestry.archive.descriptor(self.raw / f"operations/A-seed-{seed}.COMPLETE.json"), self.mapping)
                return original_operation(root, phase, seed, self.source(seed), self.profiles[seed])
            return original_operation(root, phase, seed, source, registration)
        result.operation, result.encode = operation, self.encoding(result.encode)
        return result

    def for_endpoint(self, module):
        result = isolated_module(module, self)
        original_collect, original_registration = result.collect_ab, result.registration_for
        def registration_for(args):
            registration, freeze, source, parent, provenance = original_registration(args)
            self.require_current(registration)
            self.require_bound(freeze)
            if args.phase == "A":
                require(source == self.source(29), "Wrong primary A endpoint producer")
                for seed in (17, 29, 43):
                    result.parent_freeze("A", self.source(seed), self.profiles[seed])
                provenance = {**provenance, "scientific_training_registered_commit": None,
                    "scientific_training_source_freeze_sha256": None, "producer_map": self.map_descriptor,
                    "scientific_training_producers_by_seed": self.source_map(), "primary_training_parent_for_legacy_interface": source,
                    "training_producer_scope": "Mixed registered episodes; exact producer is determined by seed."}
            return registration, freeze, source, parent, provenance
        def collect_ab(root, phase, runtime_sha, source, parent):
            if phase != "A":
                return original_collect(root, phase, runtime_sha, source, parent)
            require(Path(root) == self.raw and source == self.source(29) and runtime_sha == self.mapping["17"]["runtime_sha256"],
                    "A endpoint root/primary/runtime differs")
            for seed in result.ab.SEEDS:
                actual = self.source(seed)
                actual_parent = result.parent_freeze("A", actual, self.profiles[seed])
                result.operation_complete(root, phase, seed, actual, actual_parent)
                ancestry.verify_producer(seed, ancestry.archive.descriptor(self.raw / f"operations/A-seed-{seed}.COMPLETE.json"), self.mapping)
            inventory = result.ab.collect_checkpoints(root, phase, runtime_sha)
            require(set(inventory["completions"]) == {"17", "29", "43"}, "A completion population differs")
            for seed, complete in inventory["completions"].items():
                actual = self.source(int(seed))
                require(complete["source_freeze_sha256"] == actual["sha256"] and complete["registered_commit"] == actual["registered_commit"],
                        "A completion actual producer differs")
            for entry in inventory["entries"]:
                actual = self.source(entry["seed"])
                binding = ancestry.state_metadata(Path(inventory["stage"]) / entry["path"])["binding"]
                require(binding["source_freeze_sha256"] == actual["sha256"] and binding["protocol_sha256"] == actual["protocol_sha256"]
                        and binding["runtime_sha256"] == runtime_sha, "A checkpoint actual producer/runtime differs")
            return inventory
        result.registration_for, result.collect_ab = registration_for, collect_ab
        return result

    def for_summary(self, module):
        result = isolated_module(module, self)
        result.verify_job = self.verify_job(result.verify_job)
        original_collect, original_inputs = result.collect, result.analysis_inputs
        def collect(args, registration):
            stages, sources, artifacts, seals, provenance = original_collect(args, registration)
            for item in (self.map_descriptor, self.import_receipt):
                result.add(artifacts, ancestry.checked(item))
            provenance.update({"producer_map": self.map_descriptor, "import_receipt": self.import_receipt, "imported_jobs": ["A-17"]})
            return stages, sources, artifacts, seals, provenance
        def analysis_inputs(*args, **kwargs):
            return {**original_inputs(*args, **kwargs), "producer_map": self.map_descriptor, "import_receipt": self.import_receipt}
        result.collect, result.analysis_inputs, result.encode = collect, analysis_inputs, self.encoding(result.encode)
        return result

    def report_profiles(self, operations, spec):
        require(spec.get("producer_map") == self.map_descriptor and spec.get("import_receipt") == self.import_receipt
                and spec["raw_root"] == str(self.raw) and spec["amendment"] == self.current_profile, "Report map/profile differs")
        for (phase, seed), operation in operations.items():
            require(self.operation_profile_matches(operation, phase, seed, self.profiles[29]), "Operation amendment differs")
        return True

    def for_report(self, module):
        result = isolated_module(module, self)
        original_ready = result.ready_operations
        def ready(spec):
            operations = original_ready(spec)
            self.report_profiles(operations, spec)
            return operations
        result.ready_operations = ready
        return result

    def verify_training_inputs(self, args, freeze, registration):
        self.require_current(registration)
        self.require_bound(freeze)
        phase, seed = args.phase, args.seed
        require(phase in ("B", "W", "R") and Path(args.root) == self.raw, "Unknown followup input gate")
        for current in ((17, 29, 43) if phase == "W" else (seed,)):
            source = self.source(current)
            ancestry.verify_producer(current, ancestry.archive.descriptor(self.raw / f"operations/A-seed-{current}.COMPLETE.json"), self.mapping)
            bank = self.raw / f"stage_A/seed-{current}/bank"
            names = [mode + "-head.npz" for mode in ("field12", "full_current_state", "history6")] if phase == "B" else ["BANK.json", "trace.jsonl.gz", "field12-head.npz"]
            states = ["schedule-6000-baseline-step-48.state"] if phase == "W" else (
                [f"schedule-{schedule}-{prefix}-step-{step}.state" for schedule in range(6000, 6004)
                 for prefix in ("baseline", "balanced") for step in range(0, 288, 48)] if phase == "R" else [])
            for name in names + states:
                path = bank / name
                require(str(path) in freeze["artifacts"], "Followup input was not frozen")
                ancestry.hash_checked(path, freeze["artifacts"][str(path)])
            for name in states:
                metadata = ancestry.state_metadata(bank / name)
                require(metadata["binding"]["source_freeze_sha256"] == source["sha256"]
                        and metadata["binding"]["protocol_sha256"] == source["protocol_sha256"]
                        and metadata["binding"]["runtime_sha256"] == self.mapping[str(current)]["runtime_sha256"]
                        and metadata["cursor"]["seed"] == current, "Followup parent source/runtime/seed differs")

    def for_runner(self, module):
        result = isolated_module(module, self)
        original = result.validate_freeze
        def validate(args, registration):
            self.require_current(registration)
            require(not (args.phase == "A" and args.seed == 17), "A17 is imported and cannot execute again")
            freeze = original(args, registration)
            if args.phase in ("B", "W", "R"):
                self.verify_training_inputs(args, freeze, registration)
            return freeze
        result.validate_freeze = validate
        return result

    def for_analysis_launcher(self, module):
        result = isolated_module(module, self)
        original = result.validate
        def validate(args):
            registration, freeze = original(args)
            self.require_current(registration)
            self.require_bound(freeze)
            spec = result.json_read(args.inputs)
            require(spec.get("producer_map") == self.map_descriptor and spec.get("import_receipt") == self.import_receipt,
                    "Analysis input producer map differs")
            return registration, freeze
        result.validate = validate
        return result

    def for_finalizer(self, module):
        result = isolated_module(module, self)
        original_verify, original_finalize = result.verify_source_freeze, result.finalize
        verified = {}
        def verify(path, registration):
            self.require_current(registration)
            freeze = original_verify(path, registration)
            self.require_bound(freeze)
            require(freeze.get("evidence_id") == "verification05"
                    and freeze.get("evidence_relative") == "evidence_v2/verification05",
                    "Finalizer source does not bind execution05 evidence destination")
            verified["source_freeze_sha256"] = ancestry.archive.descriptor(Path(path).resolve())["sha256"]
            return freeze
        def finalize(storage, binding, evidence_id="verification05"):
            require(evidence_id == "verification05" and storage.root == self.raw
                    and bool(verified) and binding.get("source_freeze_sha256") == verified["source_freeze_sha256"],
                    "Finalizer requires its verified source and fixed execution05 destination")
            return original_finalize(storage, binding, evidence_id)
        result.verify_source_freeze, result.finalize = verify, finalize
        return result

    def postseal_profile(self, operation, phase, seed, store, binding):
        require(binding["operational_amendment_sha256"] == self.current_profile["sha256"], "Postseal current profile differs")
        if phase == "A":
            if seed == 17:
                require(store.metadata("controller/A-17.IMPORT.json") == self.controller.import_record
                        and store.metadata("controller/A-17.RESULT.json") == self.controller.imported_result
                        and not (self.raw / "controller/A-17.START.json").exists(), "Postseal imported job provenance differs")
            ancestry.verify_producer(seed, store.descriptor(f"operations/A-seed-{seed}.COMPLETE.json"), self.mapping)
            return operation.get("operational_amendment_sha256") == self.mapping[str(seed)]["profile"]["sha256"]
        return operation.get("operational_amendment_sha256") == binding["operational_amendment_sha256"]

    def for_postseal(self, module):
        result = isolated_module(module, self)
        result.EPISODE = ancestry.TARGET_EPISODE
        original = result.gate
        def gate(args, inputs, output):
            plan = inputs.read_json(args.plan, args.expected_plan_sha256, role="execution05_producer_plan")
            require(plan.get("producer_map") == self.map_descriptor and plan.get("import_receipt") == self.import_receipt,
                    "Postseal plan does not explicitly register imported A17")
            require(ancestry.checked(plan["producer_adapter"]) == Path(__file__).resolve(), "Unregistered producer-adapter source")
            finalizer = inputs.read_json(args.finalizer_freeze, args.expected_finalizer_sha256, role="execution05_finalizer_producer_map")
            self.require_bound(finalizer)
            aggregate = inputs.descriptor_json(finalizer["actual_aggregate_source_freeze"], "execution05_aggregate_producer_map")
            self.require_bound(aggregate)
            plan, store, protocol, receipt = original(args, inputs, output)
            receipt.update({"producer_map": self.map_descriptor, "import_receipt": self.import_receipt,
                            "imported_jobs": ["A-17"], "new_scientific_jobs": 13})
            return plan, store, protocol, receipt
        result.gate = gate
        return result
