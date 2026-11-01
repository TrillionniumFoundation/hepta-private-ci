#!/usr/bin/env python3
"""Plot completed JSON evidence without fitting, raw-array access, or new CIs.

Separate publication tool, outside the scientific source freeze. The selfcheck
requires an explicitly artificial report fixture and never discovers run data.
"""

import argparse
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import tempfile


TASKS = ("recall", "binding")
PRESSURE = ("long_distractors", "blank_retention", "irregular_dt", "clock4x", "query_swap")
DOMAINS = {"recall": ("iid", *PRESSURE, "missing_payload"),
           "binding": ("iid", *PRESSURE, "missing_a", "missing_b")}
FAMILIES = ("ordinary_distribution", "analytic_distribution", "ordinary_dual",
            "analytic_fixed", "mamba1", "transformer")
LABELS = {"iid": "IID", "long_distractors": "Long distractors", "blank_retention": "Blank retention",
          "irregular_dt": "Irregular timing", "clock4x": "Clock x4", "query_swap": "Query swap",
          "missing_payload": "Missing payload", "missing_a": "Missing A", "missing_b": "Missing B"}
SCHEMA_REVIEW = "hcsn.r15.publication.acceptance-review.v1"
SCHEMA_ONLINE = "hcsn.r15.full-online-supplement.summary.v1"


class PlotError(ValueError):
    """Input cannot support the registered display without inventing evidence."""


def require(condition, message):
    if not condition:
        raise PlotError(message)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate JSON key: " + key)
        value[key] = item
    return value


