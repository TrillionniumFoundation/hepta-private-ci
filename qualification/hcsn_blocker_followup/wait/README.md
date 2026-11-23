# Waiting for native sensor evidence

A waist-mounted smartphone recorded acceleration and angular velocity at 50 Hz. Given the annotated start of a postural transition and the person's starting posture, the task predicts which of the two other postures the person will reach. The first decision sees the preceding 24 acceleration samples ending at onset. Each subsequent decision adds 24 newly acquired samples. The six decisions cover onset through 2.40 seconds. All 30 people have independent split assignments, and each person's recordings stay together. The benchmark supplies the annotated onset and starting posture. Continuous operation would require an additional onset and posture detector. [Original UCI HAPT dataset and authors, DOI 10.24432/C54G7M](https://doi.org/10.24432/C54G7M)

WAIT costs 0.40 per real second with continuous discount 0.20/s. A terminal READ buys the synchronized gyroscope in addition to the free accelerometer for 0.30 task utility. Both sensors were recorded physically. The price defines this benchmark's utility. It does not measure hardware cost. Labels, descriptors, subject splits, conditional controls and pass criteria appear in [protocol.json](protocol.json).

| Held-out measure | Result |
|---|---:|
| Participants / transitions | 10 / 120 |
| Immediate free utility and accuracy | 0.691667 / 0.691667 |
| Locked confidence policy utility and accuracy | 0.682899 / 0.716667 |
| Mean paired utility gain | −0.008767 |
| Subjects with positive gain / ties | 4 / 1 |
| Conservative one-sided paired source sign P | 0.828125 |
| Episodes with a WAIT | 14 |
| Free clairvoyant WAIT opportunity | +0.135590 |
| Joint clairvoyant WAIT vs best immediate | +0.101903 |
| Joint paid acquisition opportunity vs best free-only future | +0.012980 |

TRAIN contained 166 events from 14 participants, and DEV contained 72 from six participants. All 358 annotated target transitions had sufficient continuous sensor coverage. DEV selected a confidence cutoff of 0.55 and a cap of two additional 0.48 s intervals. The strongest unconditional free exit on DEV was the immediate exit. On TEST the extra observations raised accuracy by three correct decisions in 120 but lowered priced utility. Knowing the outcomes retrospectively reveals positive free waiting opportunity in 31 events. The declared single primary confidence policy missed its utility threshold and sign criterion. The script fixes the workload and all models before opening the 10 test subjects.

At matched seeds the fixed and internal regenerative-QVI encoders produced identical held-out actions. In the full paid task they waited in one or two episodes and purchased once, attaining utility 0.677019–0.678545. Their independently fitted noREAD counterparts waited in three episodes and attained 0.685564. Exact per-episode scores are in the archive. This is a native-clock, non-audiovisual conditional benchmark. It does not establish behavior on unseen onset definitions, unscripted activity, or other populations. The full conditional OOF stopping teacher operates on frozen source-held-out frontend scores. Frontend and teacher use separate group fits; the entire feature pipeline was not recursively refit for nested teacher folds.

## Reproduction

The public source archive has SHA256 `4ac4ae064227c07045a99551876b54d204837e995e298b6488559e209b3deb09`. The roster commit is `331e2baa8093e68743e3c7a5fb9176984ac32465`. The externally recorded fit seal is `b0279ec0aee767cc89e6a377145b5fd267047b7a` on `research/hcsn-native-wait-hapt-0214`. Its file SHA256 is `ed56be462cbe730e6d6272033c123df51738bfb53220ae380f49b6e7038fc957`. The two 276,260-byte parts have SHA256 digests listed in [archive_parts.json](evidence/archive_parts.json). Concatenation restores the original 552,520-byte ZIP without changing any scientific file. The evidence archive contains the model weights, small derived splits, per-episode decisions, verifier result and exact original seal.

Run the independent verifier against the extracted archive from the repository root with the study's FP64 PyTorch, NumPy and one CPU thread. The 358 raw events rebuild all sensor scores to within 8.0e−15. Fourteen refitted linear heads agree within 2.3e−13. Verifier output includes the shared physical feature kernel and independent numerical stages. `verify.py` creates a fresh `verification.json`; remove the copy from the extracted evidence directory before running or run in a separate directory.

```bash
curl -L 'https://archive.ics.uci.edu/static/public/341/smartphone+based+recognition+of+human+activities+and+postural+transitions.zip' -o hapt.zip
cat qualification/hcsn_blocker_followup/wait/evidence/native_wait.zip.part01 qualification/hcsn_blocker_followup/wait/evidence/native_wait.zip.part02 > native_wait.zip
printf '%s  %s\n' '0026aa2b2d7cc4c3e7960009d553e3a2ebd1ce07925c79d980eb0b813f14d29e' native_wait.zip | sha256sum -c -
mkdir hapt-recheck
unzip native_wait.zip -d hapt-recheck -x verification.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m qualification.hcsn_blocker_followup.wait.verify hapt.zip hapt-recheck
```

To run a fresh experiment, copy `evidence/roster.json` to a new output directory, call `study fit hapt.zip NEW`, then `study confirm hapt.zip NEW --expected-seal <SHA256 of NEW/fit_seal.json>` after independently recording the new seal. Wall-clock fields change when a fit is repeated. Reported times (6.27 s fit including development and 2.50 s confirm, plus 13.94 s independent replay) are in-process times. The 79.6 MB source transfer and interpreter startup are separate resources.
