# Training a new owned candidate from one enrolled repair

The training transport accepts two complete source records from one task. It verifies the failure, the subsequent correction, the two original submitted artifacts, their execution receipts and both semantic outcomes. The trusted Linux host first asks the original Agentd text owner to verify the user's exact training grant. The grant binds the SHA-256 of each complete record. The training entry reads the private record bodies after that check.

The first supported live source is a local agent performing a create-only JSON artifact write. The artifact is read back from the actual destination and independently scored by the existing `json_artifact/1` verifier. Existing files are preserved. The original same-inode write can resume after interruption. External tool adapters that produce different kinds of outcomes need an appropriate execution receipt and verifier.

## An observed rejection

The development case started from the published owned parent in #7022. A new artificial task requested JSON integer one. The real parent generated `0` and the development correction agent submitted `1`. The sink placed and read back both artifacts. Both records explicitly identify researcher-created inputs. The fixture calls the private training implementation directly. Its owner record identifies zero participating humans.

The fixed CPU plan performed 64 AdamW steps on 2,816 LoRA coordinates. Supervision was limited to the corrected terminal answer and EOS. The earlier failed action was visible in the training context with all its labels masked. On cold generation for the original task, the parent produced `0`. The fitted child repeated `1` until the 100-token limit. The parent passed the old zero task. The child repeated `1` there as well. The two pre-adoption arms then reloaded the same tensors in separate processes and reproduced both scores. The retention gate recorded `no_update_retention_regressed`. This job consumed zero future records and received zero payment.

The saved development pair is identified by candidate `a44f85e1484f904e1fbd5c4e6c0d5804e636073f33ade25a158ee4f94c8e0336` and canonical freeze `be8611542db942bfce78f8d5ce042e6d0574f70694ebb4e95683c7f3a84d9f16`. The independent public-historical candidate from #7022 retains its own prospective freeze. Changing the synthetic source's record and task IDs was rejected by the separate SQLite intake before a model call or order.

## Source and host commands

The original agent gateway archives the submitted provider event under `MATERIALS/originals/<sha256>`, including the exact bytes named in its source record. It supplies an ordinary v1 training draft with the final submitted action still unexecuted. The trusted host selects each destination. Repeating the command for the same attempt recovers its original artifact. The CLI prints the canonical record digest for the user's original protected UI.

```sh
export PYTHONPATH="$PWD/scripts" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python -m cell_experiments.paired_source failure-draft.json failure.artifact MATERIALS/originals MATERIALS/failure.json
python -m cell_experiments.paired_source correction-draft.json correction.artifact MATERIALS/originals MATERIALS/correction.json
```

The source plan binds the study, consent delivery, exact failure and correction, parent, evaluation-only retention panel, executable training source, objective, adapter modules, learning rate, sequence budget and maximum physical update attempts. A concrete `SPEC.json` is in the archive. The trusted launcher pins both that plan and the independently built #7019 ELF. It supplies the existing original Root stream and held pidfd on fds 3 and 4. Under the Linux host's private account, use one command for native authorization, training, freeze and cold retention scoring.

```sh
python -m cell_experiments.paired_source_gate train MATERIALS SPEC.json SPEC_SHA CONSENT_ELF ELF_SHA ROOT_PID SQLITE_HOME ROUTE.json
```

The private operation directory is `MATERIALS/paired-training/<canonical digest of [study,failure,correction]>`. It holds the owner readback, plan, source completion, frozen pair and retention disposition. New A candidates carry their prior registered source catalogs and hashes of known prompts, sources and actual model input IDs. The ordinary two-stage future CLI uses those commitments. The source enrollment authority remains responsible for original consent, chronology, independent people and source provenance. The fixed retention rule preserves each item previously passed by the parent. Its passing disposition opens prospective evaluation, which still needs a new, authorized incoming task.

For a new source-trained candidate, the enrollment site records the canonical SHA-256 of the pre-arrival `RETENTION.json` as `source_retention_sha256` in its independently held freeze observation. The ordinary `paired_intake install --scope owner_intake` checks the candidate, frozen parent and every previously passed panel item before creating its intake journal. If the report lives separately, pass `--source-retention` with its location. The same check covers older intake installations when admitting a task. The registration command reopens the original completion, training consent and both cold outputs, and reproduces the old-item scores before committing the digest. Both the ordinary freeze observer and the installer rejected this archived candidate without creating either a freeze observation or an intake journal. Their command outcomes are recorded in `DISPATCH_DENIAL.json`. A released eligible request carries the same digest into the funded admission. Use the enrollment site's own sequence in this command.

```sh
python -m cell_experiments.paired_observation INBOX STUDY_SHA FREEZE_SHA SEQUENCE freeze --source-retention OPERATION/RETENTION.json
```

The trainer supports fresh base weights with the declared LoRA modules and a matching pre-existing adapter. Each physical update slot is committed before compute. SQLite saves the edited coordinates, AdamW state, CPU RNG and per-step measurement atomically. A committed update is restored. An interrupted reservation consumes one of the bounded retry slots. The original frozen weights and completed case can be reopened without fitting again.

## Reproduction

For this artificial case use the original #7022 parent directory, PyTorch 2.9.1 CPU, Transformers 4.57.3 and PEFT 0.18.0. The run used a Linux network namespace with external networking disabled. Set `new_output` to a fresh private directory. For a retained run, the standalone scoring command can recheck the existing evidence.

```sh
case_dir=qualification/public-historical-a-qwen2-052-20261123/run
study_dir=qualification/paired-source-training-20261123
python "$study_dir/qualify.py" "$case_dir" "$new_output"
python -m cell_experiments.paired_source_gate score "$new_output" "$new_output"/paired-training/*
python -m unittest cell_experiments.test_paired_source cell_experiments.test_paired_source_resume
```

`SUMMARY.json` holds the generator outputs, `RETENTION.json` the cold rejection, and `RENAMED_SOURCE.json` the independent intake refusal. `engineering-run.zip` contains the original development records, actual weights, SQLite optimizer state, tokenizer, cold outputs and decision. `RESTART_TESTS.txt` records the two independent hard-exit controls. The local observer's stable per-write inode is a live filesystem property. An extracted archive is suitable for verification and scoring.

The archive has 39 files and SHA-256 `0887cb6cc793eab7e3db62866f29e2d785778863f2857936434fd91c9c7b10a6`.