def read_json(path):
    path = Path(path).absolute()
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino), "Input changed during read: " + str(path))
    data = json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(PlotError("Nonfinite JSON: " + value)))
    require(isinstance(data, dict), "Expected a JSON object: " + str(path))
    return data, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, data):
    with Path(path).open("x") as output:
        json.dump(data, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")


def numeric(value, label):
    require(type(value) in (int, float) and math.isfinite(value), "Missing/nonfinite " + label)
    return value


def extract_effects(source, protocol=None):
    if source.get("schema") == SCHEMA_REVIEW:
        rules = source.get("actual_acceptance", {}).get("protocol_rules", {})
    else:
        require(source.get("schema") == SCHEMA_ONLINE and isinstance(protocol, dict),
                "Use ACCEPTANCE_REVIEW, or FULL_ONLINE_CONFIRMATION_SUMMARY with --protocol")
        rules = protocol.get("acceptance", {})
    require(rules.get("required_tasks") == list(TASKS), "Unexpected registered tasks")
    require(rules.get("pressure_domains") == list(PRESSURE) and rules.get("pressure_tolerance") == -.02,
            "Pressure domains/reference differ from the registered contract")
    analysis = source.get("actual_outcome_analysis")
    require(isinstance(analysis, dict), "Missing actual_outcome_analysis; replay is not a substitute")
    expected = {(task, domain) for task in TASKS for domain in DOMAINS[task]}
    cells = analysis.get("primary_four_cells", [])
    identities = [(row["task"], row["domain"]) for row in cells]
    require(len(identities) == len(set(identities)) and set(identities) == expected,
            "All 15 task/domain cells, including missing-modality controls, are required")
    inventory = {row["family"] for row in analysis.get("outcomes", [])}
    require(inventory == set(FAMILIES), "The six registered families are required")
    points, seeds, selected_by_task = [], None, {}
    for collection, comparison in (("total_effects", "D-B"), ("validation_selected_comparator", "D-B_selected")):
        seen = set()
        for index, row in enumerate(analysis.get(collection, [])):
            if collection == "total_effects" and row.get("contrast") != "D-B":
                continue
            key = (row.get("task"), row.get("domain"))
            require(key in expected and key not in seen, "Unknown/duplicate effect cell: " + str(key))
            seen.add(key)
            row_seeds = row.get("fit_seeds")
            require(isinstance(row_seeds, list) and len(row_seeds) == len(set(row_seeds)) == 8
                    and all(type(seed) is int for seed in row_seeds), "Eight paired fit seeds required")
            if seeds is None:
                seeds = row_seeds
            require(row_seeds == seeds and row.get("object_count") == 512, "Seed order or full cohort differs")
            require(row.get("negative_control") is key[1].startswith("missing"), "Incorrect negative-control flag")
            stat = row.get("metrics", {}).get("utility", {})
            mean = numeric(stat.get("mean"), "utility mean")
            interval = stat.get("fit_t95")
            require(isinstance(interval, list) and len(interval) == 2, "Missing stored fit_t95")
            low, high = (numeric(value, "fit_t95 endpoint") for value in interval)
            require(low <= mean <= high and stat.get("fit_count") == 8 and stat.get("fit_df") == 7,
                    "Invalid stored paired-fit interval metadata")
            if comparison == "D-B_selected":
                selected = row.get("selected_families")
                require(isinstance(selected, dict) and set(selected) == {str(seed) for seed in seeds}
                        and all(family in FAMILIES and not family.startswith("analytic") for family in selected.values()),
                        "Missing/invalid frozen validation-selected ordinary families")
                require(key[0] not in selected_by_task or selected_by_task[key[0]] == selected,
                        "Validation-selected comparator changed between domains")
                selected_by_task[key[0]] = selected
            points.append({"task": key[0], "domain": key[1], "comparison": comparison,
                           "mean": mean, "fit_t95": interval, "negative_control": row["negative_control"],
                           "pressure_reference_applies": comparison == "D-B" and key[1] in PRESSURE,
                           "source_pointer": f"/actual_outcome_analysis/{collection}/{index}/metrics/utility"})
        require(seen == expected, "Missing actual primary or selected-comparator domains")
    if protocol is not None:
        require(protocol.get("tasks") == list(TASKS) and protocol.get("seeds") == seeds
                and set(protocol.get("families", [])) == set(FAMILIES)
                and protocol.get("domains") == {task: list(DOMAINS[task]) for task in TASKS}
                and protocol.get("splits", {}).get("test", [None])[0] == 512,
                "Provided protocol and actual summary inventory differ")
    return {"points": points, "fit_seeds": seeds, "fit_df": 7, "objects_per_fit": 512,
            "pressure_reference": rules["pressure_tolerance"], "pressure_domains": list(PRESSURE),
            "selected_families_by_task": selected_by_task, "intervals_recomputed": False,
            "interval_scope": "Stored nominal paired-fit Student t95; no simultaneous/multiplicity correction"}


def aggregate_cost(index, effects, source):
    records = index.get("records")
    require(isinstance(records, list), "Missing full-online index.records")
    seeds = effects["fit_seeds"]
    expected = set(itertools.product(TASKS, FAMILIES, seeds))
    rows, cohort_hashes = {}, {}
    for position, row in enumerate(records):
        if (row.get("domain"), row.get("train_mode"), row.get("exec_mode")) != ("iid", "value", "value"):
            continue
        key = (row.get("task"), row.get("family"), row.get("seed"))
        require(key in expected and key not in rows, "Unexpected/duplicate IID value/value cost row: " + str(key))
        execution = row.get("execution", {})
        require(type(execution.get("objects")) is int and execution["objects"] == 512,
                "Every cost row must execute all 512 objects")
        seconds = numeric(execution.get("actor_cpu_seconds"), "actor CPU seconds")
        require(seconds >= 0, "Negative actor CPU")
        cohort = row.get("data_sha256")
        require(isinstance(cohort, str) and len(cohort) == 64 and all(c in "0123456789abcdef" for c in cohort),
                "Missing cohort data_sha256 in cost row")
        require(key[0] not in cohort_hashes or cohort_hashes[key[0]] == cohort,
                "Different IID object cohorts were mixed within a task")
        cohort_hashes[key[0]] = cohort
        rows[key] = {"seed": key[2], "actor_cpu_seconds": seconds, "objects": 512,
                     "actor_cpu_ms_per_object": seconds * 1000 / 512,
                     "source_pointer": f"/records/{position}/execution/actor_cpu_seconds"}
    require(set(rows) == expected, "Missing any of the 96 IID value/value cost rows")
    registration = [entry["sha256"] for entry in source.get("input_files", [])
                    if entry.get("path", "").endswith("/full_online_confirmation/SELF_REGISTRATION.json")]
    if registration:
        require(len(set(registration)) == 1 and index.get("registration_sha256") == registration[0],
                "Cost index and acceptance review identify different online registrations")
    cells = []
    for task, family in itertools.product(TASKS, FAMILIES):
        fits = [rows[(task, family, seed)] for seed in seeds]
        mean = math.fsum(row["actor_cpu_ms_per_object"] for row in fits) / len(fits)
        cells.append({"task": task, "family": family, "actor_cpu_ms_per_object": mean, "fits": fits})
    return {"cells": cells, "fit_seeds": seeds, "objects_per_fit": 512, "cohort_sha256_by_task": cohort_hashes,
            "selected_condition_rows": len(rows), "all_index_rows": len(records),
            "aggregation": "Arithmetic mean across 8 fits of actor_cpu_seconds * 1000 / 512; same cohort per task",
            "accounting": "Actor CPU only; group/worker CPU is not added. Repeated fits do not create new independent objects.",
            "scope": "Full-cohort actual IID value/value execution; not a microbenchmark; no GPU or Joules measurement"}


def chart_spec(cost, artificial):
    values = {(cell["task"], cell["family"]): cell["actor_cpu_ms_per_object"] for cell in cost["cells"]}
    return {"content": {"chartType": "bar",
        "meta": {"title": ("TEST FIXTURE - " if artificial else "") + "Actual online actor CPU per object",
                 "description": "IID, value training and value execution; all 512 objects per fit. Descriptive mean across eight fits for each task and family.",
                 "footer": ("Artificial layout data; not formal results. " if artificial else "") +
                           "Actor CPU only, never added to worker/group CPU. Full-cohort execution, not a microbenchmark. GPU and Joules were not measured."},
        "xKey": "family", "series": [{"dataKey": task + "_ms_per_object", "label": task.capitalize(),
            "axisLabel": "Actor CPU ms per object", "valueFormat": "raw", "valueSuffix": " ms"} for task in TASKS],
        "yAxisMin": 0, "layout": "vertical",
        "data": [{"family": family, **{task + "_ms_per_object": values[(task, family)] for task in TASKS}}
                 for family in FAMILIES]}}


def draw_forest(effects, directory, artificial):
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "hcsn-publication-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator, FuncFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "svg.hashsalt": "hcsn-r15-publication-forest-v1"})
    figure, axes = plt.subplots(1, 2, figsize=(14.8, 8.4), sharex=True)
    figure.subplots_adjust(left=.14, right=.975, bottom=.245, top=.79, wspace=.42)
    lookup = {(point["task"], point["domain"], point["comparison"]): point for point in effects["points"]}
    endpoints = [value for point in effects["points"] for value in point["fit_t95"]] + [0, -.02]
    low, high = min(endpoints), max(endpoints)
    span = max(high - low, .04)
    limits = (low - .12 * span, high + .12 * span)
    colors = {"D-B": "#235d86", "D-B_selected": "#ad671c"}
    markers = {"D-B": "o", "D-B_selected": "D"}
    y_pressure, y_control = [1.45 + i for i in range(5)], [7.05, 8.05]
    for axis, task in zip(axes, TASKS):
        locations = {"iid": 0, **dict(zip(PRESSURE, y_pressure))}
        locations.update(zip([domain for domain in DOMAINS[task] if domain.startswith("missing")], y_control))
        axis.set_xlim(*limits)
        axis.set_ylim(8.65, -.65)
        axis.axhspan(6.45, 8.65, color="#f4f1eb", zorder=0)
        axis.axvline(0, color="#5d6368", linewidth=1.2, zorder=1)
        # This reference deliberately stops before IID and missing-modality rows.
        axis.vlines(effects["pressure_reference"], 1.08, 5.82, colors="#9a4652",
                    linestyles=(0, (4, 3)), linewidth=1.4, zorder=2)
        for domain, y in locations.items():
            for comparison, offset in (("D-B", -.13), ("D-B_selected", .13)):
                point = lookup[(task, domain, comparison)]
                mean, (lo, hi) = point["mean"], point["fit_t95"]
                axis.errorbar(mean, y + offset, xerr=[[mean - lo], [hi - mean]], fmt=markers[comparison],
                              color=colors[comparison], markersize=5.4, capsize=3, elinewidth=1.6,
                              markeredgecolor="white", markeredgewidth=.5, zorder=4)
        axis.set_yticks(list(locations.values()), [LABELS[domain] for domain in locations])
        axis.tick_params(axis="y", length=0, pad=9)
        axis.xaxis.set_major_locator(MaxNLocator(nbins=6))
        axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:+.3f}" if value else "0"))
        axis.grid(axis="x", color="#e5e8eb", linewidth=.6)
        axis.set_axisbelow(True)
        for spine in ("top", "right", "left"):
            axis.spines[spine].set_visible(False)
        axis.spines["bottom"].set_color("#c5cbd0")
        axis.set_title(task.capitalize(), fontsize=15, fontweight="bold", loc="left", pad=17)
        axis.set_xlabel("Actual online utility difference", labelpad=11)
        axis.text(0, .851, "Registered pressure domains", transform=axis.transAxes,
                  fontsize=9, color="#68717a", va="bottom")
        axis.text(.025, .216, "Missing-modality negative controls", transform=axis.transAxes,
                  fontsize=9, color="#6e6251", va="bottom")
    title = "Actual online utility differences across all registered domains"
    figure.text(.5, .945, title, ha="center", fontsize=17, fontweight="bold", color="#1f2933")
    figure.text(.5, .907, "Value-trained backends with value execution; 8 paired fits, 512 objects per fit",
                ha="center", fontsize=11, color="#52606d")
    if artificial:
        figure.text(.5, .861, "TEST FIXTURE  |  ARTIFICIAL VALUES  |  NOT FORMAL RESULTS", ha="center",
                    fontsize=12, fontweight="bold", color="#9b3b19",
                    bbox={"facecolor": "#fff0df", "edgecolor": "#dca66d", "boxstyle": "round,pad=0.35"})
    legend = [Line2D([], [], color=colors["D-B"], marker="o", label="Primary D - B (matched ordinary)"),
              Line2D([], [], color=colors["D-B_selected"], marker="D", label="D - validation-selected ordinary"),
              Line2D([], [], color="#9a4652", linestyle="--", label="Pressure mean reference: -0.02")]
    figure.legend(handles=legend, loc="lower center", bbox_to_anchor=(.5, .147), ncol=3,
                  frameon=False, fontsize=10, handlelength=2.2, columnspacing=2.0)
    footer = ["Points and intervals are copied from stored mean / nominal fit t95 (df = 7); no intervals are recomputed.",
              "The -0.02 reference applies only to primary D - B means in the five pressure domains per task, not to interval endpoints or selected-comparator effects.",
              "Missing-modality controls remain separate. Positive values favor the analytic distribution core; all negative domains are retained."]
    for i, line in enumerate(footer):
        figure.text(.5, .118 - i * .026, line, ha="center", fontsize=8.8, color="#52606d")
    figure.savefig(directory / "forest_actual_utility.png", dpi=180, facecolor="white")
    figure.savefig(directory / "forest_actual_utility.svg", facecolor="white", metadata={"Date": None})
    plt.close(figure)
    return {"matplotlib_version": matplotlib.__version__, "x_limits": list(limits),
            "panels": list(TASKS), "task_domain_rows": 15, "estimates": 30,
            "pressure_reference_y_span": [1.08, 5.82], "pressure_rows_per_panel": 5}


