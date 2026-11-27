"""Plot only completed, independently audited C2 archive records; no model calls."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import tarfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, StrMethodFormatter


HERE = Path(__file__).resolve().parent
COLORS = ("#217f9b", "#aa6c87")
EXPECTED_FITS = ("hcsn-s211-lr0.001", "hcsn-s307-lr0.001")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return {"bytes": path.stat().st_size, "sha256": result.hexdigest()}


def collect(archive, receipt_path, audit_path):
    archive_identity = identity(archive)
    receipt, audit = [json.loads(path.read_text()) for path in (receipt_path, audit_path)]
    require(all(archive_identity[key] == receipt[key] for key in ("bytes", "sha256")), "exact complete artifact identity")
    require(audit["status"] == "VERIFIED_ARCHIVED_CONTINUATIONS" and audit["archive_sha256"] == archive_identity["sha256"]
            and audit["independent_review_forward_calls"] == audit["independent_review_optimizer_calls"] == 0,
            "complete independent archive review must precede reporting")
    names = {"MANIFEST.json", "source/REQUEST.json", "source/BINDINGS.json", "source/FREEZE.json",
             "run/TERMINAL.json", "native/NATIVE_TERMINAL.json"}
    for fit in EXPECTED_FITS:
        names.update("run/" + fit + "/" + name for name in ("RESULT.json", "COST.json", "events.jsonl"))
    selected, member_names = {}, []
    # The full archive identity is checked above. Only plotting inputs are
    # retained and individually rehashed; model checkpoint bytes are not loaded.
    with tarfile.open(archive, "r|xz") as source:
        for item in source:
            path = Path(item.name)
            require(item.isfile() and not path.is_absolute() and ".." not in path.parts and item.name not in member_names,
                    "regular unique archive members")
            member_names.append(item.name)
            if item.name in names:
                selected[item.name] = source.extractfile(item).read()
    require(set(selected) == names, "all required actual reporting inputs present")
    manifest = json.loads(selected["MANIFEST.json"])
    require(set(member_names) == set(manifest["members"]) | {"MANIFEST.json"}
            and len(member_names) == audit["archive_members_verified"], "same complete audited archive membership")
    require(len(selected["MANIFEST.json"]) == receipt["manifest_bytes"]
            and hashlib.sha256(selected["MANIFEST.json"]).hexdigest() == receipt["manifest_sha256"], "archive manifest receipt")
    input_identities = {}
    for name, payload in selected.items():
        observed = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        expected = manifest["members"].get(name)
        if expected is not None:
            require(all(observed[key] == expected[key] for key in observed), "exact plotted source member " + name)
        input_identities[name] = observed
    read = lambda name: json.loads(selected[name])
    request, bindings, freeze = [read("source/" + name) for name in ("REQUEST.json", "BINDINGS.json", "FREEZE.json")]
    require(request["identity"] == bindings["identity"] == freeze["identity"] == manifest["identity"], "unchanged continuation identity")
    for name in ("REQUEST.json", "BINDINGS.json"):
        require(input_identities["source/" + name]["sha256"] == freeze["files"][name], "frozen experiment input " + name)
    terminal, native = read("run/TERMINAL.json"), read("native/NATIVE_TERMINAL.json")
    require(native["terminal_publication_confirmed"] and native["output_complete"]
            and terminal["status"] not in ("RUNNING", "FINISHING")
            and set(terminal["fits"]) == set(EXPECTED_FITS), "both actual terminal outcomes required")
    fits = []
    for name in EXPECTED_FITS:
        prefix = "run/" + name + "/"
        result, cost = read(prefix + "RESULT.json"), read(prefix + "COST.json")
        require(cost == terminal["fits"][name] and cost["result_sha256"] == input_identities[prefix + "RESULT.json"]["sha256"],
                "terminal cost binds the exact plotted result")
        require(result["events_sha256"] == input_identities[prefix + "events.jsonl"]["sha256"], "result binds complete event journal")
        events = [json.loads(line) for line in selected[prefix + "events.jsonl"].splitlines()]
        updates = [{"elapsed_wall_seconds": row["optimizer_return_elapsed_seconds"], "new_completed_updates": row["new_number"],
                    "logical_main_update": row["number"], "current_epoch": row["epoch"], "batch_index": row["batch_index"],
                    "within_scientific_budget": row["within_scientific_budget"]}
                   for row in events if row["kind"] == "optimizer_completed"]
        epochs = [{"epoch": row["epoch"], "elapsed_wall_seconds": row["new_phase_wall_seconds"],
                   "macro_f1": row["development"]["macro_f1_11_classes"], "train_events": row["events"],
                   "development_events": row["development"]["events"]} for row in result["epochs"]]
        require(len(updates) == result["new_optimizer_completed"]
                and [row["new_completed_updates"] for row in updates] == list(range(1, len(updates) + 1)), "every actual optimizer completion retained")
        require([row["epoch"] for row in epochs] == list(range(result["start_epoch"] + 1, result["last_complete_epoch"] + 1)),
                "every new complete epoch retained")
        require(all(row["train_events"] == 89216 and row["development_events"] == 31952 for row in epochs), "full original ABC/D population")
        for sequence in (epochs, updates):
            require([row["elapsed_wall_seconds"] for row in sequence] == sorted(row["elapsed_wall_seconds"] for row in sequence),
                    "monotone actual observation times")
        independent = next(row for row in audit["reviews"] if row["fit"] == name)
        require(independent["new_optimizer_completed"] == len(updates) and independent["last_complete_epoch"] == result["last_complete_epoch"]
                and independent["stopping"] == result["stopping"] and independent["cost"] == cost, "exact independently reviewed fit")
        selected_complete = result["selected_development_complete"]
        selected_score = (result["selected_development"]["macro_f1_11_classes"] if selected_complete else result["stopping"]["best"])
        require(selected_score == result["stopping"]["best"] and math.isfinite(selected_score), "actual final selected best")
        inherited = bindings["fits"][name]["stopping"]
        anchor_epoch = result["last_complete_epoch"] - result["stopping"]["stale_epochs"]
        complete_history = bindings["fits"][name]["inherited_history"] + result["epochs"]
        require(complete_history[anchor_epoch - 1]["development"]["macro_f1_11_classes"] == result["stopping"]["plateau_anchor"],
                "plateau anchor is distinct from strict best and verified against complete history")
        for key, expected in {"scientific_admission": "HOLD", "original_controller_terminal": "UNKNOWN", "full_six_fit_replay": False,
                              "independent_complete_training_replays": 0, "confirmation_access": False}.items():
            require(result[key] == expected, "unchanged qualification scope " + key)
        fits.append({"name": name, "seed": int(name.split("-s")[1].split("-")[0]), "start_epoch": result["start_epoch"],
                     "inherited_best_epoch": inherited["best_epoch"], "inherited_best_macro_f1": inherited["best"],
                     "epochs": epochs, "optimizer_completions": updates, "new_completed_updates": len(updates),
                     "new_micro_forwards_started": result["new_micro_forwards_started"], "last_complete_epoch": result["last_complete_epoch"],
                     "selected_epoch": result["stopping"]["best_epoch"], "selected_macro_f1": selected_score,
                     "selected_development_complete": selected_complete,
                     "selected_result_elapsed_wall_seconds": result["new_phase_wall_seconds_before_exit"],
                     "training_stop_elapsed_wall_seconds": result["training_end_new_phase_wall_seconds"],
                     "full_process_exit_elapsed_wall_seconds": cost["full_fresh_process_wall_seconds"],
                     "status": result["status"], "stop_reason": result["stop_reason"], "stopping": result["stopping"],
                     "plateau_anchor_epoch": anchor_epoch,
                     "partial_epoch_cursor": result["live_partial_epoch_cursor"],
                     "open_optimizer_completion_interval": result["open_optimizer_completion_interval"],
                     "late_optimizer_completions": result["optimizer_completions_after_scientific_deadline"], "cost": cost})
    return {"schema": "hepta.c2-continuation-progress-figure.v1", "identity": request["identity"], "fits": fits,
            "budget": request["budget"], "archive_identity": archive_identity, "archive_filename": archive.name,
            "archive_manifest_member_count": len(member_names), "plotted_input_members": input_identities,
            "frozen_execution_source_sha256": freeze["files"], "reader_source_sha256": audit["reader_source_sha256"],
            "artifact_receipt_identity": identity(receipt_path), "independent_review_identity": identity(audit_path),
            "plot_source_identity": identity(Path(__file__)), "matplotlib_version": matplotlib.__version__,
            "quality_scope": "Subject D development macro F1 is used to select checkpoints; it is not a held-out test result.",
            "model_scope": "Two seeds of the original single-layer QPR core with frozen physics; no claim of a model-family comparison or the new current-state kernel.",
            "time_scope": "Each fit uses its own new dispatch-relative elapsed wall time, including setup/imports/validation. Costs and stopping times come from actual terminal records.",
            "selection_marker_scope": "Stars show the selected checkpoint score at the final result timestamp, not new training epochs. A hollow star denotes a recorded best whose final development reevaluation was incomplete.",
            "count_scope": "All recorded actual optimizer completions are included, including any partial final epoch or late completion. Original duplicated tail work is not refunded.",
            "resume_scope": "The four earlier cold probes restored original complete-epoch checkpoints 126/127. New partial-epoch checkpoints were saved and structurally audited only; no new training from these partial checkpoints was executed.",
            "rendering": "All new complete-epoch observations and all optimizer completion events. No smoothing, omitted points, fitted curve, or extension beyond actual process exit.",
            "original_controller_terminal": "UNKNOWN", "independent_complete_training_replays": 0, "scientific_admission": "HOLD",
            "model_calls": 0, "optimizer_calls": 0, "new_reference_calculations": 0}


def draw(data, output):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.hashsalt": "hepta-c2-continuation-progress-v1"})
    figure, axes = plt.subplots(1, 2, figsize=(14.8, 8.5))
    figure.subplots_adjust(left=.075, right=.975, bottom=.295, top=.78, wspace=.25)
    figure.suptitle("C2 continuations: quality and actual work", x=.075, y=.967,
                   ha="left", fontsize=21, fontweight="bold", color="#173042")
    figure.text(.075, .91, "Original QPR core · frozen physics · learning rate 0.001 · two seeds · single-thread CPU",
                fontsize=11, color="#536474")
    budget = data["budget"]["scientific_wall_seconds_per_fit"]
    reserve = budget - data["budget"]["finalization_reserve_seconds"]
    maximum_exit = max(row["full_process_exit_elapsed_wall_seconds"] for row in data["fits"])
    end = max(budget, maximum_exit) * 1.055
    all_scores = [row["macro_f1"] for fit in data["fits"] for row in fit["epochs"]]
    all_scores += [fit[key] for fit in data["fits"] for key in ("inherited_best_macro_f1", "selected_macro_f1")]
    spread = max(all_scores) - min(all_scores)
    axes[0].set_ylim(min(all_scores) - max(.008, .16 * spread), max(all_scores) + max(.012, .22 * spread))
    axes[0].yaxis.set_major_formatter(StrMethodFormatter("{x:.3f}"))
    axes[1].set_ylim(-2, max(row["new_completed_updates"] for row in data["fits"]) * 1.25)
    axes[1].yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    for axis, title in zip(axes, ("A   Development quality at complete epochs", "B   Actual optimizer completions, including partial epochs")):
        axis.set_title(title, loc="left", fontsize=12, fontweight="bold", color="#173042", pad=17)
        axis.set_xlim(-80, end)
        axis.set_xticks((0, 1500, 3000, 4500, 6000))
        axis.set_xlabel("New elapsed wall time · seconds", fontsize=10.5, labelpad=11)
        axis.tick_params(colors="#536474")
        axis.grid(axis="y", color="#e5e9ed", linewidth=.8)
        axis.set_axisbelow(True)
        axis.axvspan(reserve, budget, color="#eef1f4", alpha=.8, zorder=0)
        axis.axvline(reserve, color="#9babb7", linestyle=":", linewidth=1.2, zorder=1)
        axis.axvline(budget, color="#758795", linestyle="--", linewidth=1.2, zorder=1)
    axes[0].set_ylabel("Subject D macro F1 · 11 classes", fontsize=11, labelpad=10)
    axes[1].set_ylabel("New completed optimizer calls", fontsize=11, labelpad=10)
    for index, (fit, color) in enumerate(zip(data["fits"], COLORS)):
        epochs, updates = fit["epochs"], fit["optimizer_completions"]
        label = f"Seed {fit['seed']} (resume after epoch {fit['start_epoch']})"
        axes[0].plot([row["elapsed_wall_seconds"] for row in epochs], [row["macro_f1"] for row in epochs],
                     color=color, marker="o" if index == 0 else "s", markersize=5.0, linewidth=1.65,
                     markeredgecolor="white", markeredgewidth=.6, label=label, zorder=4)
        axes[0].hlines(fit["inherited_best_macro_f1"], 0, fit["full_process_exit_elapsed_wall_seconds"],
                       color=color, linewidth=1.1, linestyle=(0, (4, 3)), alpha=.8, zorder=2)
        axes[0].scatter(fit["selected_result_elapsed_wall_seconds"], fit["selected_macro_f1"],
                        marker="*", s=155, facecolor=color if fit["selected_development_complete"] else "white",
                        edgecolor="white" if fit["selected_development_complete"] else color, linewidth=.7, zorder=7)
        text = f"Selected epoch {fit['selected_epoch']}\nF1 {fit['selected_macro_f1']:.6f}"
        if not fit["selected_development_complete"]:
            text += "\nFinal D reevaluation incomplete"
        axes[0].annotate(text, xy=(fit["selected_result_elapsed_wall_seconds"], fit["selected_macro_f1"]),
                         xytext=(-18, 22) if index == 0 else (.94, .24),
                         textcoords="offset points" if index == 0 else "axes fraction", ha="right", va="center",
                         fontsize=9.3, color=color, bbox=dict(boxstyle="round,pad=.35", fc="white", ec="#d8e1e7"),
                         arrowprops=dict(arrowstyle="-", color=color, lw=.8), zorder=8)
        x = [0] + [row["elapsed_wall_seconds"] for row in updates] + [fit["full_process_exit_elapsed_wall_seconds"]]
        y = [0] + [row["new_completed_updates"] for row in updates] + [fit["new_completed_updates"]]
        axes[1].step(x, y, where="post", color=color, linewidth=1.7, zorder=4)
        axes[1].scatter([row["elapsed_wall_seconds"] for row in updates], [row["new_completed_updates"] for row in updates],
                        s=5, color=color, alpha=.45, linewidths=0, zorder=4)
        stop = fit["full_process_exit_elapsed_wall_seconds"]
        axes[1].scatter(stop, fit["new_completed_updates"], marker="D", s=45, color=color,
                        edgecolor="white", linewidth=.6, zorder=6)
        training_stop = fit["training_stop_elapsed_wall_seconds"]
        axes[1].plot([training_stop, training_stop], [0, fit["new_completed_updates"]], color=color,
                     linestyle=(0, (1, 3)), linewidth=.85, alpha=.65, zorder=2)
        stop_label = "Plateau stop" if fit["status"] == "COMPLETED_PLATEAU" else fit["status"].replace("_", " ").title()
        text = (f"Seed {fit['seed']}: {fit['new_completed_updates']} updates\n{stop_label}; last full epoch {fit['last_complete_epoch']}\n"
                f"Anchor e{fit['plateau_anchor_epoch']} / {fit['stopping']['plateau_anchor']:.6f}; stale {fit['stopping']['stale_epochs']}\n"
                f"Train stop {training_stop:,.1f} s · exit {stop:,.1f} s")
        if fit["open_optimizer_completion_interval"] != [0, 0]:
            text += f"\nIn-flight completion unknown: {fit['open_optimizer_completion_interval']}"
        axes[1].annotate(text, xy=(stop, fit["new_completed_updates"]),
                         xytext=(-20, 29) if index == 0 else (.025, .64),
                         textcoords="offset points" if index == 0 else "axes fraction", ha="right" if index == 0 else "left", va="center",
                         fontsize=9.1, color=color, bbox=dict(boxstyle="round,pad=.4", fc="white", ec="#d8e1e7"),
                         arrowprops=dict(arrowstyle="-", color=color, lw=.8), zorder=8)
        late = [row for row in updates if not row["within_scientific_budget"]]
        if late:
            axes[1].scatter([row["elapsed_wall_seconds"] for row in late], [row["new_completed_updates"] for row in late],
                            marker="x", s=30, color="#c45646", linewidths=1.2, zorder=9)
    handles, labels = axes[0].get_legend_handles_labels()
    handles += [Line2D([0], [0], color="#718492", linestyle="--", linewidth=1.2),
                Line2D([0], [0], marker="*", color="#718492", linestyle="None", markersize=10)]
    labels += ["Inherited best (reference)", "Final checkpoint selection"]
    figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(.068, .875), ncol=4,
                  frameon=False, fontsize=10.3, handlelength=2.2, columnspacing=2.2, labelspacing=.7)
    footer = [f"D is the development set used for checkpoint selection, not a held-out test. These are two seeds of the same frozen-physics QPR model.",
              f"All {sum(len(fit['epochs']) for fit in data['fits'])} new complete epochs and {sum(fit['new_completed_updates'] for fit in data['fits'])} actual optimizer completions are shown. No smoothing, omitted points, or extrapolation.",
              f"Dotted gray line: training-reserve boundary at {reserve:,.0f} s. Dashed gray line: {budget:,.0f} s total scientific budget; shaded region is reserved for finalization.",
              "Stars mark selection at the final result timestamp, not a new training epoch. Diamonds mark actual process exits; colored dotted lines mark training stops.",
              "Counts include replayed original partial work and any final partial epoch; no work is refunded. Timings include setup, imports and development evaluation.",
              "New partial-epoch checkpoints were saved and structurally audited, not resumed in another training run. Four cold probes used original complete epochs.",
              "New continuation identities only. Original controller: UNKNOWN · full six-fit training replay: 0/6 · scientific admission: HOLD."]
    for index, text in enumerate(footer):
        figure.text(.075, .205 - index * .027, text, ha="left", fontsize=8.8, color="#536474")
    output.mkdir(parents=True, exist_ok=True)
    prefix = output / "c2-continuation-progress"
    for suffix in (".png", ".svg"):
        destination = prefix.with_suffix(suffix)
        metadata = {"Creator": "Hepta C2 continuation evidence", "Date": None} if suffix == ".svg" else None
        figure.savefig(destination, dpi=200, facecolor="white", metadata=metadata)
        if suffix == ".svg":
            destination.write_text("\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n")
    plt.close(figure)
    path = output / "c2-continuation-progress-data.json"
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"complete_epochs": sum(len(fit["epochs"]) for fit in data["fits"]),
                      "optimizer_completions": sum(fit["new_completed_updates"] for fit in data["fits"]),
                      "png": str(prefix.with_suffix('.png')), "svg": str(prefix.with_suffix('.svg')), "data": str(path),
                      "model_calls": 0, "optimizer_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    draw(collect(args.archive, args.receipt, args.audit), args.output)
