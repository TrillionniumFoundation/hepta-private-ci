//! Synthetic Python-contract vectors. These bind wire bytes only, not a worker,
//! canonical model, authenticated Memory/Ledger owner, or actual training run.
//! Request vector SHA256: 30f9c2ff802e5af50cebe47f70d282e181e9ea8b28eb62f16cc769254c4cdcc2.

pub(super) const REQUEST: &str = r###"{"schema":"hepta.joint-text-worker.request.v1","profile":"joint-v4-verified-memory-text-sgd-v1","principal_id":"fixture-principal_id","agent_id":"fixture-agent_id","cell_id":"fixture-cell_id","operation_id":"fixture-operation_id","source_run_id":"fixture-source_run_id","completed_task_receipt":"119ef4c8f8b8c2edf3c403ac7acb8ad02f7bc2b0af7991594981217d6d9f2b28","iteration_head":"0fd088639c0af03b881d00063490ecac130461e1857871adb2fe49946983b13f","selected_bundle_digest":"abb5904130ed54d7f5cdd8302e207e27b5af4c95f32fb6154129a86375446878","selected_generation":2,"candidate_artifact_id":"fixture-candidate_artifact_id","evaluation_profile":"d6c97a647d8143f0bd204c95b4a099278ef8d01d981182dd860888f196b78f85","dataset_digest":"f1e93ff249b9ae0b46c31b5d161159b259123f74a6f18c6b5c7bc618dc4b8af4","dataset_observed_rows":7,"dataset_observed_bytes":1000,"source_record_count":3,"materialization_digest":"bc4c927cadba806f1eecc94f770470f69653205236d168657da6d2997c2d477e","materialization_profile_digest":"a07ee3043fb5c37fd4100579bd66e3831796689694dfa9d451e9598555ec8f55","source_support_digest":"920fc4d8ee6962ae67f68996adb641162b1ec41d86bc494eb2c741ad41d9e770","source_content_sha256":"f323e3d7c89505a5ca442b528b0f25e830161cbe6b0875bd7b9822f83e131bc1","source_revision":1,"source_policy_revision":5,"predecessor_sha256":"7f7fd8c1827e7045122b4817a747904be9e5fa1174ddc938c07de18f48f1e0bc","predecessor_bytes":1024,"execution_source_digest":"9452aafecc4665fc54fdb1d0d928c845733c85450edbd0d0c8fbbdb6eff3567e","prefix":"Ab世界","continuation":"🙂","steps":2,"learning_rate_f64_be":"3f847ae147ae147b","maximum_dataset_rows":10,"maximum_dataset_bytes":4608,"maximum_training_steps":4,"maximum_training_milliseconds":5000,"maximum_artifact_bytes":8388608}
"###;

