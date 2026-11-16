# Scenario context loading verification

This is controlled verification, not a live Mistral/cloud campaign or evidence of
live-model compliance. Operator's bundle and tool contracts remain unchanged.

The QA archive's initial provider request contained eight complete scenarios and
the original bundle handle: 47,587 serialized request bytes, including a 22,482-byte
task message. The scenarios themselves occupied 12,252 bytes when reserialized
with Python's default JSON spacing. Those figures are bytes, not token usage.
The archive was inspected read-only; its target content is not copied into this
repository.

## Workflow checks

`tests/test_scenario_loading.py` runs the production composition, native model
response validation, dispatcher, scenario delivery, observation reader, history
reduction, and finish adapter with controlled peer responses across Chat,
Responses, Anthropic, Bedrock Converse, and Gemini codecs. It verifies:

- An index-only initial request and complete, single active scenario bodies.
- Selection confirmation without copied/paginated instructions in tool history.
- Same-response selection/execution rejection before target dispatch.
- Two scenario executions, evidence inspection, switching, two snapshots with
  parentage, restore, and retained revision/observation associations.
- Local trimming during assessment repair, blocked exploration, scenario revisit,
  two evidence rereads, and an accepted multi-scenario assessment.
- Unvisited scenarios remain explicit. Inspected citations survive trimming while
  content-presence flags reflect the actual current prompt.
- The complete original bundle and recorded prior requests remain intact.

`test_scenario_delivery`, `test_context_overhead`, `test_instruction_boundary`,
and `test_finalization_capacity` also cover oversized requirements, ordinary
bundle/resource byte reads, explicit invalid selection offsets, context limits,
trusted instruction boundaries, exact repair state, and reserved finalization.

`TestHarnessScenarioLoadingProcess` uses actual Python Harness and Go Operator
processes over FIFO and spool, with controlled model responses and the local
native target fixture. Provider requests are checked for a single active scenario
and absent scenario bodies in tool-result history. It executes two scenarios,
reads both outputs, creates/restores a snapshot, revisits requirements, submits
one assessment citing both outputs, exits zero, confirms cleanup, and checks
exported scenario associations. The test-only overlays add explicit selection to
older scripted workflows; production transport and Operator code are unchanged.

## Validation results

`make test-pr` passes 177 Harness tests, 45 shared Python contract tests, source
inventory verification, and syntax checks. Process verification used Operator
`22409c18079f71a21f858ced017021288ad964f9` as implementation provenance with the
unchanged approved contract 0.9.0; no Operator source revision is required for
compatibility.

The complete integration run passed every case except the inherited
`TestPythonUnsupportedFieldRepairAndExport` script, which initially attempted its
scenario without selecting it. After its test-only selection update, that case
and both new scenario process lanes passed. The final scenario and local/context
reduction process cases were rerun successfully after the context-size accounting
review. No release was published and no live/paid model campaign was run.

## Cumulative comparison

Baseline: `697130e` (`candidate-v0.1.4` when this branch was created).
Measurements are recorded in [scenario-context-loading.json](measurements/scenario-context-loading.json).
Both versions receive identical four- or eight-scenario synthetic bundles and
perform the same two experiments, snapshots/restore, evidence reads, rejected
finish, and correction. The baseline does **not** make redundant full-bundle reads,
so this comparison does not attribute the QA run's avoided rereads as savings.

The new workflow makes 12 model requests versus 11 previously. Its first selection
requires an additional turn; subsequent selections share independent evidence-read
responses. Both versions make four observation reads (two deliberate final
rereads), zero model-summary calls, two target invocations, and one restore. The
new version also revisits individual requirements during repair.

| Bundle / history policy | Before cumulative bytes | After cumulative bytes | Change |
| --- | ---: | ---: | ---: |
| Four scenarios, no forced reduction | 418,808 | 476,135 | +13.69% |
| Four scenarios, one forced reduction | 406,199 | 454,968 | +12.01% |
| Eight scenarios, no forced reduction | 509,591 | 496,563 | −2.56% |
| Eight scenarios, one forced reduction | 496,982 | 475,396 | −4.34% |

These totals sum serialized Harness conversation requests plus fixed prompt and
tool-schema bytes per request. They are an input-size proxy, not exact provider
wire bytes or tokens. Initial conversation request sizes fall from 11,658 to
9,920 bytes for four scenarios, and from 19,911 to 11,109 for eight. The small-bundle
case costs more overall despite that smaller initial request: selection overhead
and factual records outweigh deferred content. The JSON also reports bytes/4
estimates separately. Actual provider usage is unavailable; fixture accounting is
synthetic and must not be reported as measured token savings.

Reproduce from the repository root with the matching Operator checkout:

```sh
mkdir -p /tmp/harness-scenario-before
git archive 697130e src assets | tar -x -C /tmp/harness-scenario-before
PYTHONPATH=/tmp/harness-scenario-before/src:../operator_sandbox/contracts/python:tests \
  ../operator_sandbox/.venv/bin/python build/measure_scenario_loading.py \
  --prompt /tmp/harness-scenario-before/assets/default-system-prompt.txt \
  --output /tmp/scenario-before.json
PYTHONPATH=src:../operator_sandbox/contracts/python:tests \
  ../operator_sandbox/.venv/bin/python build/measure_scenario_loading.py \
  --output /tmp/scenario-after.json
make test-pr
make test-integration
```

Full evidence retention, shared validation, and the finalization action restriction
remain in force. Controlled fixtures establish delivery, correlation, and dispatch
behavior; they cannot establish that a live model will select efficiently, avoid
all unnecessary reads, or produce an acceptable assessment.
