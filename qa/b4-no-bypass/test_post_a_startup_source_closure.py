"""Post-A startup must finish before the historical delivery can submit work.

These are lexical source and mutation controls. They do not execute a Rust
future, establish a live Root permission, or prove a successful ordinary parent.
"""

from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_hepta_callers as PROOF


AGENT = "codex-rs/hepta-agentd/src/"
CONT = AGENT + "production_post_a_continuation.rs"
DELIVERY = AGENT + "learning_iteration_historical_source.rs"
PREPARE = "fn prepare_original_delivery("
CONSUME = "fn run_original_prepared_continuation("
PREPARED = "OriginalPreparedPostAContinuationV1"
FIELDS = (
    ("source", "Arc<RegisteredHistoricalLearningSourceV1>"),
    ("owners", "Arc<OriginalCellQ24LearningStageOwnersV1>"),
    ("trust", "Arc<OriginalHistoricalLearningTrustV1>"),
    ("receipt", "Arc<OriginalHistoricalTaskReadReceiptV1>"),
    ("successor", "OriginalQ24SuccessorHandoffV1"),
    ("publication", "OriginalPreparedPublicationRoute"),
    ("material", "OriginalMaterialWriter"),
    ("artifacts", "OriginalArtifactPlan"),
    ("task", "OriginalCTaskPlan"),
    ("generation", "OriginalGenerationFiles"),
    ("files", "OriginalFiles"),
    ("baseline", "Arc<LoadedCellQ24ModelV1>"),
    ("final_use", "Arc<FinalUseAuthority>"),
    ("clock", "Arc<dyn AuthorityClock>"),
    ("identity", "AgentdIdentity"),
    ("end", "Instant"),
    ("state", "Arc<AgentdState>"),
    ("cancelled", "CancellationToken"),
)


