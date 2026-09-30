//! Shared read-only host fixtures; not product code or an owner implementation.
use super::*;

pub(crate) fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(id) => id,
        Err(error) => panic!("fixture identifier: {error}"),
    }
}

pub(crate) fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(generation) => generation,
        Err(error) => panic!("fixture generation: {error}"),
    }
}

pub(crate) fn event_log(events: &Arc<Mutex<Vec<String>>>) -> MutexGuard<'_, Vec<String>> {
    match events.lock() {
        Ok(events) => events,
        Err(_) => panic!("event lock poisoned"),
    }
}

pub(crate) fn new_host(
    graph: OrganGraphsV1,
    handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
) -> OrganHostV1 {
    match OrganHostV1::new(graph, handlers) {
        Ok(host) => host,
        Err(error) => panic!("valid host: {error}"),
    }
}

pub(crate) fn start_host(host: &mut OrganHostV1) {
    if let Err(error) = host.start_all() {
        panic!("start host: {error}");
    }
}

pub(crate) fn graph() -> OrganGraphsV1 {
    let port = id("message.v1");
    let safe = FallbackTerminal::SafeState(Digest32::of_bytes(b"safe"));
    OrganGraphsV1 {
        generation: generation(7),
        organs: vec![
            OrganNodeV1 {
                id: id("source"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![],
                outputs: vec![port.clone()],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.a"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port.clone()],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.b"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: safe,
            },
        ],
        initialization: vec![OrganEdge { from: 0, to: 1 }, OrganEdge { from: 1, to: 2 }],
        runtime: vec![
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing: DataflowTiming::Buffered,
            },
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 2, port: 0 },
                timing: DataflowTiming::Buffered,
            },
        ],
        feedback: vec![],
        fallback: vec![OrganEdge { from: 0, to: 2 }, OrganEdge { from: 1, to: 2 }],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id(&format!("process.{organ}")),
                host: id("host"),
            })
            .collect(),
    }
}

#[derive(Debug)]
pub(crate) struct FixtureOrgan {
    pub(crate) id: StableId,
    pub(crate) events: Arc<Mutex<Vec<String>>>,
    pub(crate) start_fault: bool,
    pub(crate) handle_fault: bool,
    pub(crate) stop_fault: bool,
    pub(crate) output_bytes: usize,
}

impl TrustedReadOnlyOrganV1 for FixtureOrgan {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.record("start");
        if self.start_fault {
            Err(self.fault("start"))
        } else {
            Ok(())
        }
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        self.record(&format!("handle:{input_port}:{}", payload.len()));
        if self.handle_fault {
            Err(self.fault("handle"))
        } else {
            Ok(vec![self.id.as_str().as_bytes()[0]; self.output_bytes])
        }
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.record("stop");
        if self.stop_fault {
            Err(self.fault("stop"))
        } else {
            Ok(())
        }
    }
}

impl FixtureOrgan {
    pub(crate) fn new(name: &str, events: Arc<Mutex<Vec<String>>>) -> Self {
        Self {
            id: id(name),
            events,
            start_fault: false,
            handle_fault: false,
            stop_fault: false,
            output_bytes: 1,
        }
    }

    fn record(&self, event: &str) {
        event_log(&self.events).push(format!("{event}:{}", self.id));
    }

    fn fault(&self, phase: &str) -> OrganHandlerFaultV1 {
        OrganHandlerFaultV1::new(id(&format!("{phase}.fault")))
    }
}

pub(crate) fn handlers(events: &Arc<Mutex<Vec<String>>>) -> Vec<Box<dyn TrustedReadOnlyOrganV1>> {
    ["source", "target.a", "target.b"]
        .into_iter()
        .map(|name| {
            Box::new(FixtureOrgan::new(name, Arc::clone(events))) as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect()
}
