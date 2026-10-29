"""Scientific figures from completed v4 evidence, with explicit scope boundaries.

No task model or heldout dataset is imported. Production mode requires the
completed aggregate and actual native-owner measurement artifacts. Development
mode uses an in-memory layout fixture, visibly watermarked, outside results/.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.text import Text
import numpy as np


ROOT = Path(__file__).resolve().parent
PRIMARY = "ctrnn_state_cpu"
SEEDS = [101, 211, 307, 401, 503]
ORDER = ["rr_full", "fp_no_rollover", "rr_mean_maturity", "rr_shuffle_maturity",
         "rr_fixed_boundary", "rr_frozen_resource", "lif", "alif", "resource_lif",
         "ctrnn", "ctrnn_state", "ctrnn_upper_state", "alif_analog", "ctrnn_analog",
         "ctrnn_state_cpu", "ctrnn_analog_cpu"]
LABELS = dict(zip(ORDER, ["RR, full", "RR, no rollover", "RR, mean maturity",
    "RR, shuffled maturity", "RR, fixed boundary", "RR, frozen resource", "LIF", "ALIF",
    "Resource-LIF", "CT-RNN, 1 mode", "CT-RNN, 8 modes", "CT-RNN, 20 modes",
    "ALIF, analog readout", "CT-RNN, analog readout", "CT-RNN, 8 modes, equal CPU",
    "CT-RNN, analog, equal CPU"]))
COUNTS = [64, 256, 1024, 4096]
CONDITIONS = ["A0", "A2", "B0", "B2"]
COLORS = {"rr": "#155D7A", "rr_variant": "#668DA3", "primary": "#B25A28",
          "baseline": "#727B85", "green": "#34725F", "invalid": "#A0A0A0"}
NATIVE_FIELDS = ("owner_p95_us", "owner_p99_us", "batch_p99_ms", "queue_p95_us",
                 "owner_ticks_per_second", "actual_owner_ticks_measured")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5,
        "axes.titlesize": 12, "axes.labelsize": 11, "axes.titleweight": "semibold",
        "axes.edgecolor": "#5F6870", "axes.labelcolor": "#202A31",
        "text.color": "#202A31", "xtick.color": "#46515B", "ytick.color": "#26343F",
        "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
        "grid.color": "#DCE1E4", "grid.linewidth": .7, "lines.linewidth": 1.5,
        "savefig.dpi": 300, "figure.dpi": 120, "figure.facecolor": "white",
        "axes.facecolor": "white", "svg.fonttype": "none",
        "svg.hashsalt": "rrsnn-v4-scientific-figures-1", "pdf.fonttype": 42})


def statistic(value, bounded=False):
    mean, interval = float(value["mean"]), np.asarray(value["ci95"], dtype=float)
    per_seed = np.asarray(value["training_seed_means"], dtype=float)
    if (interval.shape != (2,) or per_seed.shape != (5,) or not np.isfinite(mean)
            or not np.isfinite(interval).all() or not np.isfinite(per_seed).all()
            or interval[0] > interval[1]
            or abs(float(per_seed.mean())-mean) > 1e-8):
        raise ValueError("Malformed five-seed point estimate or confidence interval")
    if bounded and (min(mean, *interval) < -1e-8 or max(mean, *interval) > 1+1e-8):
        raise ValueError("Normalized utility must lie between zero and one")
    return {"mean": mean, "ci95": interval.tolist(), "training_seed_means": per_seed.tolist()}


def validate_aggregate(data):
    if (data.get("schema") != "rrsnn-v4-paired-aggregate-1"
            or data.get("primary_comparator") != PRIMARY or data.get("training_seeds") != SEEDS
            or data.get("real_future_window") is not False
            or data.get("native_cell_scale_claim") is not False
            or data.get("bootstrap", {}).get("draws") != 10000):
        raise ValueError("Expected the completed frozen synthetic v4 aggregate")
    for dataset in ("test", "shift", "paired"):
        entry = data["datasets"][dataset]
        if entry["scenarios"] != 256 or set(entry["models"]) != set(ORDER):
            raise ValueError("The complete 16-configuration, 256-scenario matrix is required")
        if set(entry["against_primary"]) != set(ORDER)-{PRIMARY}:
            raise ValueError("Every stored paired primary contrast is required")
        base = statistic(entry["models"][PRIMARY]["normalized_expected_utility"], True)
        for model in ORDER:
            current = statistic(entry["models"][model]["normalized_expected_utility"], True)
            if model != PRIMARY:
                delta = statistic(entry["against_primary"][model]["normalized_expected_gain_percentage_points"])
                if abs(delta["mean"]-100*(current["mean"]-base["mean"])) > 1e-8:
                    raise ValueError("Stored normalized contrast has inconsistent units or direction")
    paired = data["datasets"]["paired"]
    if paired["resampled_value_groups"] != 64 or set(paired["counterfactual"]) != set(ORDER):
        raise ValueError("Strict counterfactual figure needs all 64 four-condition groups")
    for model in ORDER:
        if paired["models"][model].get("initial_state_pairing_verified") is not True:
            raise ValueError("The strict paired starting-state witness was not verified")
        current = paired["counterfactual"][model]
        if set(current["expected_utility_by_condition"]) != set(CONDITIONS):
            raise ValueError("A0/A2/B0/B2 condition set is incomplete")
        cells = {key: statistic(current["expected_utility_by_condition"][key]) for key in CONDITIONS}
        effect = statistic(current["shock_interaction_B_minus_A"])
        direct = cells["B2"]["mean"]-cells["B0"]["mean"]-cells["A2"]["mean"]+cells["A0"]["mean"]
        if abs(effect["mean"]-direct) > 1e-8:
            raise ValueError("Counterfactual interaction point estimate has the wrong direction")
    gain = statistic(paired["rr_full_shock_interaction_gain_vs_primary"])
    direct = (paired["counterfactual"]["rr_full"]["shock_interaction_B_minus_A"]["mean"]
              -paired["counterfactual"][PRIMARY]["shock_interaction_B_minus_A"]["mean"])
    if abs(gain["mean"]-direct) > 1e-8:
        raise ValueError("Stored RR-versus-primary interaction contrast is inconsistent")
    return data


def native_evidence(status, original, confirmation):
    if (status.get("same_simultaneous_run") is not False
            or status.get("first4096_invalid_retained") is not True
            or status.get("production_cell_workload") is not False
            or status.get("all_measured_ticks_abstained") is not True):
        raise ValueError("Native scope or invalid-window accounting differs")
    if original["protocol"] != confirmation["protocol"]:
        raise ValueError("Original and confirmation native protocols differ")
    protocol = original["protocol"]
    if (protocol["counts"] != COUNTS or protocol["measured_rounds"] != 32
            or protocol["warmup_rounds"] != 4 or protocol["affinity"] != [8]
            or protocol["production_cells"] is not False):
        raise ValueError("Unexpected native-owner component measurement contract")
    first = {int(row["instances"]): row for row in original["rows"]}
    if set(first) != set(COUNTS) or len(confirmation["rows"]) != 1:
        raise ValueError("Native component matrix or confirmation is incomplete")
    confirmed = confirmation["rows"][0]
    if confirmed["instances"] != 4096 or first[4096]["memory_window_valid"] is not False:
        raise ValueError("Expected the retained invalid first 4096 window and its confirmation")
    selected = [first[count] for count in COUNTS[:-1]]+[confirmed]
    advertised = {int(row["instances"]): row for row in status["component_rows"]}
    if set(advertised) != set(COUNTS):
        raise ValueError("Native status omits a component count")
    for row in selected:
        count = row["instances"]
        if (row["memory_window_valid"] is not True or row["actual_owner_ticks_measured"] != 32*count
                or any(row["memory_limit_events_delta"].get(k, 0) != 0 for k in ("max", "oom", "oom_kill"))
                or row["native"]["scope"]["trained_rr_model"] is not False
                or row["native"]["scope"]["production_cell_workload"] is not False
                or row["native"]["abstained_measured"] != row["actual_owner_ticks_measured"]):
            raise ValueError("An unqualified native window was selected as the main measurement")
        for key in NATIVE_FIELDS:
            if not math.isclose(float(advertised[count][key]), float(row[key]), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Native status does not reproduce its raw measurement")
        if (advertised[count]["peak_rss_bytes"] != row["native"]["peak_rss_bytes"]
                or advertised[count]["binary_sha256"] != row["binary_sha256"]
                or advertised[count]["protocol_sha256"] != row["protocol_sha256"]):
            raise ValueError("Native identity or measured RSS differs from raw evidence")
    if not any(first[4096]["memory_limit_events_delta"].get(k, 0) > 0 for k in ("max", "oom", "oom_kill")):
        raise ValueError("Retained invalid window is missing its pressure witness")
    return {"protocol": protocol, "rows": selected, "invalid_first_4096": first[4096],
            "same_simultaneous_run": False, "unit": "native owner component instances"}


def color(model):
    return COLORS["rr"] if model == "rr_full" else COLORS["primary"] if model == PRIMARY else (
        COLORS["rr_variant"] if model in ORDER[:6] else COLORS["baseline"])


def marker(model):
    return "D" if model == "rr_full" else "s" if model == PRIMARY else "o"


def interval(ax, mean, low, high, y, model, reference=False):
    # Drawing intervals independently also permits a percentile CI whose point
    # estimate happens to lie outside its endpoints.
    ink = color(model)
    if not reference:
        ax.hlines(y, low, high, color=ink, linewidth=1.65, zorder=3)
        ax.vlines([low, high], y-.085, y+.085, color=ink, linewidth=1.1, zorder=3)
    ax.scatter(mean, y, s=47 if model in ("rr_full", PRIMARY) else 34, marker=marker(model),
               facecolor="white" if reference else ink, edgecolor=ink, linewidth=1.2, zorder=4)


def forest_axis(ax, labels=True):
    ax.set_ylim(len(ORDER)-.5, -.5)
    ax.set_yticks(range(len(ORDER)), [LABELS[name] for name in ORDER] if labels else [])
    ax.tick_params(axis="y", length=0, pad=10)
    ax.grid(axis="x")
    ax.spines["left"].set_visible(False)
    for name in ("rr_full", PRIMARY):
        y = ORDER.index(name)
        ax.axhspan(y-.44, y+.44, color=color(name), alpha=.055, zorder=0)
    ax.axhline(5.5, color="#DADEE1", linewidth=.7)
    ax.axhline(13.5, color="#DADEE1", linewidth=.7)
    for text, name in zip(ax.get_yticklabels(), ORDER):
        if name in ("rr_full", PRIMARY):
            text.set_fontweight("semibold")
            text.set_color(color(name))


def header(fig, title, subtitle):
    fig.text(.025, .965, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(.025, .925, subtitle, ha="left", va="top", fontsize=10.5, color="#52616C")


def common_legend(fig, y=.114):
    handles = [Line2D([], [], color=COLORS["rr"], marker="D", linestyle="", label="Full RR"),
               Line2D([], [], color=COLORS["rr_variant"], marker="o", linestyle="", label="RR ablations"),
               Line2D([], [], color=COLORS["baseline"], marker="o", linestyle="", label="Other controls"),
               Line2D([], [], color=COLORS["primary"], marker="s", linestyle="", label="Locked primary")]
    fig.legend(handles=handles, loc="center", bbox_to_anchor=(.60, y), ncol=4,
               frameon=False, fontsize=9.6, handletextpad=.45, columnspacing=1.6)


def utility_figure(data):
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 9.0))
    fig.subplots_adjust(left=.285, right=.975, bottom=.205, top=.865, wspace=.18)
    header(fig, "Synthetic closed-loop delivered-query utility",
           "All 16 prespecified configurations · 977 registered trainable parameters · five training seeds")
    plotted = {}
    for axis, dataset, title in zip(axes, ("test", "shift"), ("a  Heldout test scenarios", "b  Distribution shift")):
        forest_axis(axis, labels=dataset == "test")
        axis.set_title(title, loc="left", pad=12)
        axis.set_xlim(0, 100)
        axis.set_xlabel("Normalized expected utility (% of oracle)", labelpad=10)
        plotted[dataset] = {}
        for index, name in enumerate(ORDER):
            item = statistic(data["datasets"][dataset]["models"][name]["normalized_expected_utility"], True)
            interval(axis, 100*item["mean"], 100*item["ci95"][0], 100*item["ci95"][1], index, name)
            plotted[dataset][name] = item
    common_legend(fig)
    caption = ("Points are mean per-scenario expected utility divided by the scenario's DP optimum; bars are pointwise 95% percentile intervals.\n"
               "10,000 crossed seed × scenario resamples after averaging four latent paths. Five seeds limit training-variability inference; realized query draws are not used here.\n"
               "The primary is the eight-mode CT-RNN trained to the paired RR CPU budget. Synthetic heldout scenarios do not establish a production future window.")
    fig.text(.025, .068, caption, ha="left", va="top", fontsize=9.0, linespacing=1.45)
    return fig, {"title": "Synthetic closed-loop delivered-query utility", "caption": caption,
                 "data": plotted, "unit": "fraction of per-scenario DP optimum; displayed as percent"}


def contrast_figure(data):
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 9.0))
    fig.subplots_adjust(left=.285, right=.975, bottom=.205, top=.865, wspace=.18)
    header(fig, "Paired utility contrasts against the locked primary",
           "Configuration minus CT-RNN, eight modes, equal training CPU · full RR highlighted")
    maximum = max(abs(endpoint) for dataset in ("test", "shift")
                  for value in data["datasets"][dataset]["against_primary"].values()
                  for endpoint in [value["normalized_expected_gain_percentage_points"]["mean"],
                                   *value["normalized_expected_gain_percentage_points"]["ci95"]])
    extent = max(1., maximum*1.12)
    plotted = {}
    for axis, dataset, title in zip(axes, ("test", "shift"), ("a  Heldout test scenarios", "b  Distribution shift")):
        forest_axis(axis, labels=dataset == "test")
        axis.axvline(0, color="#65737C", linestyle="--", linewidth=1)
        axis.set_xlim(-extent, extent)
        axis.set_title(title, loc="left", pad=12)
        axis.set_xlabel("Gain over primary (percentage points)", labelpad=10)
        plotted[dataset] = {}
        for index, name in enumerate(ORDER):
            if name == PRIMARY:
                interval(axis, 0, 0, 0, index, name, reference=True)
                plotted[dataset][name] = {"exact_reference_identity": True, "mean": 0., "ci95": None}
            else:
                item = statistic(data["datasets"][dataset]["against_primary"][name]["normalized_expected_gain_percentage_points"])
                interval(axis, item["mean"], *item["ci95"], index, name)
                plotted[dataset][name] = item
    common_legend(fig)
    caption = ("Intervals are the stored paired contrast estimates; they are not obtained by subtracting marginal confidence limits. The open square is the exact zero reference.\n"
               "Pointwise 95% percentile intervals from 10,000 crossed seed × scenario resamples. All 16 configurations are shown in a fixed order.\n"
               "Expected-utility contrasts average four latent paths; realized query draws do not enter these intervals. Five seeds limit precision; there is no family-wise significance claim.")
    fig.text(.025, .068, caption, ha="left", va="top", fontsize=9.0, linespacing=1.45)
    return fig, {"title": "Paired utility contrasts against the locked primary", "caption": caption,
                 "data": plotted, "unit": "percentage-point change in normalized expected utility"}


def counterfactual_figure(data):
    pair = data["datasets"]["paired"]
    fig = plt.figure(figsize=(14.2, 9.3))
    left = fig.add_axes([.075, .235, .35, .60])
    right = fig.add_axes([.725, .235, .245, .60])
    header(fig, "Strict maturity × resource-shock counterfactual",
           "Identical pre-cue state, item values, budget, memory total and average maturity within each matched value group")
    left.set_title("a  Full RR and the locked primary", loc="left", pad=12)
    selected = {}
    maximum = 0.
    for name in ("rr_full", PRIMARY):
        selected[name] = {}
        for profile, line_style in (("A", "-"), ("B", "--")):
            cells = [statistic(pair["counterfactual"][name]["expected_utility_by_condition"][profile+str(shock)]) for shock in (0, 2)]
            mean = [item["mean"] for item in cells]
            label = ("RR" if name == "rr_full" else "Primary")+f", profile {profile}"
            left.plot([0, 2], mean, color=color(name), marker=marker(name), linestyle=line_style,
                      label=label, markersize=6)
            for x, item in zip((0, 2), cells):
                low, high = item["ci95"]
                left.vlines(x, low, high, color=color(name), linewidth=1.2)
                left.hlines([low, high], x-.055, x+.055, color=color(name), linewidth=1)
                maximum = max(maximum, high, item["mean"])
            selected[name][profile] = cells
    left.set_xlim(-.25, 2.25)
    left.set_ylim(0, max(.1, maximum*1.12))
    left.set_xticks([0, 2])
    left.set_xlabel("Announced resource reduction (budget units)", labelpad=10)
    left.set_ylabel("Expected delivered-query utility", labelpad=10)
    left.grid(axis="y")
    left.legend(frameon=False, fontsize=9.8, loc="best")
    forest_axis(right)
    right.tick_params(axis="y", labelsize=9.7)
    right.set_title("b  Shock interaction", loc="left", pad=12)
    interactions = {}
    maximum = max(abs(value) for name in ORDER
                  for value in [pair["counterfactual"][name]["shock_interaction_B_minus_A"]["mean"],
                                *pair["counterfactual"][name]["shock_interaction_B_minus_A"]["ci95"]])
    extent = max(.02, maximum*1.15)
    right.set_xlim(-extent, extent)
    right.axvline(0, color="#65737C", linestyle="--", linewidth=1)
    right.set_xlabel("(B₂ − B₀) − (A₂ − A₀)\nExpected-utility units", labelpad=10)
    for index, name in enumerate(ORDER):
        item = statistic(pair["counterfactual"][name]["shock_interaction_B_minus_A"])
        interval(right, item["mean"], *item["ci95"], index, name)
        interactions[name] = item
    gain = statistic(pair["rr_full_shock_interaction_gain_vs_primary"])
    text = f"RR − primary interaction: {gain['mean']:+.4f}  [95% CI {gain['ci95'][0]:+.4f}, {gain['ci95'][1]:+.4f}]"
    fig.text(.075, .16, text, fontsize=10.6, fontweight="semibold", color=COLORS["rr"])
    caption = ("Profile A deadlines: (1, 1, 3, 3); profile B: (2, 2, 2, 2). Both have mean maturity two. Shock levels are zero and two budget units.\n"
               "All four conditions remain together within each of 64 resampled value groups; five training seeds form the crossed factor. Initial-state witnesses are required.\n"
               "Bars are stored pointwise 95% intervals from 10,000 resamples, averaging four latent paths per cell. Realized terminal query draws are not used in these expected-utility intervals.")
    fig.text(.025, .095, caption, ha="left", va="top", fontsize=9.0, linespacing=1.5)
    return fig, {"title": "Strict maturity × resource-shock counterfactual", "caption": caption,
                 "condition_curves": selected, "interaction": interactions,
                 "rr_minus_primary_interaction": gain, "unit": "raw expected delivered-query utility"}


def native_figure(evidence):
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.8))
    fig.subplots_adjust(left=.085, right=.975, bottom=.245, top=.845, wspace=.26, hspace=.43)
    header(fig, "Native owner components: durability-path resource profile",
           "CPU 8 · one bounded FIFO · fixed untrained Q24 projection · all measured output attempts abstained")
    rows, invalid = evidence["rows"], evidence["invalid_first_4096"]
    counts = [row["instances"] for row in rows]
    definitions = [
        ("a  Owner tick latency", "Wall time (ms; queue age excluded)",
         [("owner_p95_us", .001, "p95", COLORS["rr"], "o"), ("owner_p99_us", .001, "p99", COLORS["primary"], "D")]),
        ("b  FIFO queue and complete batch", "Wall time (s)",
         [("queue_p95_us", .000001, "Queue age p95", COLORS["rr"], "o"),
          ("batch_p99_ms", .001, "Complete batch p99", COLORS["primary"], "D")]),
        ("c  Measured owner throughput", "Owner ticks / wall second",
         [("owner_ticks_per_second", 1., "Measured ticks", COLORS["green"], "o")]),
        ("d  Process high-water memory", "Pre-reopen peak RSS (MiB)",
         [("peak_rss_bytes", 1/2**20, "Process high-water mark", COLORS["green"], "o")]),
    ]
    plotted = {}
    for axis, (title, ylabel, fields) in zip(axes.flat, definitions):
        axis.set_title(title, loc="left", pad=9)
        axis.set_xscale("log", base=2)
        axis.set_xticks(COUNTS, [str(x) for x in COUNTS])
        axis.set_xlim(48, 5500)
        axis.set_xlabel("Native owner component instances")
        axis.set_ylabel(ylabel)
        axis.grid(axis="y")
        for key, factor, label, ink, shape in fields:
            values = [float(row["native"][key] if key == "peak_rss_bytes" else row[key])*factor for row in rows]
            bad = float(invalid["native"][key] if key == "peak_rss_bytes" else invalid[key])*factor
            axis.plot(counts, values, color=ink, marker=shape, label=label, markersize=5.5)
            axis.scatter([4096], [bad], color=COLORS["invalid"], marker="x", s=45, linewidth=1.5, zorder=4)
            plotted[key] = {"instances": counts, "values": values, "conversion_factor": factor,
                            "invalid_first_4096_value": bad}
        axis.set_ylim(bottom=0)
        axis.legend(loc="best", frameon=False, fontsize=9.0)
    fig.legend(handles=[Line2D([], [], color=COLORS["invalid"], marker="x", linestyle="",
                               label="Retained first 4096 window: shared memory-pressure events")],
               loc="center", bbox_to_anchor=(.5, .161), frameon=False, fontsize=9.5)
    caption = ("Each instance is one NeuronRuntime + SparseJournal + independent FileAnchorWitnessStore. Main points use valid windows; 4096 uses the confirmation run.\n"
               "Measurements occurred in separate shared-host windows: four warmup and 32 measured rounds. Owner latency includes witness fsync; queue age is separate.\n"
               "p95/p99 are descriptive run quantiles; there are only 32 complete-batch samples. RSS includes initialization and timing arrays, captured before reopen.\n"
               "This view measures the native component path with a fixed projection. It does not qualify trained RR scale performance or production Cell deployment.")
    fig.text(.025, .112, caption, ha="left", va="top", fontsize=8.9, linespacing=1.45)
    return fig, {"title": "Native owner components: durability-path resource profile", "caption": caption,
                 "data": plotted, "unit": "native owner component instances", "production_cells": False,
                 "trained_rr_scale_measurement": False, "same_simultaneous_run": False,
                 "invalid_window_events": invalid["memory_limit_events_delta"]}


def watermark(fig):
    fig.text(.5, .50, "DEVELOPMENT LAYOUT ONLY\nNOT EXPERIMENT RESULTS", ha="center", va="center",
             rotation=24, fontsize=27, color="#C16C65", alpha=.25, fontweight="bold", zorder=100)


def check_text_layout(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    violations = []
    inactive_tick_labels = set()
    # Locators can retain Text objects for ticks beyond the view limits. The
    # Axis renderer does not draw those labels, although get_visible() is true.
    for axis in fig.axes:
        for coordinate, limits in ((axis.xaxis, axis.get_xlim()), (axis.yaxis, axis.get_ylim())):
            low, high = sorted(limits)
            for tick in coordinate.get_major_ticks()+coordinate.get_minor_ticks():
                if tick.get_loc() < low-1e-10 or tick.get_loc() > high+1e-10:
                    inactive_tick_labels.update((id(tick.label1), id(tick.label2)))
    for item in fig.findobj(Text):
        if id(item) in inactive_tick_labels or not item.get_visible() or not item.get_text().strip():
            continue
        box = item.get_window_extent(renderer)
        if box.x0 < bounds.x0-3 or box.x1 > bounds.x1+3 or box.y0 < bounds.y0-3 or box.y1 > bounds.y1+3:
            violations.append(item.get_text())
    if violations:
        raise ValueError(f"Figure text extends beyond canvas: {violations[:4]}")


def save_figure(fig, evidence, directory, basename, development=False):
    if development:
        watermark(fig)
    check_text_layout(fig)
    description = evidence["caption"]+("\nDEVELOPMENT LAYOUT FIXTURE; NOT EXPERIMENT RESULTS." if development else "")
    paths = []
    for suffix in ("png", "svg"):
        path = directory/f"{basename}.{suffix}"
        fig.savefig(path, format=suffix, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=.16,
                    metadata={"Title": evidence["title"], "Description": description,
                              **({"Date": None} if suffix == "svg" else {})})
        paths.append({"filename": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    plt.close(fig)
    return {"files": paths, "evidence": evidence}


def render_set(data, native, directory, development=False):
    style()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    figures = []
    for name, builder, argument in (
            ("01_normalized_utility", utility_figure, data),
            ("02_gain_over_primary", contrast_figure, data),
            ("03_maturity_shock_counterfactual", counterfactual_figure, data),
            ("04_native_owner_costs", native_figure, native)):
        fig, evidence = builder(argument)
        figures.append(save_figure(fig, evidence, directory, name, development))
    return figures


def make_figures(aggregate_path, status_path, original_path, confirmation_path, destination):
    sources = {"aggregate": {"path": str(Path(aggregate_path).resolve()), "sha256": sha(aggregate_path)},
               "native_status": {"path": str(Path(status_path).resolve()), "sha256": sha(status_path)},
               "native_original": {"path": str(Path(original_path).resolve()), "sha256": sha(original_path)},
               "native_confirmation": {"path": str(Path(confirmation_path).resolve()), "sha256": sha(confirmation_path)},
               "figure_script": {"path": str(Path(__file__).resolve()), "sha256": sha(__file__)}}
    destination = Path(destination).resolve()
    manifest_path = destination/"figures_manifest.json"
    if manifest_path.exists():
        existing = read_json(manifest_path)
        if existing["sources"] != sources:
            raise ValueError("Existing figures have different evidence or plotting source")
        for figure in existing["figures"]:
            for file in figure["files"]:
                if sha(destination/file["filename"]) != file["sha256"]:
                    raise ValueError("An existing figure was changed")
        return existing
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Refusing to replace an unmanifested nonempty figure directory")
    data = validate_aggregate(read_json(aggregate_path))
    native = native_evidence(read_json(status_path), read_json(original_path), read_json(confirmation_path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rr-v4-final-figures-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        figures = render_set(data, native, staging)
        result = {"schema": "rrsnn-v4-scientific-figures-1", "sources": sources, "figures": figures,
                  "all_16_configurations_in_fixed_order": ORDER, "primary_comparator": PRIMARY,
                  "png_dpi": 300, "svg_vector_text": True, "matplotlib_version": matplotlib.__version__,
                  "synthetic_task_figures_separate_from_native_component_costs": True,
                  "confidence_interval_scope": "Stored pointwise intervals; five training seeds; no family-wise claim.",
                  "mock_final_results_created": False, "native_instances_relabelled_as_cells": False}
        (staging/"figures_manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
        for record in sources.values():
            if sha(record["path"]) != record["sha256"]:
                raise ValueError("Input evidence changed while figures were rendering")
        if destination.exists():
            destination.rmdir()  # Only the already-checked empty directory is removed.
        staging.rename(destination)
    return result


def development_fixture():
    """In-memory layout data only; never saved as an experimental aggregate."""
    def summary(mean, width=.035):
        return {"mean": mean, "ci95": [mean-width, mean+width], "training_seed_means": [mean]*5}
    data = {"schema": "rrsnn-v4-paired-aggregate-1", "primary_comparator": PRIMARY,
            "training_seeds": SEEDS, "real_future_window": False, "native_cell_scale_claim": False,
            "bootstrap": {"draws": 10000}, "datasets": {}}
    for dataset in ("test", "shift", "paired"):
        means = {name: .51+.018*index-(.05 if dataset == "shift" else 0) for index, name in enumerate(ORDER)}
        entry = {"scenarios": 256, "resampled_value_groups": 64 if dataset == "paired" else 256,
                 "models": {}, "against_primary": {}}
        for name in ORDER:
            entry["models"][name] = {"normalized_expected_utility": summary(means[name]), "initial_state_pairing_verified": True}
            if name != PRIMARY:
                entry["against_primary"][name] = {"normalized_expected_gain_percentage_points": summary(100*(means[name]-means[PRIMARY]), 4.)}
        data["datasets"][dataset] = entry
    pair = data["datasets"]["paired"]
    pair["counterfactual"] = {}
    for index, name in enumerate(ORDER):
        effect = -.08+.012*index
        cells = {"A0": 2.5, "A2": 1.7, "B0": 2.4, "B2": 1.6+effect}
        pair["counterfactual"][name] = {"expected_utility_by_condition": {key: summary(value, .15) for key, value in cells.items()},
                                        "shock_interaction_B_minus_A": summary(effect, .04)}
    delta = pair["counterfactual"]["rr_full"]["shock_interaction_B_minus_A"]["mean"]-pair["counterfactual"][PRIMARY]["shock_interaction_B_minus_A"]["mean"]
    pair["rr_full_shock_interaction_gain_vs_primary"] = summary(delta, .05)
    def native_row(count, valid=True):
        return {"instances": count, "owner_p95_us": 2500., "owner_p99_us": 5000.,
                "batch_p99_ms": count*2., "queue_p95_us": count*1000., "owner_ticks_per_second": 700.,
                "actual_owner_ticks_measured": count*32, "native": {"peak_rss_bytes": count*20000},
                "memory_limit_events_delta": {"max": 0 if valid else 1}, "memory_window_valid": valid}
    native = {"rows": [native_row(count) for count in COUNTS], "invalid_first_4096": native_row(4096, False)}
    return validate_aggregate(data), native


def validate_development(preview_directory=None):
    data, native = development_fixture()
    if preview_directory is None:
        with tempfile.TemporaryDirectory(prefix="rr-v4-figure-layout-") as temporary:
            figures = render_set(data, native, temporary, development=True)
        retained = False
    else:
        directory = Path(preview_directory).resolve()
        if directory == ROOT or ROOT in directory.parents:
            raise ValueError("Development previews must be outside the experiment directory")
        figures = render_set(data, native, directory, development=True)
        retained = True
    assert len(figures) == 4 and all(len(figure["files"]) == 2 for figure in figures)
    outside = json.loads(json.dumps(data))
    for dataset in ("test", "shift"):
        for value in outside["datasets"][dataset]["against_primary"].values():
            value["normalized_expected_gain_percentage_points"]["ci95"] = [-.1, .1]
    contrast, _ = contrast_figure(outside)
    for axis, dataset in zip(contrast.axes, ("test", "shift")):
        low, high = axis.get_xlim()
        assert all(low <= value["normalized_expected_gain_percentage_points"]["mean"] <= high
                   for value in outside["datasets"][dataset]["against_primary"].values())
    plt.close(contrast)
    for value in outside["datasets"]["paired"]["counterfactual"].values():
        value["shock_interaction_B_minus_A"]["ci95"] = [-.0001, .0001]
    counterfactual, _ = counterfactual_figure(outside)
    low, high = counterfactual.axes[1].get_xlim()
    assert all(low <= value["shock_interaction_B_minus_A"]["mean"] <= high
               for value in outside["datasets"]["paired"]["counterfactual"].values())
    plt.close(counterfactual)
    rejected = json.loads(json.dumps(data))
    rejected["datasets"]["test"]["against_primary"]["rr_full"]["normalized_expected_gain_percentage_points"]["mean"] += 1
    try:
        validate_aggregate(rejected)
    except ValueError:
        pass
    else:
        raise AssertionError("Inconsistent contrast accepted")
    return {"schema": "rrsnn-v4-scientific-figures-development-1", "all_passed": True,
            "four_png_and_four_svg_rendered": True, "all_text_inside_canvas": True,
            "inconsistent_contrast_rejected": True, "production_or_holdout_data_opened": False,
            "point_estimate_outside_percentile_interval_remains_visible": True,
            "fixture_aggregate_written": False, "previews_watermarked_development_only": True,
            "development_preview_retained": retained, "source_sha256": sha(__file__),
            "matplotlib_version": matplotlib.__version__}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, default=ROOT/"results"/"aggregate.json")
    parser.add_argument("--native-status", type=Path, default=ROOT/"hepta"/"r5_local_status.json")
    parser.add_argument("--native-original", type=Path, default=ROOT/"hepta"/"native_results"/"component_benchmark.json")
    parser.add_argument("--native-confirmation", type=Path, default=ROOT/"hepta"/"native_results"/"component_benchmark_confirmation_4096.json")
    parser.add_argument("--output", type=Path, default=ROOT/"results"/"figures")
    parser.add_argument("--validate-development", action="store_true")
    parser.add_argument("--preview-directory", type=Path)
    arguments = parser.parse_args()
    if arguments.validate_development:
        report = validate_development(arguments.preview_directory)
        (ROOT/"figures_validation.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
        print(json.dumps(report))
    else:
        report = make_figures(arguments.aggregate, arguments.native_status, arguments.native_original,
                              arguments.native_confirmation, arguments.output)
        print(json.dumps({"figures": len(report["figures"]), "directory": str(arguments.output)}))