def stripped(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


TOKENS = re.compile(r"::|->|=>|==|!=|<=|>=|&&|\|\||[A-Za-z_]\w*|[0-9]+|[^\s]")


def marker_pattern(marker):
    """Ignore whitespace, preserving token boundaries and original source offsets."""
    tokens = TOKENS.findall(marker)
    pieces = [r"(?<!\w)" + re.escape(token) + r"(?!\w)" if re.fullmatch(r"\w+", token)
              else re.escape(token) for token in tokens]
    return re.compile(r"\s*".join(pieces))


def marker_span(code, marker, start=0, end=None, *, unique=False):
    matches = list(marker_pattern(marker).finditer(code, start, len(code) if end is None else end))
    if not matches or unique and len(matches) != 1:
        raise PROOF.VerificationFailure("actual code marker missing or ambiguous: " + marker)
    return matches[0].span()


def replace_marker(source, marker, replacement, start=0, end=None):
    begin, finish = marker_span(stripped(source), marker, start, end, unique=True)
    return source[:begin] + replacement + source[finish:]


def parenthesis_end(code, opening):
    if code[opening] != "(":
        raise PROOF.VerificationFailure("actual opening parenthesis required")
    depth = 0
    for position in range(opening, len(code)):
        depth += (code[position] == "(") - (code[position] == ")")
        if depth == 0:
            return position + 1
    raise PROOF.VerificationFailure("complete original argument list required")


def function_span(code, marker):
    start, _ = marker_span(code, marker, unique=True)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("complete startup function required")
    return start, end + 1


def startup_spans(source):
    """Keep the real awaited match and both futures ordered across formatting."""
    code = stripped(source)
    start, end = function_span(code, "fn run(")
    markers = (
        "let joined = cancellation.child_token();",
        "let continuation = match crate::production_launcher::OriginalPostAContinuationV1::prepare_original_delivery(",
        ".await {", "Ok(Some(continuation)) => continuation,", "Ok(None) => return Ok(()),",
        "Err(error) => {", "joined.cancel();", "return Err(error);",
        "let delivery = self.run_delivery(handle, Arc::clone(&state), joined.clone());",
        "let continuation = continuation.run_original_prepared_continuation();",
    )
    positions = []
    cursor = start
    for marker in markers:
        span = marker_span(code, marker, cursor, end, unique=True)
        positions.append(span)
        cursor = span[1]
    for index in (0, 1, 8, 9):
        before = code[start:positions[index][0]]
        if before.count("{") - before.count("}") != 1:
            raise PROOF.VerificationFailure("startup or future escaped the original top-level path")
    calls = list(marker_pattern("run_delivery(").finditer(code, positions[0][1], end))
    if len(calls) != 1 or not positions[8][0] < calls[0].start() < positions[8][1]:
        raise PROOF.VerificationFailure("delivery must not be created before successful startup")
    return {"preparation": positions[1], "await": positions[2],
            "delivery": positions[8], "consumer": positions[9]}


def move_delivery_before_preparation(source):
    spans = startup_spans(source)
    first = spans["preparation"][0]
    start, end = spans["delivery"]
    return source[:first] + source[start:end] + "\n" + source[first:start] + source[end:]


def require_prepared_shape(source):
    """Check the one non-clonable private-field owner and its sole construction."""
    code = stripped(source)
    marker = "pub(crate) struct " + PREPARED + " {"
    start, declaration_end = marker_span(code, marker, unique=True)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("complete private prepared owner required")
    expected = marker + "\n" + "\n".join(
        "    " + name + ": " + kind + "," for name, kind in FIELDS
    ) + "\n}"
    if TOKENS.findall(code[start:end + 1]) != TOKENS.findall(expected):
        raise PROOF.VerificationFailure("prepared fields must be the original private inputs")
    if code[:start].rstrip().endswith("]") or re.search(
        r"\bimpl\s+(?:[\w:]+::)?(?:Clone|Default)\s+for\s+" + PREPARED + r"\b", code
    ):
        raise PROOF.VerificationFailure("prepared owner cannot be derived, cloned or defaulted")
    impl_marker = "impl " + PREPARED + " {"
    implementation, impl_header_end = marker_span(code, impl_marker, unique=True)
    implementation_end = PROOF._rust_item_end(code, implementation)
    if implementation_end is None:
        raise PROOF.VerificationFailure("complete prepared impl required")
    construct = "Ok(Some(" + PREPARED + " {"
    construction, constructor_header_end = marker_span(code, construct, unique=True)
    prepare_start, prepare_end = function_span(code, PREPARE)
    if not prepare_start < construction < prepare_end:
        raise PROOF.VerificationFailure("prepared construction escaped actual preflight")
    expected_mentions = {
        marker_span(code, PREPARED, start, declaration_end, unique=True)[0],
        marker_span(code, PREPARED, construction, constructor_header_end, unique=True)[0],
        marker_span(code, PREPARED, implementation, impl_header_end, unique=True)[0],
    }
    actual_mentions = {match.start() for match in marker_pattern(PREPARED + " {").finditer(code)}
    if actual_mentions != expected_mentions:
        raise PROOF.VerificationFailure("additional prepared owner construction or impl")
    consume_start, consume_end = function_span(code, CONSUME)
    if not implementation < consume_start < consume_end <= implementation_end + 1:
        raise PROOF.VerificationFailure("consumer must belong to the original prepared owner")
    implementation_body = code[implementation:implementation_end + 1]
    if len(re.findall(r"\bSelf\s*\{", implementation_body)) != 1:
        raise PROOF.VerificationFailure("prepared consumer must only destructure its own inputs")
    signature = (marker_pattern(CONSUME + "self").pattern + r"\s*,?\s*" +
                 marker_pattern(") -> Result<(), AgentdError> {").pattern)
    if re.match(signature, code[consume_start:consume_end]) is None:
        raise PROOF.VerificationFailure("prepared consumer cannot accept replacement state or token")
    names = "|".join(re.escape(name) for name, _ in FIELDS)
    shadow = re.compile(r"\blet\s+(?:mut\s+)?(?:" + names + r")\s*(?::[^;=]+)?=")
    if shadow.search(code[prepare_start:prepare_end]):
        raise PROOF.VerificationFailure("startup cannot shadow transferred original inputs")
    if re.search(r"\blet\s+(?:mut\s+)?(?:state|cancelled)\s*(?::[^;=]+)?=",
                 code[consume_start:consume_end]):
        raise PROOF.VerificationFailure("consumer cannot replace its retained state or token")


class PostAStartupSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def verify_source(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        if path == CONT:
            require_prepared_shape(source)
        elif path == DELIVERY:
            startup_spans(source)

    def reject_change(self, path, before, after):
        self.verify_source(path, before)
        self.assertNotEqual(before, after)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify_source(path, after)

    def reject_removal(self, path, marker, token):
        source = (ROOT / path).read_text()
        start, end = function_span(stripped(source), marker)
        position, finish = marker_span(stripped(source), token, start, end)
        self.reject_change(path, source,
                           source[:position] + "/* " + source[position:finish] + " */" + source[finish:])

    def test_startup_keeps_admission_current_source_trust_and_original_end(self):
        for token in (
            "drop(grants);", "if cancelled.is_cancelled()", "return Ok(None);",
            "post_a_remaining(end)?", "require_successor_admission(&state, &identity)",
            "_ = cancelled.cancelled() => return Ok(None)",
            "tokio::time::sleep(post_a_remaining(end)?.min(Duration::from_millis(25)))",
            "RegisteredHistoricalLearningSourceV1::require_current_historical_source(",
            "&source, &identity,",
            "OriginalHistoricalLearningTrustV1::require_original_receipt(&trust, &receipt)?",
        ):
            with self.subTest(token=token):
                self.reject_removal(CONT, PREPARE, token)

    def test_startup_must_finish_successfully_before_delivery_is_created(self):
        for token in (
            "OriginalPostAContinuationV1::prepare_original_delivery(",
            "Arc::clone(&state),", "joined.clone(),", ".await {",
            "Ok(Some(continuation)) => continuation,", "Ok(None) => return Ok(()),",
            "joined.cancel();", "return Err(error);",
            "let delivery = self.run_delivery(handle, Arc::clone(&state), joined.clone());",
            "let continuation = continuation.run_original_prepared_continuation();",
        ):
            with self.subTest(token=token):
                self.reject_removal(DELIVERY, "fn run(", token)
        source = (ROOT / DELIVERY).read_text()
        self.reject_change(DELIVERY, source, move_delivery_before_preparation(source))
        spans = startup_spans(source)
        ranges = ((spans["preparation"][0], spans["await"][1]),
                  spans["delivery"], spans["consumer"])
        reformatted = source
        for begin, finish in sorted(ranges, reverse=True):
            reformatted = (reformatted[:begin] + re.sub(r"\s+", "\n    ", source[begin:finish])
                           + reformatted[finish:])
        self.assertEqual(TOKENS.findall(stripped(source)), TOKENS.findall(stripped(reformatted)))
        # This tests the QA's formatter-independent locator/order check only.
        # The unchanged CALLERS literals still require actual formatted-byte rebinding.
        startup_spans(reformatted)
        for mutation in (
            move_delivery_before_preparation(reformatted),
            replace_marker(reformatted, ".await {", "{"),
            replace_marker(reformatted, "Ok(Some(continuation)) => continuation,", "Ok(Some(continuation)) => return Ok(()),"),
            replace_marker(reformatted, "Ok(None) => return Ok(()),", "Ok(None) => continuation,"),
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                startup_spans(mutation)

    def test_prepared_fields_stay_private_and_state_token_cannot_be_rebound(self):
        source = (ROOT / CONT).read_text()
        code = stripped(source)
        marker = "pub(crate) struct " + PREPARED + " {"
        declaration, _ = marker_span(code, marker, unique=True)
        declaration_end = PROOF._rust_item_end(code, declaration)
        field, _ = marker_span(code, "state: Arc<AgentdState>,", declaration, declaration_end, unique=True)
        _, parameters = marker_span(code, CONSUME, unique=True)
        parameters -= 1
        parameters_end = parenthesis_end(code, parameters)
        construct, _ = marker_span(code, "Ok(Some(" + PREPARED + " {", unique=True)
        mutations = (
            source[:field] + "pub " + source[field:],
            source[:declaration] + "#[derive(Clone)]\n" + source[declaration:],
            source[:declaration] + "#[derive(Default, Clone)]\n" + source[declaration:],
            source[:parameters] + "(self, state: Arc<AgentdState>)" + source[parameters_end:],
            source[:construct] + "let state = replacement_state;\n        " + source[construct:],
            source[:construct] + "let cancelled = replacement_token;\n        " + source[construct:],
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                self.reject_change(CONT, source, mutation)
        # Whitespace and a formatter-added trailing comma cannot create an extra argument.
        formatted = source[:parameters] + "(\n        self,\n    )" + source[parameters_end:]
        require_prepared_shape(formatted)

    def test_successful_preflight_is_the_only_prepared_owner_constructor(self):
        source = (ROOT / CONT).read_text()
        code = stripped(source)
        construct = "Ok(Some(" + PREPARED + " {"
        start, _ = marker_span(code, construct, unique=True)
        opening = code.index("(", start)
        end = parenthesis_end(code, opening)
        extra = source[start:end]
        mutation = source + "\nfn bypass_original_preflight() { " + extra + " }\n"
        self.reject_change(CONT, source, mutation)
        for token in ("source,", "owners,", "trust,", "receipt,", "successor,", "publication,",
                      "material,", "artifacts,", "task,", "generation,", "files,", "baseline,",
                      "final_use,", "clock,", "identity,", "end,", "state,", "cancelled,"):
            position, finish = marker_span(code, token, start, end, unique=True)
            mutation = source[:position] + "/* " + source[position:finish] + " */" + source[finish:]
            with self.subTest(field=token):
                self.reject_change(CONT, source, mutation)

    def test_startup_and_consumer_reject_every_unlisted_matching_product_caller(self):
        boundaries = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        original_index = {path: stripped((ROOT / path).read_text()) for path in (CONT, DELIVERY)}
        for identifier, owner, method in (
            ("post_a_continuation_original_startup", "OriginalPostAContinuationV1", "prepare_original_delivery"),
            ("post_a_continuation_supervised_run", PREPARED, "run_original_prepared_continuation"),
        ):
            boundary = boundaries[identifier]
            self.assertEqual(boundary.product_callers, (DELIVERY,))
            PROOF._verify_boundary(ROOT, boundary, original_index, ignored, fields_by_receiver_type={})
            foreign = AGENT + "unlisted_startup_probe.rs"
            for call in (f"unresolved.{method}()", f"{owner}::{method}(owner)",
                         f"<{owner}>::{method}(owner)", f"some::alias::{method}(owner)"):
                injected = dict(original_index)
                injected[foreign] = "fn probe() { " + call + "; }"
                with self.subTest(boundary=identifier, call=call):
                    with self.assertRaises(PROOF.VerificationFailure) as raised:
                        PROOF._verify_boundary(ROOT, boundary, injected, ignored, fields_by_receiver_type={})
                    self.assertIn(foreign, str(raised.exception))

    def test_both_owned_futures_stay_joined_after_first_error_and_cancellation(self):
        for token in (
            "let delivery_cancelled = joined.clone();", "let continuation_cancelled = joined.clone();",
            "let first_failure = AtomicU8::new(0);", "tokio::join!(", "let result = delivery.await",
            "first_failure.compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)",
            "delivery_cancelled.cancel()", "let result = continuation.await",
            "first_failure.compare_exchange(0, 2, Ordering::AcqRel, Ordering::Acquire)",
            "continuation_cancelled.cancel()", "if first_failure.load(Ordering::Acquire) == 2 {",
            "continuation?;", "return delivery;", "delivery?;",
        ):
            with self.subTest(token=token):
                self.reject_removal(DELIVERY, "fn run(", token)


if __name__ == "__main__":
    unittest.main()
