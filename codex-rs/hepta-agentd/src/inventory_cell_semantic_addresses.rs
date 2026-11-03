//! Versioned, bounded name and capability matching. This is a declared query
//! grammar, not a claim that a classifier recognizes arbitrary unknown intent.

use super::AddressKind;
use super::Alias;
use codex_hepta_cognitive_types::InventoryCellRouteV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct QueryTemplate {
    pub operation: MemoryOperationV1,
    pub template: String,
}

// ASCII case folding and whitespace folding only. Unicode names remain exact;
// no transliteration, confusable folding, punctuation removal or substring match.
pub(super) fn normalize(text: &str) -> String {
    text.split_whitespace()
        .map(str::to_ascii_lowercase)
        .collect::<Vec<_>>()
        .join(" ")
}

pub(super) fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name
            .chars()
            .all(|c| c.is_alphanumeric() || matches!(c, ' ' | '_' | '-'))
}

impl QueryTemplate {
    pub fn validate(&self) -> bool {
        let entity = self.template.matches("{entity}").count();
        let workflow = self.template.matches("{workflow}").count();
        let literal = self
            .template
            .replace("{entity}", "")
            .replace("{workflow}", "");
        let shape = match self.operation {
            MemoryOperationV1::Semantic => (1, 0),
            MemoryOperationV1::Procedure => (0, 1),
            MemoryOperationV1::Apply => (1, 1),
            _ => return false,
        };
        !self.template.is_empty()
            && self.template.len() <= 256
            && !self.template.chars().any(char::is_control)
            && (entity, workflow) == shape
            && !literal.contains(['{', '}'])
            && !self.template.contains("}{")
    }

    fn resolve(&self, text: &str, aliases: &[Alias]) -> Option<InventoryCellRouteV1> {
        let first = self.template.find('{')?;
        let end = self.template.find('}')?;
        let kind = slot(&self.template[first..=end])?;
        let rest = &self.template[end + 1..];
        let text = text.strip_prefix(&self.template[..first])?;
        let mut route = InventoryCellRouteV1 {
            operation: self.operation,
            entity: None,
            workflow: None,
        };
        if let Some(second) = rest.find('{') {
            let second_end = rest.find('}')?;
            let second_kind = slot(&rest[second..=second_end])?;
            let text = text.strip_suffix(&rest[second_end + 1..])?;
            let delimiter = &rest[..second];
            let mut matches = text.match_indices(delimiter).filter_map(|(offset, _)| {
                let a = lookup(aliases, kind, &text[..offset])?;
                let b = lookup(aliases, second_kind, &text[offset + delimiter.len()..])?;
                Some((a, b))
            });
            let (a, b) = matches.next()?;
            if matches.next().is_some() {
                return None;
            }
            assign(&mut route, kind, a);
            assign(&mut route, second_kind, b);
        } else {
            let name = text.strip_suffix(rest)?;
            assign(&mut route, kind, lookup(aliases, kind, name)?);
        }
        route.validate().ok()?;
        Some(route)
    }
}

pub(super) fn resolve(
    text: &str,
    templates: &[QueryTemplate],
    aliases: &[Alias],
) -> Option<InventoryCellRouteV1> {
    let normalized = normalize(text);
    let mut matches = templates
        .iter()
        .filter_map(|template| template.resolve(&normalized, aliases));
    let first = matches.next()?;
    // Several declared phrasings may be equivalent; conflicting routes abstain.
    if matches.any(|route| route != first) {
        return None;
    }
    Some(first)
}

fn lookup(aliases: &[Alias], kind: AddressKind, name: &str) -> Option<ContractIdV1> {
    let name = name.trim();
    aliases
        .iter()
        .find(|alias| alias.kind == kind && alias.phrases.iter().any(|phrase| phrase == name))
        .map(|alias| alias.key.clone())
}

fn slot(value: &str) -> Option<AddressKind> {
    match value {
        "{entity}" => Some(AddressKind::Entity),
        "{workflow}" => Some(AddressKind::Workflow),
        _ => None,
    }
}

fn assign(route: &mut InventoryCellRouteV1, kind: AddressKind, key: ContractIdV1) {
    match kind {
        AddressKind::Entity => route.entity = Some(key),
        AddressKind::Workflow => route.workflow = Some(key),
    }
}
