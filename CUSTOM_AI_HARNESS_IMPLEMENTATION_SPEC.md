# Attack Harness runtime

Attack Harness v0.1.0 is a single Python process inside an Operator-managed
container. It reads campaign objectives and scenarios, asks a model to choose
permitted experiments, inspects feedback, and submits an assessment. Operator
owns external effects, authorization, durable evidence, and cleanup.

The exact shared package, matching runtime, and model-tool examples are documented
in [the integration guide](docs/INTEGRATION.md). The image layout and confinement
boundary are documented in [the container specification](GUEST_ARTIFACT_LAYOUT_SPEC.md).

## Contract ownership

The Harness loads Operator's shared contract package **0.2.1** from the image and
validates its exact digest against [the contract lock](build/contract-lock.json).
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

The initial context contains objectives, a scenario index, admitted target
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
`make test-integration` uses the pinned Operator runtime, production Harness
entrypoint, and controlled model/target fixtures over both transports. Local
publication tests run with `python3 -m unittest discover -s build/tests -v`.
The [integration guide](docs/INTEGRATION.md#build-and-verify-an-integration) describes
what the process fixture covers and how it differs from a deployed campaign.
