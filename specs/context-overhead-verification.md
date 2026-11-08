# Recurring context measurements

Baseline: Harness `52f0678`. Changed source: implementation of
[context-overhead.md](context-overhead.md) on `fix/assessment-repair`.
Shared contract: 0.7.1, unchanged. Measurements are **controlled serialization and
local-estimate measurements, not live provider token savings**.

The motivating November 8, 02:12 UTC archive predates the control-flow fixes. Its
sampled native request was 61,777 bytes with 17 reference descriptors; the
reference list alone serialized to approximately 5.4 KB with Python's default
JSON formatting. It informed the fixture shape, not a claim of reproducing that
run's failing trajectory with current code.

## Identical workload

`tests/context_overhead_fixture.py` uses the existing four-scenario support bundle,
17 readable references, all 11 frozen tools, four target invocations, two batches
of independent evidence reads, one incorrect finish, a prose/menu reply, and a
corrected finish. The correction cites the first response's actual marker. The
controlled model rereads that response only if its content is absent from native
tool history. Target text contains an unrelated ticket offer and an untrusted
handle; neither becomes campaign requirements or verified metadata.

Both sources use the same 65,536-prompt/4,096-completion test profile, allowances,
scenario/reference/target/model inputs, response policy, and tool schema. The
input digest (excluding the intentionally changed system prompt) is
`sha256:72eea0f658d01dc10d49fbaa7e00bfddb8a0fcf47c8e50923a7ceeda35732d39`.
No production profile or budget is enlarged by this change.

Synthetic accounting reports `ceil(serialized_request_bytes / 4)` input tokens
and 20 output tokens to exercise existing accounting. Those numbers are fixture
inputs, **not actual provider usage**. The local estimate uses Harness's unchanged
heuristic (initially 0.5 tokens/byte, then calibrated against the preceding
synthetic usage). Full per-request numbers and the schema digest are in
[context-overhead.json](measurements/context-overhead.json).

## Serialized request-envelope bytes

The pressure case uses the existing test-only `compact_at=100000` hook, identically
on both sources, to exercise reduction in a short controlled sequence. The second
case uses the production byte threshold, 1,048,576; its short sequence does not
require reduction.

| Metric | Pressure before | Pressure after | No reduction before | No reduction after |
|---|---:|---:|---:|---:|
| Initial request | 45,152 | 37,973 | 45,152 | 37,973 |
| After first independent evidence reads | 75,637 | 68,458 | 75,637 | 68,458 |
| First request repairing finish | 53,087 | 73,166 | 112,309 | 101,660 |
| Cumulative input, including summaries/rereads | 706,447 | 660,167 | 702,322 | 629,800 |
| Model requests | 11 | 10 | 9 | 9 |
| Model-based summaries | 1 | 0 | 0 | 0 |
| Evidence reads, including rereads | 5 | 5 | 4 | 4 |
| Evidence rereads | 1 | 1 | 0 | 0 |
| Frozen native tool declarations | 14,999 | 14,999 | 14,999 | 14,999 |

Initial serialization falls **15.9%**. Cumulative bytes fall **6.6%** under pressure
and **10.3%** without reduction. No additional rereads are introduced relative to
each baseline. Pressure does cost one reread relative to the untrimmed workload;
that cost is included, not hidden by measuring only the immediately trimmed prompt.

The pressure-case repair request grows because local reduction retains recent
observation content while the baseline model summary discards it. The change does
not improve every individual request. Without reduction, repair serialization
falls 9.5%; the diagnostic appears in one authoritative current block, and native
history supplies the original arguments while present. Tool declarations remain
14,999 bytes—39.5% of the smaller initial envelope. Shared-schema simplification
is a separate coordinated contract task.

## Local token estimates, not provider measurements

| Metric | Pressure before | Pressure after | No reduction before | No reduction after |
|---|---:|---:|---:|---:|
| Initial estimate | 22,576 | 18,987 | 22,576 | 18,987 |
| After first evidence reads | 20,802 | 18,827 | 20,802 | 18,827 |
| First repair request | 14,600 | 20,121 | 30,886 | 27,957 |
| Sum of request estimates | 204,443 | 190,100 | 203,307 | 181,747 |

Actual provider-reported usage is unavailable (`null` in the measurement file).
These estimates do not justify lowering reservations, changing budgets, or claiming
live-model reliability or tokenizer-measured savings.

## Reproduce

From the Harness repository, use an empty baseline directory:

```sh
mkdir /tmp/harness-context-baseline-52f0678
git archive 52f0678 | tar -x -C /tmp/harness-context-baseline-52f0678
../operator_sandbox/.venv/bin/python build/measure_context.py \
  --source-root /tmp/harness-context-baseline-52f0678 \
  --operator-root ../operator_sandbox --compact-at 100000 \
  --output /tmp/context-before.json
../operator_sandbox/.venv/bin/python build/measure_context.py \
  --operator-root ../operator_sandbox --compact-at 100000 \
  --output /tmp/context-after.json
```

Repeat both commands with `--compact-at 1048576` for the no-reduction case. The
script uses the selected source/prompt with the same current controlled fixture
and shared contract implementation. It performs no network/provider calls.

## Regression scope

Harness tests exercise complete/deferred scenarios, real reference reads, local
and host rejection, exact duplicate-key retention, correction without replay,
independent reads, range citations, truthful context-limit termination, protected
finalization, and native history validation for Chat Completions, Responses,
Anthropic Messages, Bedrock Converse, and Gemini.

Validation passed: 171 Harness tests, 45 shared Python tests, source-lock and syntax
checks. Separate process tests passed for simple/direct/artifact campaigns,
partial evidence pagination, corrected assessments, no-progress termination,
protected finalization, both structured budget-exhaustion cases, and the new local
context-reduction workflow. Operator provenance for these controlled tests is
`6c80282707354fbf86826c244ce401380460aa4a`; it is not a new compatibility pin.

The separate Operator/Harness process regression uses local controlled providers
and native target fixtures over FIFO and spool, including history reduction during
exploration and repair, evidence rereading, accepted assessment, Harness exit zero,
cleanup, and exported scenario attribution. The Go overlay's diagnostic assertion
reads the new authoritative repair block instead of expecting a duplicated diagnostic
in tool history; no Operator source or shared interface changes are required.

The oversized-scenario unit fixture now forces deferred delivery with a smaller
test task limit and realistically sized complete scenarios, retaining the original
32k-token model profile and exact read-accounting assertions. Production limits
are unchanged. Controlled responses verify plumbing and safeguards, not whether
a live model will always retain investigative focus or choose sufficient rereads.
No paid/cloud evaluation or release publication is included.
