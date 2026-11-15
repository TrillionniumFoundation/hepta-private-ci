//! Complete public-crate observer; no parsing or rendering implementation.
mod counter;
mod lifecycle;
use std::error::Error;
use std::io::Read;
use std::io::Write;
use std::panic::AssertUnwindSafe;
use subject::Template;
use subject::TemplateError;
use subject::TemplateParseError;
use subject::TemplateRenderError;

struct Output(Vec<u8>);
impl Output {
    fn word(&mut self, value: u64) {
        self.0.extend_from_slice(&value.to_le_bytes());
    }
    fn text(&mut self, value: &str) {
        self.word(value.len() as u64);
        self.0.extend_from_slice(value.as_bytes());
    }
    fn truth(&mut self, value: bool) {
        self.word(u64::from(value));
    }
}

fn error<E: Error + Clone + Eq>(error: &E, out: &mut Output) {
    out.text(&format!("{error:?}"));
    out.text(&error.to_string());
    let cloned = error.clone();
    out.truth(error == &cloned);
    out.text(&format!("{cloned:?}"));
    let mut source = error.source();
    let mut count = 0;
    while let Some(inner) = source {
        out.truth(true);
        out.text(&format!("{inner:?}"));
        out.text(&inner.to_string());
        source = inner.source();
        count += 1;
        assert!(count < 8);
    }
    out.truth(false);
}

fn rendering<E, F>(values: &[(String, String)], fault: u64, out: &mut Output, invoke: F)
where
    E: Error + Clone + Eq,
    F: FnOnce(lifecycle::Input) -> Result<String, E>,
{
    let (input, events) = lifecycle::Input::new(values, fault);
    match std::panic::catch_unwind(AssertUnwindSafe(|| invoke(input))) {
        Ok(Ok(rendered)) => {
            out.word(0);
            out.text(&rendered);
        }
        Ok(Err(failure)) => {
            out.word(1);
            error(&failure, out);
        }
        Err(payload) => {
            out.word(2);
            if let Some(value) = payload.downcast_ref::<String>() {
                out.text("String");
                out.text(value);
            } else if let Some(value) = payload.downcast_ref::<&str>() {
                out.text("&str");
                out.text(value);
            } else {
                panic!("unexpected non-string panic payload");
            }
        }
    }
    let events = events.borrow();
    out.word(events.len() as u64);
    for event in events.iter() {
        out.text(event);
    }
}

fn parse_tag(value: &Result<Template, TemplateParseError>) -> u64 {
    match value {
        Ok(_) => 0,
        Err(TemplateParseError::EmptyPlaceholder { .. }) => 1,
        Err(TemplateParseError::NestedPlaceholder { .. }) => 2,
        Err(TemplateParseError::UnmatchedClosingDelimiter { .. }) => 3,
        Err(TemplateParseError::UnterminatedPlaceholder { .. }) => 4,
    }
}

fn observe(source: &str, values: &[(String, String)], fault: u64) -> Output {
    let mut out = Output(Vec::new());
    let mut owned = source.to_owned();
    counter::stage(1);
    let parsed = Template::parse(&owned);
    let source_len = owned.len();
    owned.clear();
    owned.push_str(&"X".repeat(source_len));
    drop(owned);
    out.word(parse_tag(&parsed));
    out.word(source_len as u64);
    let start = match &parsed {
        Ok(_) => 0,
        Err(
            TemplateParseError::EmptyPlaceholder { start }
            | TemplateParseError::NestedPlaceholder { start }
            | TemplateParseError::UnmatchedClosingDelimiter { start }
            | TemplateParseError::UnterminatedPlaceholder { start },
        ) => *start,
    };
    out.word(start as u64);
    out.text(&format!("{parsed:?}"));
    match parsed {
        Ok(template) => {
            let cloned = template.clone();
            out.truth(template == cloned);
            out.text(&format!("{cloned:?}"));
            counter::stage(2);
            let reparsed = Template::parse(source);
            out.text(&format!("{reparsed:?}"));
            out.truth(reparsed.as_ref() == Ok(&template));
            counter::stage(4);
            let empty = Template::parse("").unwrap_or_else(|failure| panic!("{failure}"));
            out.truth(template == empty);
            out.truth(template != empty);
            let mut names = Vec::new();
            let mut iter = template.placeholders();
            loop {
                out.word(iter.len() as u64);
                let (lower, upper) = iter.size_hint();
                out.word(lower as u64);
                out.word(upper.unwrap_or(usize::MAX) as u64);
                if let Some(name) = iter.next() {
                    out.truth(true);
                    out.text(name);
                    names.push(name.to_owned());
                } else {
                    out.truth(false);
                    break;
                }
            }
            out.truth(iter.next().is_none());
            out.word(iter.len() as u64);
            drop(iter);
            counter::stage(10);
            rendering(values, fault, &mut out, |input| template.render(input));
            let auto: Vec<_> = names
                .iter()
                .rev()
                .enumerate()
                .map(|(index, name)| (name.clone(), format!("value:{index}:{{{{}}}}\0漢")))
                .collect();
            counter::stage(11);
            rendering(&auto, 0, &mut out, |input| template.render(input));
            drop(template);
            let reusable: Vec<_> = auto
                .into_iter()
                .map(|(name, value)| (name, format!("second:{value}")))
                .collect();
            counter::stage(12);
            rendering(&reusable, 0, &mut out, |input| cloned.render(input));
        }
        Err(failure) => {
            error(&failure, &mut out);
            error(&TemplateError::from(failure), &mut out);
        }
    }
    counter::stage(3);
    rendering(values, fault, &mut out, |input| {
        subject::render(source, input)
    });
    out
}

