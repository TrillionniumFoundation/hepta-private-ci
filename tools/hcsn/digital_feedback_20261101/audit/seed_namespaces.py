"""Enumerate task RNG initialization identities without generating any worlds.

No project imports or random draws. Candidate-paired streams are represented
once per fit/role/world. Study seed expressions are read from the actual source
AST, so a proposed split-offset correction is not assumed already implemented.
"""
import argparse
import ast
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

ALLOWED = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Subscript, ast.BinOp,
           ast.Add, ast.Sub, ast.Mult, ast.IfExp, ast.Compare, ast.In, ast.NotIn,
           ast.Eq, ast.NotEq, ast.Dict, ast.List, ast.Tuple)


def expression(path, function, target=None, rng=False):
    tree = ast.parse(Path(path).read_text())
    definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    matches = []
    for node in ast.walk(definition):
        if rng and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "default_rng":
            matches.append(node.args[0])
        elif target and isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            matches.append(node.value)
    if len(matches) != 1:
        raise ValueError(f"expected one explicit seed expression: {path}:{function}:{target}")
    value = ast.Expression(matches[0])
    if any(not isinstance(node, ALLOWED) for node in ast.walk(value)):
        raise ValueError("seed expression exceeds side-effect-free AST subset")
    return compile(value, str(path), "eval"), ast.unparse(matches[0])


