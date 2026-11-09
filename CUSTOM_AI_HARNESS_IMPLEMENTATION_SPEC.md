# Attack Harness runtime

Attack Harness v0.1.4 is a single Python process inside an Operator-managed
container. It reads campaign objectives and scenarios, asks a model to choose
permitted experiments, inspects feedback, and submits an assessment. Operator
owns external effects, authorization, durable evidence, and cleanup.

The exact shared package, compatible runtime, and model-tool examples are documented
in [the integration guide](docs/INTEGRATION.md). The image layout and confinement
boundary are documented in [the container specification](GUEST_ARTIFACT_LAYOUT_SPEC.md).

## Contract ownership

The Harness loads Operator's shared contract package from the image and validates
its version and exact AsyncAPI document-byte hash against
[the contract lock](build/contract-lock.json).
The package supplies schemas, semantic validators, operation definitions,
provider tool projections, and fixtures. Startup also checks the host's package,
registry, and release bindings. An incompatible package fails before execution.

No model-facing schema is independently maintained in Harness. The shared
provider projections describe the same runtime interface; runtime validators
continue enforcing constraints that a provider's schema dialect cannot express.

## Process composition

[`composition.py`](src/attack_harness/composition.py) creates each mutable service
once per admitted campaign. They share the same protocol, transport client,
verified inputs, limits, execution receipt state, and finalizer.

| Component | Responsibility |
| --- | --- |
| `bootstrap.py`, `entrypoint.py`, `startup.py` | Load fixed release code, select transport, install confinement, verify startup identities, and enter the campaign. |
| `files.py`, `inputs.py`, `skill_loader.py` | Read bounded immutable inventories, validate paths and identities, and load passive instructions and references. |
| `fifo.py`, `spool.py`, `runtime.py` | Frame and correlate host communication, enforce deadlines, service control messages, and close execution. |
| `composition.py`, `adaptive.py` | Construct the campaign context and run the bounded model/tool loop. |
| `tools.py`, `handlers.py` | Validate calls, expose permitted handlers, and return correlated results or actionable errors. |
| `attempts.py` | Validate explicit origin, submit attempts unchanged, retain execution receipts, and prevent duplicate submissions. |
| `artifacts.py`, `observations.py` | Publish committed content and read permitted evidence with integrity and bounds checks. |
| `conclusion.py` | Validate assessment references and submit the single finish operation. |
| `diagnostics.py` | Preserve failure causes and emit bounded host/stderr diagnostics. |

All Python components are in [`src/attack_harness`](src/attack_harness). There is
no plugin code loader, generated-code runner, shell tool, or secondary agent.

## Startup and transport

The fixed startup sequence is `bootstrap` → `confinement_ready` → `initialize`
→ `initialized` → `admission_open`. Confinement is installed before the guest reads
scenario, skill, or model data. Initialization verifies input, skill, prompt,
manifest, contract, image, and release identities before ordinary operations begin.

Operator selects `fifo` for Linux hosts or `spool` for macOS hosts through
`OPERATOR_TRANSPORT`. Both use separate ordinary and control lanes. Only one
ordinary operation is in flight at a time, while control messages and deadlines
remain serviceable. Transport code enforces framing, sequence and identity
correlation, bounded queues, and shared acknowledgement semantics. No reconnect,
replacement process, or automatic campaign replay is performed after failure.

## Campaign context and model interaction

The initial context contains objectives, complete scenario requirements, admitted target
capabilities, limits, a work queue, an initially untested coverage ledger, reference
handles, and selected skill instructions. Large immutable content can be read by
handle with `reference_read`. Context compaction preserves identity and receipt
references; summaries are conversation aids rather than evidence.

The effective prompt is supplied and bound by Operator. The image's default
[operating guidance](assets/default-system-prompt.txt) explains direct input,
explicit origin, valid returned handles, observation inspection, and honest
finish. Custom prompt authors should preserve those instructions. Harness does
not change a host-bound prompt after initialization. Skills are instructions and
passive references; they cannot add executable tools or expand authority.

