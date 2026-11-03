use crate::safe_yaml::Value as YamlValue;
pub(crate) fn parse_command_description(raw_frontmatter: &str) -> Option<String> {
    let parsed: YamlValue = crate::safe_yaml::from_str(raw_frontmatter).ok()?;
    let mapping = parsed.as_mapping()?;
    mapping.iter().find_map(|(key, value)| {
        if key.as_str()?.trim() == "description" {
            yaml_scalar(value)
        } else {
            None
        }
    })
}

fn yaml_scalar(value: &YamlValue) -> Option<String> {
    match value {
        YamlValue::String(value) => Some(value.trim().to_string()),
        YamlValue::Bool(value) => Some(value.to_string()),
        YamlValue::Number(value) => Some(value.to_string()),
        YamlValue::Null | YamlValue::Sequence(_) | YamlValue::Mapping(_) | YamlValue::Tagged(_) => {
            None
        }
    }
}
