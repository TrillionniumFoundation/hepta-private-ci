# Restore the study002 figures

From the repository root, run this command to open any original SVG or PNG
named by either figure manifest at its recorded path.

```sh
study=experiments/continuous_spiking_followup/results/study002
python3 "$study/analysis/restore_audit_archives.py" \
  --study-root "$study" --manifest "$study/analysis/audit_archives/MANIFEST_002.json"
```

The second archive manifest includes all sixteen paths in the first manifest
and ten additional SVGs. The existing reader checks every original SHA-256
and creates missing files. Use `--verify-only` to check the archive without
writing outputs. A second restore skips files with identical bytes.

The report's two embedded SVGs and its PNG are directly viewable after
checkout. The restored figure paths support vector display and verification
against `analysis/figures/FIGURE_MANIFEST.json` and
`analysis/figures_v2/FIGURE_MANIFEST.json`.

## Original report figures

The two embedded SVGs remain at their existing Markdown link targets as
checkout previews. `MANIFEST_003.json` records the exact original bytes,
separately from the previews, at both recorded `figures_v2` paths.
To restore the signed originals without overwriting the checkout previews:

```sh
study=experiments/continuous_spiking_followup/results/study002
archive="$study/analysis/audit_archives"
output=$(mktemp -d)
mkdir -p "$output/analysis/audit_archives"
cp "$archive/MANIFEST_003.json" "$output/analysis/audit_archives/"
cp "$archive/08872353f5fb5f5e172ec4d461f64f0741cf84d966567e5e6fdaefba4914cfef.gz" \
   "$archive/5767b633d5be059d75e144abb71483d419bdb7eeaa7710392f1abe19b8aa9814.gz" \
   "$output/analysis/audit_archives/"
python3 "$study/analysis/restore_audit_archives.py" \
  --study-root "$output" --manifest "$output/analysis/audit_archives/MANIFEST_003.json"
```

The original figure SHA-256 values in `analysis/figures_v2/FIGURE_MANIFEST.json`
and `analysis/STABLE_TRAINING_ANALYSIS_FILES.json` apply to the restored files,
not to the checkout previews. The report and the prior figure archive remain
unchanged.