def audit(protocol, study, training, historical=(), formal_fits=None, retained=(), retained_sources=None,
          retained_formal=()):
    formal = list(protocol["fits"] if formal_fits is None else formal_fits)
    development = list(protocol["development_fits"])
    if set(formal) & set(development) or len(formal) != len(set(formal)) or len(development) != len(set(development)):
        raise ValueError("formal/development fit identities must be unique and disjoint")
    if any(isinstance(fit, bool) or not isinstance(fit, int) or not 0 <= fit < 10000 for fit in formal + development):
        raise ValueError("registered seed partition requires integer 0 <= fit < 10000")
    for key in ("train_worlds", "validation_worlds", "iid_worlds", "ood_worlds", "feedback_worlds_total"):
        if not isinstance(protocol[key], int) or not 0 < protocol[key] < 10000:
            raise ValueError("registered world count must lie in (0,10000)")
    value_code, value_text = expression(study, "evaluate", "seed")
    probe_code, probe_text = expression(study, "probe_pairs", "seed")
    training_functions = {node.name for node in ast.parse(Path(training).read_text()).body
                          if isinstance(node, ast.FunctionDef)}
    fit_function = "_fit_candidate_body" if "_fit_candidate_body" in training_functions else "fit_candidate"
    visit_code, visit_text = expression(training, fit_function, "execution_seed")
    batch_code, batch_text = expression(training, fit_function, rng=True)
    order_code, order_text = expression(study, "train", rng=True)
    rows = []
    retained_sources = retained_sources or {}
    retained_expressions = {}
    formal_expressions = {}

    def add(stage, role, fit, split, index, seed, historical=False):
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        engine = "torch.manual_seed CPU" if role == "head_initialization" else "numpy.default_rng"
        rows.append(dict(stage=stage, role=role, fit=fit, split=split, world_index=index,
                         seed=seed, generator_api=engine, historical=historical))

    def calculate(code, fit, split="train", index=0):
        return int(eval(code, {"__builtins__": {}}, dict(protocol=protocol, fit=fit, split=split,
                                                       i=index, world_cursor=index)))

    for stage, fits in (("development", development), ("formal", formal)):
        for fit in fits:
            for split, offset in (("train", 0), ("validation", 100000)):
                add(stage, "cohort", fit, split, None, protocol["data_seed_base"] + fit * 1000000 + offset)
            add(stage, "calibration", fit, "train", None, protocol["data_seed_base"] + fit * 1000000 + 900000)
            for split, offset in (("train", 700000), ("validation", 800000)):
                add(stage, "behavior_actions", fit, split, None, protocol["data_seed_base"] + fit * 1000000 + offset)
            add(stage, "head_initialization", fit, "train", None, 731000 + fit)
            add(stage, "cell_initialization", fit, "train", None, 732000 + fit)
            add(stage, "minibatches", fit, "train", None, calculate(batch_code, fit))
            add(stage, "candidate_order", fit, "train", None, calculate(order_code, fit))
            for index in range(protocol["feedback_worlds_total"]):
                add(stage, "feedback_execution", fit, "train", index, calculate(visit_code, fit, index=index))
            for index in range(protocol["train_worlds"]):
                add(stage, "decoder_probe", fit, "train", index, calculate(probe_code, fit, "train", index))
            splits = (("validation", "validation_ood") if stage == "development" else ("iid", "ood"))
            for split in splits:
                count = protocol["validation_worlds"] if stage == "development" else protocol[split + "_worlds"]
                if split == "validation_ood":
                    add(stage, "cohort", fit, split, None, protocol["development_ood_seed_base"] + fit * 1000000 + 300000)
                elif split in ("iid", "ood"):
                    offset = 200000 if split == "iid" else 300000
                    add(stage, "cohort", fit, split, None, protocol["confirmation_seed_base"] + fit * 1000000 + offset)
                for index in range(count):
                    add(stage, "value_execution", fit, split, index, calculate(value_code, fit, split, index))
                    if stage == "formal":
                        add(stage, "decoder_probe", fit, split, index, calculate(probe_code, fit, split, index))
    historical_fits = set()
    for name, old in historical:
        for fit in old["fits"] + old.get("development_fits", []):
            historical_fits.add(fit)
            is_formal = fit in old["fits"]
            splits = (("train", 0), ("validation", 100000)) + ((("iid", 200000), ("ood", 300000)) if is_formal else ())
            for split, offset in splits:
                base = old["confirmation_seed_base"] if split in ("iid", "ood") else old["data_seed_base"]
                add(name, "cohort", fit, split, None, base + fit * 1000000 + offset, True)
            add(name, "calibration", fit, "train", None, old["data_seed_base"] + fit * 1000000 + 900000, True)
            for split, offset in (("train", 700000), ("validation", 800000)):
                add(name, "behavior_actions", fit, split, None, old["data_seed_base"] + fit * 1000000 + offset, True)
            add(name, "head_initialization", fit, "train", None, 731000 + fit, True)
            add(name, "cell_initialization", fit, "train", None, 732000 + fit, True)
            add(name, "minibatches", fit, "train", None, old.get("batch_seed_base", 733000) + fit, True)
            if "occupancy_seed_base" in old:
                for index in range(old["train_worlds"]):
                    add(name, "feedback_execution", fit, "train", index,
                        old["occupancy_seed_base"] + fit * 10000 + index, True)
            for split in (("iid", "ood") if is_formal else ("validation",)):
                offset = {"validation": 0, "iid": 10000, "ood": 20000}[split] if "execution_seed_base" in old else {"iid": 0, "ood": 10000}[split]
                for index in range(old[split + "_worlds"]):
                    add(name, "value_execution", fit, split, index,
                        old.get("execution_seed_base", 830000000) + fit * 100000 + offset + index, True)
                    if "execution_seed_base" not in old:
                        rows[-1]["generator_api"] = "historical native/Python task RNG; not assumed NumPy"
    for name, record, kind in retained:
        old, fit = record["protocol"], record["fit"]
        historical_fits.add(fit)
        for split, offset in (("train", 0), ("validation", 100000)):
            add(name, "cohort", fit, split, None, old["data_seed_base"] + fit * 1000000 + offset, True)
        for role, offset in (("calibration", 900000), ("behavior_actions", 700000)):
            add(name, role, fit, "train", None, old["data_seed_base"] + fit * 1000000 + offset, True)
        add(name, "behavior_actions", fit, "validation", None, old["data_seed_base"] + fit * 1000000 + 800000, True)
        for role, base in (("head_initialization", 731000), ("cell_initialization", 732000),
                           ("minibatches", old["batch_seed_base"])):
            add(name, role, fit, "train", None, base + fit, True)
        for index in range(old["feedback_worlds_total"]):
            add(name, "feedback_execution", fit, "train", index, old["occupancy_seed_base"] + fit * 100000 + index, True)
        if kind == "development":
            add(name, "candidate_order", fit, "train", None, old["candidate_order_seed_base"] + fit, True)
            add(name, "cohort", fit, "validation_ood", None, old["development_ood_seed_base"] + fit * 1000000 + 300000, True)
            for split in ("validation", "validation_ood"):
                for index in range(old["validation_worlds"]):
                    add(name, "value_execution", fit, split, index,
                        old["execution_seed_base"] + fit * 100000 + (20000 if "ood" in split else 10000) + index, True)
            archived_study = retained_sources[name]
            historical_probe, historical_probe_text = expression(archived_study, "probe_pairs", "seed")
            retained_expressions[name] = dict(probe=historical_probe_text,
                source=str(archived_study), source_sha256=hashlib.sha256(Path(archived_study).read_bytes()).hexdigest())
            for index in range(old["train_worlds"]):
                seed = int(eval(historical_probe, {"__builtins__": {}},
                                dict(protocol=old, fit=fit, split="train", i=index)))
                add(name, "decoder_probe", fit, "train", index, seed, True)
        elif "probe_seed_base" in old:
            # The retained plumbing pilot reused this declared configuration.
            # Enumerate full role windows as a conservative superset; this does
            # not assert that every configured pilot episode was executed.
            for split in ("train", "validation"):
                for index in range(old[split + "_worlds"]):
                    add(name, "decoder_probe", fit, split, index,
                        old["probe_seed_base"] + fit * 100000 + 10000 + index, True)
            for index in range(old["validation_worlds"]):
                add(name, "value_execution", fit, "validation", index,
                    old["execution_seed_base"] + fit * 100000 + 10000 + index, True)
    for previous in retained_formal:
        old, name = previous["protocol"], previous["run"]
        archived_study, archived_training = Path(previous["study"]), Path(previous["training"])
        functions = {node.name for node in ast.parse(archived_training.read_text()).body
                     if isinstance(node, ast.FunctionDef)}
        body = "_fit_candidate_body" if "_fit_candidate_body" in functions else "fit_candidate"
        specifications = dict(value_execution=(archived_study,"evaluate","seed",False),
                              decoder_probe=(archived_study,"probe_pairs","seed",False),
                              feedback_execution=(archived_training,body,"execution_seed",False),
                              minibatches=(archived_training,body,None,True),
                              candidate_order=(archived_study,"train",None,True))
        expressions = {role:expression(path,function,target,rng)
                       for role,(path,function,target,rng) in specifications.items()}
        formal_expressions[name] = {role:description for role,(_,description) in expressions.items()}
        started, cancelled, finished = (set(previous[key]) for key in
                                        ("started_fits","cancelled_before_start_fits","finished_fits"))
        for fit in old["fits"]:
            historical_fits.add(fit)

            def reserve(role, split, index, seed):
                add(name,role,fit,split,index,seed,True)
                rows[-1].update(planned_only=fit not in started or split in ("iid","ood"),
                    fit_execution_status="training_finished" if fit in finished else "training_started" if fit in started else
                                         "cancelled_before_scientific_start" if fit in cancelled else "no_start_record",
                    use_scope="registered namespace window, not proof every listed stream was drawn; IID/OOD remained ungenerated in this aborted formal version")

            def seed_for(role, split="train", index=0):
                return int(eval(expressions[role][0],{"__builtins__":{}},
                                dict(protocol=old,fit=fit,split=split,i=index,world_cursor=index)))

            for split,offset in (("train",0),("validation",100000),("iid",200000),("ood",300000)):
                base = old["confirmation_seed_base"] if split in ("iid","ood") else old["data_seed_base"]
                reserve("cohort",split,None,base+fit*1000000+offset)
            reserve("calibration","train",None,old["data_seed_base"]+fit*1000000+900000)
            for split,offset in (("train",700000),("validation",800000)):
                reserve("behavior_actions",split,None,old["data_seed_base"]+fit*1000000+offset)
            reserve("head_initialization","train",None,731000+fit)
            reserve("cell_initialization","train",None,732000+fit)
            for role in ("minibatches","candidate_order"):
                reserve(role,"train",None,seed_for(role))
            for index in range(old["feedback_worlds_total"]):
                reserve("feedback_execution","train",index,seed_for("feedback_execution",index=index))
            for index in range(old["train_worlds"]):
                reserve("decoder_probe","train",index,seed_for("decoder_probe",index=index))
            for split in ("iid","ood"):
                for index in range(old[split+"_worlds"]):
                    for role in ("value_execution","decoder_probe"):
                        reserve(role,split,index,seed_for(role,split,index))
    if set(formal) & historical_fits:
        raise ValueError("formal fit IDs reuse historical formal/development/pilot fits")
    by_seed, intervals = defaultdict(list), defaultdict(list)
    for row in rows:
        by_seed[row["seed"]].append(row)
        intervals[(row["stage"], row["role"], row["split"])].append(row["seed"])
    aliases = [entries for entries in by_seed.values() if len(entries) > 1 and any(not row["historical"] for row in entries)]
    collisions = [entries for entries in aliases if sum(not row["historical"] for row in entries) > 1
                  or any(not row["historical"] and row["stage"] == "formal" for row in entries)]
    dev_aliases = [entries for entries in aliases if entries not in collisions]
    serialized = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return dict(schema="digital-feedback-seed-namespace-audit-v1", passed=not collisions,
                formal_fits=formal, development_fits=development, formal_ids_overridden=formal_fits is not None,
                expressions=dict(value_execution=value_text, decoder_probe=probe_text, feedback=visit_text,
                                 minibatches=batch_text, candidate_order=order_text),
                retained_development_expressions=retained_expressions,
                retained_formal_expressions=formal_expressions,
                retained_formal_execution_inventory=[{key:entry[key] for key in
                    ("run","snapshot","started_fits","finished_fits","cancelled_before_start_fits")}
                    for entry in retained_formal],
                source_sha256={str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (study, training)},
                entries=len(rows), enumeration_sha256=hashlib.sha256(serialized).hexdigest(),
                collision_seed_count=len(collisions), collisions=collisions,
                development_historical_alias_count=len(dev_aliases), development_historical_aliases=dev_aliases,
                generator_aware_development_aliases=[dict(seed=entries[0]["seed"],
                    same_generator_pairs=[dict(left=a, right=b, same_role=a["role"] == b["role"],
                                               same_fit=a["fit"] == b["fit"])
                                          for i, a in enumerate(entries) for b in entries[i + 1:]
                                          if a["generator_api"] == b["generator_api"]]) for entries in dev_aliases],
                intervals=[dict(stage=k[0], role=k[1], split=k[2], count=len(v), minimum=min(v), maximum=max(v))
                           for k, v in sorted(intervals.items())],
                all_explicit_seeds=rows,
                declared_reuse="All candidates of one fit intentionally share initialization/minibatch and paired world-execution streams; those aliases are enumerated once.",
                historical_scope="Retained finite-task formal/development protocols, explicit prior-development/pilot records, and aborted-formal source snapshots with started/cancelled status. Unstarted formal fits and all ungenerated IID/OOD windows are planned-only reservations. Pilot role windows with a probe configuration include plumbing conservatively, not a claim every configured episode ran. Standalone CTMC auxiliaries and unit fixtures are outside this task study.",
                development_reuse_scope="Old development aliases are reported, never relabeled fresh independent confirmation. passed requires zero new-design internal aliases and zero formal aliases with all retained roles, even across different generator APIs.",
                limits="No world/label/packet bytes generated. Nested packet seeds are random draws inside each cohort stream, not separately pre-inspected. Distinct initializers do not prove abstract PRNG independence.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--training-source", type=Path)
    parser.add_argument("--historical-protocol", type=Path, action="append", default=[])
    parser.add_argument("--retained-development", type=Path, action="append", default=[])
    parser.add_argument("--retained-formal", type=Path, action="append", default=[],
                        help="Aborted formal training directory, paired with formal_source_NNN snapshot")
    parser.add_argument("--pilot-process", type=Path, action="append", default=[])
    parser.add_argument("--formal-fits", help="Inclusive first:last:step planning override, without changing protocol")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    fits = None
    if args.formal_fits:
        first, last, step = map(int, args.formal_fits.split(":"))
        fits = list(range(first, last + 1, step))
    retained = [(str(p), json.loads(p.read_text()), "pilot") for p in args.pilot_process]
    retained_sources = {}
    for prior in args.retained_development:
        launched = json.loads((prior / "LAUNCH.json").read_text())
        archived_study = prior.parent / prior.name.replace("development_", "development_source_", 1) / "study.py"
        source_key = str(root.relative_to(root.parents[2]) / "study.py")
        if hashlib.sha256(archived_study.read_bytes()).hexdigest() != launched["source_sha256"][source_key]:
            raise ValueError("retained development study source differs from its launch identity")
        for fit in launched["fits"]:
            p = prior / f"fit_{fit}" / "STARTED.json"
            retained.append((str(p), json.loads(p.read_text()), "development"))
            retained_sources[str(p)] = archived_study
    retained_formal, formal_inputs = [], []
    for prior in args.retained_formal:
        snapshot = prior.parent / prior.name.replace("training_","formal_source_",1)
        snapshot_path = snapshot / "SNAPSHOT.json"
        snapshot_record = json.loads(snapshot_path.read_text())
        if snapshot_record.get("confirmation_generated") is not False:
            raise ValueError("retained-formal option requires an explicitly unconfirmed aborted version")
        formal_inputs.append(snapshot_path)
        for name,expected in snapshot_record["source_sha256"].items():
            if Path(name).name != name or hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != expected:
                raise ValueError("retained formal snapshot identity mismatch")
            formal_inputs.append(snapshot/name)
        old = json.loads((snapshot/"protocol.json").read_text())
        launch_path = prior/"LAUNCH.json"
        launch = json.loads(launch_path.read_text())
        frozen = json.loads((snapshot/"SOURCE_FREEZE.json").read_text())
        if launch["fits"] != old["fits"] or launch["source_sha256"] != frozen["source_sha256"]:
            raise ValueError("retained formal launch differs from archived source/protocol")
        formal_inputs.append(launch_path)
        for name in ("ABORT_REGISTRATION.json","STOP_AFTER_ACTIVE.json","CONTROLLER_RECEIPT.json"):
            if (prior/name).exists():
                formal_inputs.append(prior/name)
        started,finished,cancelled = [],[],[]
        for fit in old["fits"]:
            folder = prior/f"fit_{fit}"
            begin = folder/"STARTED.json"
            if begin.exists():
                value = json.loads(begin.read_text())
                if value["fit"] != fit or value["protocol"] != old or value["source_sha256"] != launch["source_sha256"]:
                    raise ValueError("retained formal STARTED identity mismatch")
                started.append(fit)
            if (folder/"FINISHED.json").exists():
                if fit not in started:
                    raise ValueError("formal FINISHED without a started scientific fit")
                finished.append(fit)
            if any((folder/name).exists() for name in ("ABORTED_BEFORE_START.json","CANCELLED_BEFORE_START.json")):
                if fit in started:
                    raise ValueError("formal fit both started and cancelled-before-start")
                cancelled.append(fit)
            for name in ("STARTED.json","FINISHED.json","FAILED.json","ABORTED_BEFORE_START.json","CANCELLED_BEFORE_START.json"):
                if (folder/name).exists():
                    formal_inputs.append(folder/name)
            receipt = prior/"process_receipts"/f"fit_{fit}.json"
            if receipt.exists():
                formal_inputs.append(receipt)
        retained_formal.append(dict(run=str(prior),snapshot=str(snapshot),protocol=old,
            study=str(snapshot/"study.py"),training=str(snapshot/"training.py"),started_fits=started,
            finished_fits=finished,cancelled_before_start_fits=cancelled))
    result = audit(json.loads(args.protocol.read_text()), args.study or root / "study.py",
                   args.training_source or root / "training.py",
                   [(str(p), json.loads(p.read_text())) for p in args.historical_protocol], fits, retained, retained_sources,
                   retained_formal)
    inputs = [args.protocol] + args.historical_protocol + args.pilot_process
    for prior in args.retained_development:
        inputs.append(prior / "LAUNCH.json")
        inputs += [prior / f"fit_{fit}" / "STARTED.json"
                   for fit in json.loads((prior / "LAUNCH.json").read_text())["fits"]]
    inputs += list(set(retained_sources.values()))
    inputs += formal_inputs
    result["input_files_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in inputs}
    raw = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0) if args.output.suffix == ".gz" else raw)
    print(json.dumps({key: result[key] for key in ("passed", "entries", "collision_seed_count", "enumeration_sha256")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
