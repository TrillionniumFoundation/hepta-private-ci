use super::PluginMeasurementDefinition;
use super::PluginMetricsOperation;
use super::load_plugin_metrics_operations;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;

#[test]
fn yaml_analytics_keeps_string_coercions_and_resolves_real_scripts()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = AbsolutePathBuf::try_from(directory.path().canonicalize()?)?;
    fs::write(root.join("null"), "script")?;
    fs::write(
        root.join("analytics.yaml"),
        "version: 1\noperations:\n  build:\n    path: null\n    measurements:\n      latency:\n        dimensions:\n          result: [ok, error, null, true, false]\n",
    )?;
    assert_eq!(
        load_plugin_metrics_operations(&root),
        Some(BTreeMap::from([(
            "null".to_string(),
            PluginMetricsOperation {
                operation_name: "build".to_string(),
                measurements: BTreeMap::from([(
                    "latency".to_string(),
                    PluginMeasurementDefinition {
                        enum_dimensions: BTreeMap::from([(
                            "result".to_string(),
                            BTreeSet::from(
                                ["ok", "error", "null", "true", "false"].map(str::to_string)
                            ),
                        )]),
                    },
                )]),
            },
        )]))
    );
    Ok(())
}

#[test]
fn yaml_analytics_keeps_duplicate_and_schema_rejections() -> Result<(), Box<dyn std::error::Error>>
{
    let directory = tempfile::tempdir()?;
    let root = AbsolutePathBuf::try_from(directory.path().canonicalize()?)?;
    fs::write(root.join("build"), "script")?;
    for input in [
        "version: 1\noperations:\n  build: {path: build, measurements: {latency: {}}}\n  build: {path: build, measurements: {latency: {}}}\n",
        "version: 1\noperations:\n  build:\n    path: build\n    measurements:\n      latency: {}\n      latency: {}\n",
        "version: 1\noperations:\n  build:\n    path: build\n    measurements:\n      latency:\n        dimensions:\n          result: [ok]\n          result: [error]\n",
        "version: 1\nunknown: value\noperations: {}\n",
        "version: true\noperations: {}\n",
        "version: 1\noperations: [build]\n",
    ] {
        fs::write(root.join("analytics.yaml"), input)?;
        assert_eq!(load_plugin_metrics_operations(&root), None);
    }
    Ok(())
}
