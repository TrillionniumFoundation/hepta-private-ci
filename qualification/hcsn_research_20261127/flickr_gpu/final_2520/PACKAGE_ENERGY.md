# Package energy observed during the original Flickr8k run

The 7,110 samples of Linux amdgpu PPT represent the shared CPU and integrated GPU package. The process timestamps identify which training window was running. Other processes can contribute to the same sensor. There are no process-isolated GPU joules, idle baseline, facility power or device energy for the first quality crossings.

The verifier reconciled all 150 original driver intervals against the checkpoint step counts. It integrates pairs of actual watts readings inside the same interval using the trapezoidal rule. The sampling period had a median of 5.0010 seconds and a maximum of 5.0446. All 119 source-side sampled window totals reproduce to the stated precision.

The fit windows totalled 37,809.62 seconds. Pairs wholly inside individual windows covered 34,843.30 seconds (92.15%) and 2,944,206.37 joules (0.81784 kWh), averaging 84.498 watts. Sampling began partway into the 420-second stage. Another 590.14 measured seconds (49,877.65 joules) straddled different training windows. After the final fit, 115.03 measured seconds contributed 9,717.38 package joules during the remaining evaluation and completion period.

## Common late stages

All 15 runs contributed seven 300-second increments per model and seed ending at the 720- through 2,520-second checkpoints, for 21 incremental windows per arm. Their totals still depend on coverage. The averaged package readings are descriptive.

| Visual router | Windows | Valid coverage | Covered seconds | Package kJ | Mean package watts |
|---|---:|---:|---:|---:|---:|
| dense | 21 | 98.35% | 6,196.43 | 523.467 | 84.479 |
| hcsn | 21 | 98.36% | 6,196.41 | 523.673 | 84.512 |
| lif | 21 | 98.35% | 6,196.39 | 523.651 | 84.509 |
| mean | 21 | 98.27% | 6,191.41 | 523.050 | 84.480 |
| smooth | 21 | 98.36% | 6,196.44 | 523.555 | 84.493 |

All measured common-stage means fall between 84.479 and 84.512 watts. The frozen quality milestones that any arm reached were reached by all arms at the 20- or 120-second scheduled observations, before power sampling began. These observations cannot estimate energy at a common achieved quality. The unequal full-run arm totals also contain different amounts of missing data.

To reproduce the table, reconstruct flickr42_original.zip according to archive_parts.json and run `python verify_package_energy.py flickr42_original.zip flickr42_sidecars.zip package_energy.json`. The JSON contains all 150 windows, the shared-device scope and the original archive hashes.