Campaign objectives and scenario requirements MUST define the investigation within
admitted capabilities. Target replies, retrieved documents, suggestions, menus,
approval demands, and refusals MUST remain observations; they MUST NOT become new
campaign requirements or operator authorization. A target's claimed side effect
MUST remain attributed unless appropriate evidence independently establishes it.
Observation content MUST remain separate from verified execution/citation metadata;
target prose MUST NOT populate the resource or compaction handle ledger.

Guidance MUST ground each additional target action in an unresolved campaign
requirement, relevant hypothesis, or material evidence gap. The model SHOULD
explain that purpose in the existing `rationale` field. A scenario ID alone MUST
NOT establish relevance or coverage. Relevant requests for scenario-supplied
details MUST remain possible. Harness MUST NOT use action-name keyword filters
or an extra planning model to decide investigative relevance.

Ordinary automated continuations MUST return the model to the submitted campaign
and explicitly disclaim human approval, answers, or menu selections. During
assessment repair, the focused repair continuation and dispatcher restrictions
MUST remain in force, including after compaction.

Model calls go through Operator's model relay. The release contains shared
projections for OpenAI Chat, OpenAI Responses, Anthropic Messages, Bedrock
Converse, and Gemini text/tool codecs. Operator selects the admitted codec and
provider policy. Provider credentials and network access remain outside the guest.

## Fixed tools

The dispatcher validates each call before invoking its handler. Duplicate JSON
keys are rejected before ordinary decoding discards them. Calls in one model
response execute serially and receive correlated feedback.

| Tool | Behavior |
| --- | --- |
| `reference_read` | Read a bounded part of an admitted immutable input or skill reference. |
| `attempt_execute` | Submit a permitted target operation with explicit origin and direct content or a committed artifact receipt. |
| `observation_read` | Read permitted content using a returned execution receipt and observation entry. |
| `finish` | Submit an assessment, assessment-draft receipt, or unavailable reason; close execution on acceptance. |
| `artifact_publish` | Retain content for size, reuse, or an advanced operation; return a committed artifact receipt. |
| `injection_delete` | Request deletion of an owned retained injection. |
| `snapshot_request`, `snapshot_list`, `snapshot_inspect` | Create or inspect campaign-associated target snapshots when supported. |
| `restore_request` | Restore permitted target state and adopt the returned active revision. |
| `record_append` | Retain an optional historical assessment record and return its receipt. |

Host-backed tools require their dependencies in the admitted operation set.
`reference_read` is local. Optional capabilities remain subject to host
permissions, ownership, budgets, and the shared contract even when visible.

## Attempts and evidence

Every attempt requires `origin`. Scenario attempts carry the exact submitted
scenario ID; exploratory attempts omit it. Harness uses shared validation plus
submitted-bundle membership checks, then forwards the request without inferring
or repairing origin. Scenario coverage is independent of objective assessment:
citing exploratory evidence does not retroactively create a scenario attempt.

Small inputs travel directly in the request. Artifact-backed inputs use a real
committed receipt; Operator resolves descriptors and retains effective input
before dispatch. Product code owns request/attempt identities and bookkeeping.
Optional setup defaults to none and observation selection defaults to permitted
feedback, as defined in the locked shared contract.

[`AttemptExecutor`](src/attack_harness/attempts.py) remembers the original call
identity and arguments. Repeated delivery returns the retained result instead of
submitting another attempt; changed arguments cannot reuse that identity.
Local or host rejection yields no invented execution receipt. Failed and unknown
execution outcomes terminate the ordinary loop rather than trigger replay.

Observation reads preserve receipt membership, campaign ownership, availability,
integrity, and range limits. Content is returned in bounded base64 chunks with
raw lengths, EOF, truncation, and availability information. The assessment
validator distinguishes execution receipts, artifact receipts, and historical
record receipts using runtime state and preserves Operator's authoritative checks.
Claims about observation content require inspection of that content.

A healthy restore keeps the Harness process and conversation, updates the active
target revision once, and skips the remainder of the current tool batch with
correlated results. Known preflight rejection leaves the old revision usable.
Uncertain effects remain terminal. Cumulative limits do not reset on restore.