def render(args):
    source_path = args.review or args.online_summary
    source, source_meta = read_json(source_path)
    inputs = [source_meta]
    protocol = None
    if args.protocol:
        protocol, metadata = read_json(args.protocol)
        inputs.append(metadata)
    effects = extract_effects(source, protocol)
    index, metadata = read_json(args.online_index)
    inputs.append(metadata)
    cost = aggregate_cost(index, effects, source)
    artificial = bool(args.test_fixture or source.get("artificial_fixture") or index.get("artificial_fixture"))
    output = Path(args.output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    drawing = draw_forest(effects, output, artificial)
    write_json(output / "plot_data.json", {"artificial_fixture": artificial, **effects})
    write_json(output / "cost_aggregation.json", {"artificial_fixture": artificial, **cost})
    write_json(output / "chart_spec.json", chart_spec(cost, artificial))
    outputs = [{"path": path.name, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(output.iterdir())]
    receipt = {"schema": "hcsn.r15.publication.plots.v1", "artificial_fixture": artificial,
               "plot_generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "inputs": inputs, "outputs": outputs, "drawing": drawing,
               "actual_outcome_statistics_only": True, "intervals_recomputed": False,
               "model_or_policy_selection_performed": False, "raw_npz_or_checkpoint_opened": False,
               "pressure_reference_source": "Original acceptance.protocol_rules; primary D-B means only",
               "cost_source": "FULL_ONLINE_CONFIRMATION_INDEX.records[].execution.actor_cpu_seconds",
               "cost_condition_rows": 96, "objects_per_condition": 512, "worker_actor_cpu_added": False}
    write_json(output / "PLOT_PROVENANCE.json", receipt)
    return {"output": str(output), "artificial_fixture": artificial, "forest_estimates": 30,
            "task_domain_rows": 15, "cost_cells": 12, "cost_condition_rows": 96}


def selfcheck(args):
    fixture, _ = read_json(args.fixture_review)
    require(fixture.get("artificial_fixture") is True, "Selfcheck refuses non-artificial report input")
    output = Path(args.output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    fixture = copy.deepcopy(fixture)
    fixture["plot_fixture_note"] = "TEST FIXTURE. Utility interval widths manually varied for layout inspection; these are not measured confidence intervals."
    for collection in ("total_effects", "validation_selected_comparator"):
        for index, row in enumerate(fixture["actual_outcome_analysis"][collection]):
            stat = row["metrics"]["utility"]
            width = (.004, .011, .027, .016)[index % 4]
            stat["fit_t95"] = [stat["mean"] - width, stat["mean"] + width]
    review_path = output / "ARTIFICIAL_ACCEPTANCE_REVIEW.json"
    write_json(review_path, fixture)
    effects = extract_effects(fixture)
    registration = [item["sha256"] for item in fixture.get("input_files", [])
                    if item.get("path", "").endswith("/full_online_confirmation/SELF_REGISTRATION.json")]
    records = []
    for task_index, task in enumerate(TASKS):
        for family_index, family in enumerate(FAMILIES):
            for seed_index, seed in enumerate(effects["fit_seeds"]):
                records.append({"task": task, "family": family, "seed": seed, "domain": "iid",
                    "train_mode": "value", "exec_mode": "value",
                    "data_sha256": hashlib.sha256(("TEST FIXTURE " + task).encode()).hexdigest(),
                    "worker_cpu_seconds": 1e9,
                    "execution": {"actor_cpu_seconds": .512 * (1 + task_index + family_index + .1 * seed_index), "objects": 512}})
    for domain, mode, execution in (("iid", "light", "light"), ("iid", "value", "light"),
                                    ("clock4x", "value", "value")):
        unused = copy.deepcopy(records[0])
        unused.update(domain=domain, train_mode=mode, exec_mode=execution)
        unused["execution"]["actor_cpu_seconds"] = 1e12
        records.append(unused)
    index = {"artificial_fixture": True, "records": records,
             "registration_sha256": registration[0] if registration else "f" * 64}
    index_path = output / "ARTIFICIAL_FULL_ONLINE_INDEX.json"
    write_json(index_path, index)
    render_args = argparse.Namespace(review=review_path, online_summary=None, protocol=None,
                                     online_index=index_path, output=output / "rendered", test_fixture=True)
    rendered = render(render_args)
    exported = json.loads((output / "rendered/plot_data.json").read_text())
    assert exported["points"] == effects["points"] and len(exported["points"]) == 30
    assert sum(point["negative_control"] for point in exported["points"]) == 6
    assert sum(point["pressure_reference_applies"] for point in exported["points"]) == 10
    cost = json.loads((output / "rendered/cost_aggregation.json").read_text())
    assert math.isclose(cost["cells"][0]["actor_cpu_ms_per_object"], 1.35)
    spec = json.loads((output / "rendered/chart_spec.json").read_text())
    assert "content" in spec and len(spec["content"]["data"]) == 6
    assert len(spec["content"]["series"]) == 2 and "TEST FIXTURE" in spec["content"]["meta"]["title"]
    rejections = []
    for name, mutation in (("missing_cost_row", lambda value: value["records"].pop(0)),
                           ("duplicate_cost_row", lambda value: value["records"].append(value["records"][0])),
                           ("wrong_object_count", lambda value: value["records"][0]["execution"].update(objects=16)),
                           ("different_cohort", lambda value: value["records"][0].update(data_sha256="a" * 64))):
        candidate = copy.deepcopy(index)
        mutation(candidate)
        try:
            aggregate_cost(candidate, effects, fixture)
        except PlotError as error:
            rejections.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError(name)
    altered = copy.deepcopy(fixture)
    altered["actual_acceptance"]["protocol_rules"]["pressure_tolerance"] = -.03
    try:
        extract_effects(altered)
    except PlotError as error:
        rejections.append({"case": "changed_pressure_threshold", "rejected": True, "reason": str(error)})
    else:
        raise AssertionError("Changed threshold accepted")
    altered = copy.deepcopy(fixture)
    altered["actual_outcome_analysis"]["validation_selected_comparator"].pop()
    try:
        extract_effects(altered)
    except PlotError as error:
        rejections.append({"case": "omitted_effect_domain", "rejected": True, "reason": str(error)})
    else:
        raise AssertionError("Omitted effect domain accepted")
    direct = {"schema": SCHEMA_ONLINE, "actual_outcome_analysis": fixture["actual_outcome_analysis"]}
    protocol = {"acceptance": fixture["actual_acceptance"]["protocol_rules"], "tasks": list(TASKS),
                "seeds": effects["fit_seeds"], "families": list(FAMILIES),
                "domains": {task: list(DOMAINS[task]) for task in TASKS}, "splits": {"test": [512]}}
    assert extract_effects(direct, protocol) == effects
    write_json(output / "PLOT_SELFCHECK.json", {"artificial_fixture": True, "passed": True,
        "source_fixture": str(Path(args.fixture_review).absolute()), "rendered": rendered,
        "stored_mean_and_interval_passthrough": True, "negative_control_estimates_retained": 6,
        "only_registered_primary_pressure_rows_get_reference": True, "worker_cpu_sentinel_ignored": True,
        "other_domain_and_train_exec_cost_sentinels_ignored": True,
        "direct_online_summary_with_protocol_matches_review": True,
        "widget_schema_shape_checked": True, "rejection_checks": rejections,
        "scope": "Artificial publication mechanics and layout only. No formal run or test data opened."})
    return {"output": str(output), "passed": True, "fixture_only": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rendering = commands.add_parser("render")
    source = rendering.add_mutually_exclusive_group(required=True)
    source.add_argument("--review", help="Completed ACCEPTANCE_REVIEW.json")
    source.add_argument("--online-summary", help="Completed FULL_ONLINE_CONFIRMATION_SUMMARY.json")
    rendering.add_argument("--protocol", help="Required with --online-summary")
    rendering.add_argument("--online-index", required=True, help="Completed FULL_ONLINE_CONFIRMATION_INDEX.json")
    rendering.add_argument("--output", required=True, help="New output directory")
    rendering.add_argument("--test-fixture", action="store_true", help="Force prominent artificial-data labels")
    checking = commands.add_parser("selfcheck")
    checking.add_argument("--fixture-review", required=True, help="Only an artificial_fixture=true report is accepted")
    checking.add_argument("--output", required=True, help="New artificial output directory")
    args = parser.parse_args()
    try:
        result = render(args) if args.command == "render" else selfcheck(args)
    except (PlotError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