fn constructors() -> Output {
    let mut out = Output(Vec::new());
    for start in [0, 1, usize::MAX] {
        for value in [
            TemplateParseError::EmptyPlaceholder { start },
            TemplateParseError::NestedPlaceholder { start },
            TemplateParseError::UnmatchedClosingDelimiter { start },
            TemplateParseError::UnterminatedPlaceholder { start },
        ] {
            error(&value, &mut out);
            error(&TemplateError::from(value), &mut out);
        }
    }
    for name in ["", "\0漢{{ x }}", "z"] {
        for value in [
            TemplateRenderError::DuplicateValue {
                name: name.to_owned(),
            },
            TemplateRenderError::ExtraValue {
                name: name.to_owned(),
            },
            TemplateRenderError::MissingValue {
                name: name.to_owned(),
            },
        ] {
            error(&value, &mut out);
            error(&TemplateError::from(value), &mut out);
        }
    }
    out.truth(
        TemplateParseError::EmptyPlaceholder { start: 0 }
            != TemplateParseError::UnterminatedPlaceholder { start: 0 },
    );
    out.truth(
        TemplateRenderError::ExtraValue {
            name: "x".to_owned(),
        } != TemplateRenderError::MissingValue {
            name: "x".to_owned(),
        },
    );
    out
}

fn word(input: &mut impl Read) -> std::io::Result<u64> {
    let mut bytes = [0_u8; 8];
    input.read_exact(&mut bytes)?;
    Ok(u64::from_le_bytes(bytes))
}

fn text(input: &mut impl Read) -> Result<String, Box<dyn Error>> {
    let size = usize::try_from(word(input)?)?;
    if size > 4 * 1024 * 1024 {
        return Err("oversized source/value in fixture".into());
    }
    let mut bytes = vec![0_u8; size];
    input.read_exact(&mut bytes)?;
    Ok(String::from_utf8(bytes)?)
}

fn frame(output: &mut impl Write, id: u64, result: Output) -> std::io::Result<()> {
    let calls = counter::take();
    output.write_all(&id.to_le_bytes())?;
    output.write_all(&(result.0.len() as u64).to_le_bytes())?;
    output.write_all(&(calls.len() as u64).to_le_bytes())?;
    output.write_all(&result.0)?;
    for row in calls {
        for value in row {
            output.write_all(&value.to_le_bytes())?;
        }
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    std::panic::set_hook(Box::new(|_| {}));
    let mut input = std::io::BufReader::new(std::io::stdin().lock());
    let mut output = std::io::BufWriter::new(std::io::stdout().lock());
    let mut magic = [0_u8; 4];
    input.read_exact(&mut magic)?;
    if magic != *b"TPC1" {
        return Err("invalid fixture magic".into());
    }
    let count = word(&mut input)?;
    frame(&mut output, u64::MAX, constructors())?;
    for expected in 0..count {
        let id = word(&mut input)?;
        if id != expected {
            return Err("non-sequential fixture id".into());
        }
        let source = text(&mut input)?;
        let fault = word(&mut input)?;
        let count = word(&mut input)?;
        if count > 100 || fault > 8 {
            return Err("invalid variable profile".into());
        }
        let mut values = Vec::new();
        for _ in 0..count {
            values.push((text(&mut input)?, text(&mut input)?));
        }
        frame(&mut output, id, observe(&source, &values, fault))?;
    }
    let mut extra = [0_u8; 1];
    if input.read(&mut extra)? != 0 {
        return Err("trailing fixture bytes".into());
    }
    output.flush()?;
    Ok(())
}
