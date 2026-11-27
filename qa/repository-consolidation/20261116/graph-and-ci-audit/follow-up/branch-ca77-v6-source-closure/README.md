# ca77 v6 current source and original test closure

The proposed addition contains 35 original files from ca77c88d01b5dc800bdba7cfdc673c7d8d89101a: 15 runtime or inspection modules, 12 original test modules, four documents, three protocol or calibration JSON files, and one ignore file. Every incoming blob is preserved exactly. The 13 previously reviewed source paths at eb2e8028664b6db79ee1885f0d5b6ec115376021 remain unchanged.

## Current validation

The 12 additional original test modules ran 75 tests successfully with no skips. The source identity read 421 actual files. All 427 materialized source and control files were unchanged after execution, and the isolated validation Git worktree remained clean. The context used the complete 379-file native input set selected by run.source_identity from the root native owner test snapshot. Every byte was checked against that earlier frozen manifest. The validation tree has 20 native context changes relative to eb2; those are root-owned source inputs and are not included in this 35-file proposal.

The earlier 24 original Python tests, three namespace regressions and five actual native owner tests were reused by their existing receipts. They were not executed again. The static scan had counted the production function paired_fixture.test_source_ids as a test merely because its name starts with test. The correct combined Python count is 99 original tests plus three namespace regressions, or 102. No test definition was changed or silently omitted.

The original 512000-byte blob policy passed all 35 proposed files. Codespell passed with the existing configuration and dictionary, with no additional ignores. The largest new source blob is 31620 bytes and the complete source addition is 395080 bytes. The new paths are outside the existing Python formatter selector and root Prettier command; this report does not claim a whole-repository formatter pass.

## Runtime and consumer review

- control.py retains exact finite-tree work accounting, execution reserves, stopping and independent Decimal oracle checks.
- forecast.py, distribution.py and distribution_fit.py retain separate source groups for fitting, calibration and validation. Their standardization belongs to the offline forecast model; it does not introduce another normalization path into the six-source owner worker.
- joint_contract.py binds the actual text and image outputs and keeps the four modality slots explicit. Unsupported audio and video requirements fail before preparation or training.
- reporting.py preserves the complete arm and case census, distinct observer requirements, file pins, exact output bytes, source group counts, adverse outcomes and conservative unknown risk.
- run.py retains source and protocol identity before execution, single-use output directories, failed preparation records and heldout source exclusion. Its smoke mode still performs actual data preparation and fitting, so it was not run here.
- completed_owner_fixture.py, paired_fixture.py and terminal_fixture.py consume explicit completed-run or artifact inputs. Their custody tests reject foreign, incomplete or changed original records. The paired source helper is production code, not an additional regression.
- replay.py checks original source and output custody and limits replay comparison exclusions to physical timing. No scientific replay was executed here.
- validate_oracle.py checks a clean exact Git commit and raw source bytes before and after 128 finite cases, and publishes a report without overwriting an existing destination.
- plasticity_rejection_fixture.py preserves explicit rejection evidence and does not manufacture authority or eligibility.

The current modules import only this v6 source set and their pinned Python dependencies, plus the Git executable used for source identity. The 75 additional tests use their original bounded synthetic fixtures, including numerical fitting. No MNIST download, scientific smoke/full study, trained checkpoint download, historical calibration run or Cargo build was executed.

## Historical calibration boundary

neuron_calibration.py, verify_neuron_calibration.py and neuron_calibration_spec.json are unchanged original files. The historical owner source digest remains 9bf09b8f4358f7067548f813ba34100605bc0e0e481d066777befa21093f103a and the historical source commit remains b98961ceb71414490e1c6ae397cf635bca3093f4. The recorded adverse calibration and out-of-distribution results remain adverse.

The current guarded worker has a different source identity. A historical source-pinned model run therefore requires an independently restored exact original source tree and original inputs. It cannot be relabeled as a current-source result. The unchanged offline verifier can inspect original recorded states and outputs without executing the current worker. That complete historical asset closure is still under review; these 35 source files alone do not claim the old completed-run assets are available or currently qualified.

## Workflow and branch scope

No workflow is added by this proposal. In particular, the incoming blocking workflow calls ndu-v6 for related pull requests and main pushes, which would execute real smoke training. The current blocking gates must be retained when that workflow is reviewed. The incoming joint-hepta-v2 preservation job also contains a write to a research branch; that behavior requires an explicit reviewed resolution before the family merge.

This is a source addition with zero newly retained original branch heads. The complete ca77 family and its historical resources remain open for ordinary parent-preserving merge review. No remote reference or repository branch was changed by this validation.