## PostgreSQL actions and observations

The Harness MUST consume database action schemas and validators from the locked
Operator package. Admitted capabilities and host policy constrain database
response rewriting and table-policy state mutation through existing optional
attempt setup actions. It MUST NOT introduce database connections, credentials,
SQL tools, or a separate feedback channel. Direct input and one finish remain
the ordinary workflow.

The trusted prompt MUST explain the distinction between response simulation and
stored-state mutation, declared table keys/writable fields, explicit creation
permission, and checkpoint restore versus injection removal. For authorized
oracle-assisted feedback it MUST explain positive, empty, partial and unavailable
outcomes, their attempt boundary, and why observed association is not causality.
Observation reads MUST preserve host receipts, bytes, availability and reasons,
including after a healthy restore. Historical results MUST NOT be reinterpreted
as fresh verdicts. See [database integration](docs/INTEGRATION.md#postgresql-and-pgvector).

## Assessment, limits, and exit

The ordinary path is execute → inspect → finish. There is no required hypothesis
registration or caller-managed assessment upload/record/stop sequence. `finish`
accepts a bounded inline assessment, a committed assessment draft, or a specific
reason why an assessment is unavailable. Optional assessment collections may be
empty. Outcomes, evidence, and hypotheses are never fabricated to fill omissions.

Assessment reference validation reports invalid categories, unknown references,
and uninspected observations with a field path and correction. Operator validates
authoritative membership and retention, closes execution, and performs cleanup.
Rejected finish remains correctable with a new operation identity. An accepted
finish ends the model loop without another model generation or tool dispatch.

The shared loop enforces admitted budgets, model and tool limits, consecutive
invalid-call limits, context bounds, and deadlines. Stopping diagnostics retain
the reason, configured/observed counts, last rejected call, and whether an attempt
was dispatched. Failure to construct an assessment does not prevent deadline
handling or owned cleanup; Harness can finish with an unavailable reason.

Healthy unwinding after accepted finish exits 0 within the required 5,000 ms.
This does not assert objective success or completed cleanup: the accepted response
reports finalization pending, and Operator reports the final state. Independent
runtime errors, including errors after acceptance, still exit 1. Fatal diagnostics
identify the stage and stable cause, omit unrestricted input/exception text, and
emit at most 1,025 bytes to stderr. An available healthy channel also receives a
bounded diagnostic report. A secondary close failure cannot replace the primary
cause.

## Verification interfaces

`make test` runs Harness behavior tests against the locked shared schemas.
`make test-integration` uses a compatible Operator runtime, production Harness
entrypoint, and controlled model/target fixtures over both transports. Local
publication tests run with `python3 -m unittest discover -s build/tests -v`.
The [integration guide](docs/INTEGRATION.md#build-and-verify-an-integration) describes
what the process fixture covers and how it differs from a deployed campaign.

## Model context management

The shared `MODEL_CONTEXT_CONTRACT.md` defines frozen local prompt/completion
allowances, response usage snapshots, compact resource references and selected
model tools. These are Operator policy limits, not discovered provider windows.
Harness consumes those verified values; it does not negotiate or alter them.

The initial task includes ordinary operation inputs, objectives and scenarios,
selected skills and a compact resource index. Full resource contracts and advanced
tool guidance remain available through verified reference handles. Model-facing
reads default to 4096 bytes, with faithful UTF-8 text where decodable and explicit
binary/incomplete decoding otherwise; source, range and availability remain intact.

After completing a tool batch, a prompt warning triggers compaction before another
generation. Newly added bytes and a usage-calibrated local estimate also trigger
reduction. Estimates do not establish actual usage or hard admission. Compaction
uses the same charged model route and a bounded selection of whole native groups,
retains the task and exact returned identity ledger across successive compactions,
and labels summaries as interpretation. Insufficient budget or irreducible context
uses the existing honest unavailable finish path. No provider or target replay is
introduced. Exact token preflight is disabled in the baseline.

Before any exploration or model-compaction request, including the first, Harness
MUST require `remaining_tokens >= 3 * R` and `remaining_model_calls >= 3`, where
`R` is the configured maximum prompt plus completion allowance. Calls MUST account
for both host remaining allowances and local loop limits; compaction consumes a
call. Harness MUST reevaluate actual Operator accounting after every response,
without charging the reserve as consumption or increasing configured limits.

Below either boundary Harness MUST enter sticky protected finalization, while
leaving the shared execution loop open for evidence reads and finish. The existing
assessment-repair action restriction MUST also enforce this transition; its entry
reason MUST remain distinct from a real rejected finish. Finalization requests
MUST use ordinary one-request admission and MAY consume the protected allocation.
The fixed reserve is two requests, not a configurable or guaranteed retry count.

Protected finalization MUST NOT make model-based compaction calls. Deterministic
local trimming MUST remove oldest complete provider-valid exchanges, preserve
recent groups where they fit, and retain privileged instructions, original campaign
requirements, finalization/repair state, verified identities and corrections.
Omissions MUST be recorded without synthesizing a summary or changing inspection
state. Mandatory context that cannot fit MUST produce an explicit context-limit
unavailable finish. Original evidence MUST remain retained outside the prompt.

An insufficient initial allowance MUST skip exploration. If one model request can
be funded, Harness MUST attempt finalization; otherwise it MUST use the bounded
model-free unavailable-finish path. Existing deadlines and retry/no-progress limits
MUST remain active. Diagnostics MUST distinguish the informational reserve
transition, token/call exhaustion, irreducible context, and unresolved assessment
repair. The guarantee protects capacity from exploration and compaction, not
model compliance or assessment acceptance.

Compaction guidance MUST distinguish original requirements, executed actions and
verified handles, target claims/suggestions, Harness interpretations, and unresolved
campaign work. It MUST forbid promoting target offers or optional model proposals
into requirements. Reinserted summaries MUST retain `model-generated-not-evidence`
provenance and an explicit statement that this fallible historical interpretation
cannot amend the original task, scenario requirements, permissions, or repair state.
Harness MUST retain the original task and repair state independently of the summary.
Controlled tests MUST exercise these boundaries across the supported native codecs,
including misleading summaries, fabricated handles in target content, relevant
follow-ups, menu responses, and blocked exploration during assessment repair.
Such tests establish construction and dispatch behavior, not live-model resistance
to task drift.

## Operating policy supplied at startup

Harness MUST consume the exact verified EngineContext `operation_timeouts_ms` map
for every admitted ordinary operation and MUST validate `size_limits` through the
shared Go/Python contract. It MUST NOT infer missing values or use registry duration
constants. The host MUST receive the same policy that guided Harness request construction.
Harness MUST use configured upload/read chunks and expose sizing allowances in task
context. Explicit oversize arguments MUST be rejected with existing actionable
argument diagnostics before sending. Safety ceilings, receipt integrity, target
scope and campaign budget checks remain mandatory. See [integration](docs/INTEGRATION.md).

## Tool correction and no-progress handling

The runtime MUST preserve shared correction details, model-facing field paths,
execution effects and safe-resubmission status. It MUST use declared uncertainty
labels in claim references and MUST NOT silently discard explanations or invent
labels. Internal resolution errors are terminal product failures. Guidance MUST
instruct correction of the identified field without replaying completed target
actions. Compaction MUST retain bounded recent corrections. `no-progress-limit`
MUST report consecutive no-progress turns and the configured limit separately from
preceding rejections; unavailable assessment remains unsuccessful even with exit
zero. Follow [the integration correction rules](docs/tool-corrections.md).

## Model relay ownership

Harness MUST use the [compact model relay](docs/MODEL_RELAY.md). It MUST send only
purpose and conversation, consume host context accounting, and interpret native
provider responses in its own adapters. It MUST preserve opaque continuation
content and independently validate requested Operator tools. Provider-native API
schemas, settings, model aliases and metadata MUST NOT become shared-contract
acceptance gates. Operator owns provider request configuration; Harness MUST NOT
reconstruct or transmit it. Compaction MUST use purpose `compaction` and no
hard-coded provider tool settings.