pub(super) const OBSERVATION: &str = r###"{
  "schema": "hepta.joint-text-worker.observation.v1",
  "profile": "joint-v4-verified-memory-text-sgd-v1",
  "status": "candidate",
  "authority": "DENY_ALL",
  "request_sha256": "40fe15c328d94e42ed9cd311186eaffd7459664eb2c45534664b3956e288d28f",
  "request_binding_digest": "1213009c466ab739421cfb92b00becca2f0cd5ad3c6ee05123427643ae87a3d5",
  "training_profile_digest": "3f62d0827e9b16daf024d2454a3f94c2062588e41b9a2d5694e5bb6167823a1a",
  "update_rule_digest": "a1f05129c85d07b7f7d7ef2eb47b6326c284875c5731345c0e4583035bf17a51",
  "execution_source_digest": "682cde570d892a91cd3ba2a792a354d60a00adb0dfb9bc9e0a49782a1ef3f19e",
  "execution_sources": [
    {
      "path": "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
      "bytes": 74,
      "sha256": "c6ea10b2f754bea185a33f85400414a0a9290140bde995346cc67657ac753734"
    },
    {
      "path": "scripts/joint_generation_v4_io.py",
      "bytes": 33,
      "sha256": "caa2a3d169ed55ee5689dfa0a669fa7e6615212d06e92a7e20d01af53b581a18"
    },
    {
      "path": "scripts/joint_generation_v4_model.py",
      "bytes": 36,
      "sha256": "0ff78a31d35afa169f3fc6ba8a18e81adf30378ab824c8649fc09115e6a371ee"
    },
    {
      "path": "scripts/joint_generation_v4_text_worker.py",
      "bytes": 42,
      "sha256": "3ae6f707a642c17456498f344ee42083bdbe64b4911459ef77af42dc89714193"
    },
    {
      "path": "scripts/joint_text_training_compute.py",
      "bytes": 38,
      "sha256": "952fd75603467ca60f58ad455b585eaad549b0d5b165da2fafaf1ccc5a779f33"
    },
    {
      "path": "scripts/joint_text_training_contract.py",
      "bytes": 39,
      "sha256": "4f75cc71a52b4f191b4e8fb90686387460076b80ae5970058272e0b7eeb83df1"
    },
    {
      "path": "scripts/joint_text_training_io.py",
      "bytes": 33,
      "sha256": "3adbc0333a83c6d525b8e8e4f16a32072a0521132355d97763c37c1b21049be4"
    }
  ],
  "absent_source_paths": [
    "experiments/__init__.py",
    "experiments/multimodal_output_portfolio/__init__.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/__init__.py",
    "scripts/__init__.py"
  ],
  "predecessor": {
    "sha256": "7f7fd8c1827e7045122b4817a747904be9e5fa1174ddc938c07de18f48f1e0bc",
    "bytes": 1024,
    "after_sha256": "7f7fd8c1827e7045122b4817a747904be9e5fa1174ddc938c07de18f48f1e0bc",
    "roundtrip": true
  },
  "candidate": {
    "sha256": "2d110a744d32a95616e7d5dba09b2aa324e9b989ef50d4b6dea1f090f1023c05",
    "bytes": 51,
    "roundtrip": true,
    "changed": true
  },
  "training": {
    "requested_steps": 2,
    "completed_steps": 2,
    "source_samples": 1,
    "source_record_count": 3,
    "dataset_observed_rows": 7,
    "dataset_observed_bytes": 1000,
    "prefix_bytes": 8,
    "continuation_bytes": 4,
    "continuation_scalars": 1,
    "losses_f64_be": [
      "4000000000000000",
      "4004000000000000",
      "4008000000000000"
    ],
    "parameter_groups": [
      {
        "group": "core",
        "parameters": 10,
        "gradient_present_parameters": 1,
        "gradient_nonzero_parameters": 1,
        "changed_parameters": 1,
        "max_abs_gradient_f64_be": "3ff0000000000000",
        "max_abs_delta_f64_be": "3fb999999999999a"
      },
      {
        "group": "encoder",
        "parameters": 10,
        "gradient_present_parameters": 1,
        "gradient_nonzero_parameters": 1,
        "changed_parameters": 1,
        "max_abs_gradient_f64_be": "3ff0000000000000",
        "max_abs_delta_f64_be": "3fb999999999999a"
      },
      {
        "group": "transition_and_adapters",
        "parameters": 10,
        "gradient_present_parameters": 1,
        "gradient_nonzero_parameters": 1,
        "changed_parameters": 1,
        "max_abs_gradient_f64_be": "3ff0000000000000",
        "max_abs_delta_f64_be": "3fb999999999999a"
      },
      {
        "group": "text_head",
        "parameters": 10,
        "gradient_present_parameters": 1,
        "gradient_nonzero_parameters": 1,
        "changed_parameters": 1,
        "max_abs_gradient_f64_be": "3ff0000000000000",
        "max_abs_delta_f64_be": "3fb999999999999a"
      },
      {
        "group": "other_heads",
        "parameters": 10,
        "gradient_present_parameters": 1,
        "gradient_nonzero_parameters": 1,
        "changed_parameters": 1,
        "max_abs_gradient_f64_be": "3ff0000000000000",
        "max_abs_delta_f64_be": "3fb999999999999a"
      }
    ],
    "core_gradient_nonzero": true,
    "core_changed_parameters": 1,
    "effective_wall_limit_milliseconds": 5000
  },
  "runtime": {
    "python_version": "synthetic",
    "torch_version": "synthetic",
    "platform": "synthetic",
    "device": "cpu",
    "dtype": "float64",
    "threads": 1
  },
  "cost": {
    "wall_nanoseconds": 1,
    "cpu_nanoseconds": 0,
    "scope": "worker request/checkpoint validation through candidate fsync and reload; excludes observation/marker fsync, host admission/queue/transfer/publication",
    "physical_energy_joules": null,
    "full_history_cost": null
  },
  "claims": {
    "content_loss_training": true,
    "ndu_training": false,
    "evaluation": false,
    "product_loading": false,
    "selection": false,
    "stage_advanced": false
  },
  "input_files_unchanged": true,
  "source_files_unchanged": true
}
"###;

pub(super) const CANDIDATE: &[u8] = b"unsigned-synthetic-candidate; not a canonical model";
pub(super) const SOURCES_DIGEST: &str =
    "682cde570d892a91cd3ba2a792a354d60a00adb0dfb9bc9e0a49782a1ef3f19e";
