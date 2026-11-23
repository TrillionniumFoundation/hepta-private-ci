# Teacher-off readout on the balanced binary panel

Both elicitation procedures completed on the pinned teacher and student pipeline. A fresh sealed Python process reloaded the same frozen owned vocabulary, weights and routing table for every arm of each procedure. Each process reported loopback only, with zero bytes. All 12 old control questions were retained by every arm. This is one generated English evaluation with zero human users.

| Arm | Letter correct / 120 | Letter both correct / 24 | Native yes/no correct / 120 | Native yes/no both correct / 24 |
| --- | ---: | ---: | ---: | ---: |
| parent | 58 | 11 | 58 | 11 |
| t5 | 60 | 12 | 62 | 12 |
| smol | 60 | 5 | 61 | 6 |
| best_single | 60 | 12 | 61 | 6 |
| mix | 60 | 9 | 60 | 9 |
| fixed | 60 | 12 | 63 | 11 |
| sparse | 73 | 7 | 64 | 7 |

Under the primary letter readout, neither teacher achieved the discovery threshold in any domain. Each teacher was the exclusive correct teacher on 10/20 held-out questions in each domain. The sparse selector used truth labels for 72 discovery cases and may itself have learned a task discriminator. Its 73/120 exceeds the best preselected single student's 60/120, while exact pairs declined from 12/24 to 7/24. These results supply no verified teacher-domain advantage that could explain the increase.

Under the secondary native yes/no readout, Smol won review discovery 9/12 against T5's 7/12, with four Smol-only successes and two T5-only successes. Under the held-out review template, T5 scored 20/20 and Smol 10/20. The discovered direction reversed. The learned selector achieved 64/120, with the weakest family 9/20 and 7/24 pairs. The fixed graph achieved 63/120, weakest family 10/20 and 11/24 pairs. T5 alone had 12/24 exact pairs. The sentence forms and small samples constrain interpretation.

The companion evidence JSON files give all domain counts, conditional inheritance on each teacher's exclusive successes, pairs and costs. Each ZIP contains the individual teacher margins, individual cold predictions with expert choice, portable student checkpoint, freeze receipt and upstream provenance. The aggregate inference wall times on the runner exclude weight loading and orchestration. For letters, the two teachers together spent 57.46 s on discovery plus fit and 37.02 s on confirmation. For native yes/no, they spent 22.33 s and 14.08 s. Fitting all students together took 0.062 s and 0.058 s, respectively. These are CPU measurements of a 1,501-feature linear classifier and cannot be converted into a foundation-model speedup. The fixed and sparse graphs store two experts. The paired metric scores both independent constituent answers correct. There were no participants, production integrations or skill adoption events.

The first hosted attempt exposed a failure when Python lazily loaded its standard ZIP codec after the file boundary had closed. The successful run preloaded that codec before installing the original restriction. The selection, teacher and scoring logic stayed fixed. The complete successful jobs and their receipt timestamps are available in the [run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45171015838).

| Artifact | SHA-256 |
| --- | --- |
| `letter-run.zip` | `ba9a8f4482d81126eda860a7401f23ccea718ac85313502b44707bc14f135b7d` |
| `native-run.zip` | `0a0b8446718e36aa03b9ef7617d80574f52fbd58ba200bcf86a4af5ce925dfb7` |
