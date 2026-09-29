// Presentation reuse, never an authorization cache. Records are pruned to the
// current list and full correlation identities are kept outside DOM attributes.
export function createKeyedList(container) {
  let records = new Map();
  let nodes = [];
  return (items, keyOf, create, update) => {
    const next = new Map();
    const desired = [];
    for (const item of items) {
      const key = keyOf(item);
      if (next.has(key)) throw new TypeError("duplicate presentation identity");
      const record = records.get(key) ?? create(item);
      update(record, item);
      next.set(key, record);
      desired.push(record.node);
    }
    // Content-only updates preserve both DOM identity and focus. Structural
    // changes reuse surviving nodes; the console restores focus if necessary.
    if (desired.length !== nodes.length || desired.some((node, i) => node !== nodes[i])) {
      container.replaceChildren(...desired);
    }
    records = next;
    nodes = desired;
  };
}

export function setText(element, value) {
  const content = String(value);
  if (element.textContent !== content) element.textContent = content;
}
