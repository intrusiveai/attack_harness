# Integrating Attack Harness v0.1.4

Attack Harness runs as an Operator-managed container guest. Operator owns model
and target access, campaign admission, execution, evidence retention, and cleanup.
Harness consumes the shared contract below and supplies its adaptive model loop.
There is no standalone Harness service or user-facing command-line interface.

## Locked contract and runtime

The release consumes the Operator shared contract identified in
[`build/contract-lock.json`](../build/contract-lock.json). A matching version string
alone is insufficient: both products validate SHA-256 of the exact `schemas/asyncapi.json` bytes,
including formatting and the final newline.

| Identity | Locked value |
| --- | --- |
| Shared package version | `package.package_version` in [the contract lock](../build/contract-lock.json) |
| Shared package digest | `package.package_digest` in [the contract lock](../build/contract-lock.json) |
| Runtime profile | `operator-container/v1` |
| Image platforms | `linux/amd64`, `linux/arm64` |

Compatibility depends on this version/hash pair, not an Operator product version,
source commit, validator-source hash, or whole-source-tree comparison. Implementation
changes that retain these exact interface bytes remain compatible. The separate
`operator.dev/contract-package/v2` distribution manifest verifies inventory bytes,
paths and schema/registry projections; its hash is not the compatibility identity.

[`build/operator-runtime-commit.txt`](../build/operator-runtime-commit.txt) selects
reproducible integration-test provenance for CI. Local tests may use another
implementation of the approved interface. Documentation links below identify the
reviewed definitions and validators, not an admission requirement on that commit.

The [release catalog](https://releases.intrusive.ai/docs/releases/attack_harness.json)
records `contract_package_version` from the published images. The releases site's
**Shared contract** indicator helps select matching Operator and Harness packages;
admission still checks the exact embedded package identity.

Operator's immutable source defines the integration interface:

- [Shared protocol and startup](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas/SHARED_CONTRACT.md)
- [Attempt execution and permitted feedback](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas/FEEDBACK_CONTRACT.md)
- [Objectives and scenarios](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Embedded image compatibility](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas/ENGINE_RELEASE_CONTRACT.md)
- [Schemas, semantic rules, and fixtures](https://github.com/intrusiveai/operator_sandbox/tree/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas)
- [Shared Python validators and provider projections](https://github.com/intrusiveai/operator_sandbox/tree/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/contracts/python)

These sources and the checked-in locks govern field names, validation, defaults,
and limits. Do not substitute a floating branch, recreate a local schema, or
silently fall back to an older protocol.

## Install and select the image

1. Install Operator and configure its model provider and target according to
   [Operator's guide](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/README.md).
2. Pull `ghcr.io/intrusiveai/attack_harness:v0.1.4` into the Docker daemon used by
   Operator. For an immutable deployment, use the image index digest recorded in
   the GitHub release or release catalog.
3. Set Operator's `engine.image` to that locally available image. Use an Operator
   build with the exact shared package identity above.
4. Submit the objectives, optional scenarios, and selected skills through Operator.
   Operator validates compatibility and prepares the guest before admission.
5. Inspect campaign state, evidence, and reports through Operator. A completed
   target operation, accepted assessment, and completed cleanup are distinct facts.

Operator reads `/opt/operator/engine/share/compatibility.json` from the image.
Admission does not query an external compatibility service. The image and runtime
layout are documented in [the container specification](../GUEST_ARTIFACT_LAYOUT_SPEC.md).

## Ordinary execution

Harness starts with campaign-wide objectives, constraints, bundle completion
guidance, evidence limitations, and a compact index of every scenario. The index
contains IDs, short descriptions, priority, required status, objective associations,
and exact selection handles; it is not a replacement for scenario instructions.
Campaign sequencing requirements remain visible independently of priority. Supplied
content stays in user/task data and cannot override system instructions or admitted
capabilities. The scenario index derives its IDs from the submitted bundle,
independently of the number of invocations.

The submitted objectives and scenario requirements define the investigation within
admitted capabilities. Target replies and retrieved documents are observations;
their offers, menus, approval demands, and refusals do not authorize new work.
For example, providing an order ID requested by the target can advance a scenario
that supplied that ID. An offer to create a ticket or notify a team is relevant
only if it independently serves an authorized campaign requirement. The model
is guided to explain additional experiments in `rationale`; a scenario ID alone
does not establish relevance or coverage. Target claims of side effects retain
their attribution unless appropriate evidence verifies those effects.

Automated continuations explicitly return the model to the submitted campaign;
they are not human answers, approvals, or menu selections. Context checkpoints
retain original requirements and verified execution facts separately from target
content. They do not generate a model summary or turn target suggestions into
requirements. Any explicitly supplied summary remains fallible history that cannot
amend requirements, permissions, or assessment-repair state. Controlled tests verify these boundaries
and repair dispatch restrictions across native conversation formats; they do not
prove that a live model will always resist task drift.

For every bundle size, `reference_read` with a `scenario_index` reference handle and
offset zero activates the complete scenario. The request delivering its confirmation
already contains those instructions in `active_scenario`; no acknowledgment is required. The tool
returns a short selection confirmation, not a second copy or a paginated chunk;
`max_bytes` does not truncate scenario instructions. Switching starts a fresh
model conversation containing the new active section, after the current tool batch
is resolved. Earlier native messages and thinking blocks are not carried into it. The original verified bundle is unchanged and remains readable through
its original handle, but is not another required read. Other references retain
normal byte-range reading. Selecting the next scenario can share a response with
independent reads of existing observations; execution waits for the next turn.

Beside the active instructions, `active_scenario_activity` shows a compact
record of associated target attempts, snapshot creation, restores and injection
deletions. Entries show the operation and returned status, relevant handles and
which evidence was inspected or remains visible. When supplied, `requested_purpose`
is the caller's short stated rationale, not a verified result. Inputs and evidence
bodies stay outside this tracker. A completed invocation does not establish that
a scenario requirement was satisfied; withheld or rejected associated attempts
are shown as not executed.

The record is a snapshot at the start of the conversation. Subsequent tool results
provide incremental updates; Harness never edits the original message to refresh
it. Switching scenarios starts a new snapshot for the selected scenario, initially
empty if no actions exist. Revisiting a scenario restores its retained activity. Earlier evidence remains available for
the final assessment, even after history reduction. Exploratory attempts are not
assigned to the loaded scenario, and unvalidated submissions retain their normal
corrections rather than receiving an inferred scenario association.

An attempt for an unloaded scenario is withheld before target dispatch. Harness
loads its complete requirements and requires another model turn to reconstruct
the attempt. Selection and execution in one response cannot bypass this boundary.
Context switches consume existing tool, model-turn, and read allowances. If full
active requirements cannot fit alongside campaign context within the 768 KiB task
limit, `scenario_context_limit` reports the failure without truncating requirements
or executing the call. Native prompt limits and protected finalization still apply.

The index remains visible during finalization. Product-owned facts distinguish
instructions delivered from completed executions, and associate scenario IDs,
execution status, observations, inspected citations, snapshots, and restore
lineage. Entering protected finalization or assessment repair starts a campaign-wide
checkpoint containing activity from all scenarios, including unvisited scenarios.
These records do not assert objective success. Context renewal omits old native
exchanges, never retained evidence; a citation may stay valid while
its content is absent from the current prompt. Revisit individual scenario
requirements and reread evidence as needed for the assessment. Unvisited scenarios
and unresolved findings must be reported honestly. Scenario selection remains
available during assessment repair; new target actions remain blocked.

After scenario selection, ordinary execution uses three tools: `attempt_execute`, `observation_read`, and `finish`.
Operator retains effective input before dispatch and returns authoritative
execution receipts and permitted observation entries. If retention fails, it
does not dispatch the target operation.

Every attempt explicitly selects its origin:

- `origin: "scenario"` requires the exact ID of a scenario in the submitted bundle.
- `origin: "exploratory"` forbids `scenario_id` and represents authorized work
  outside a supplied scenario. It does not establish scenario coverage.

For a target whose `invoke` operation accepts this JSON input:

```json
{
  "origin": "scenario",
  "scenario_id": "configuration",
  "operation_id": "invoke",
  "json": {"prompt": "Reply exactly QA_CONFIG_OK. Do not call tools."}
}
```

The scenario and operation must exist in the admitted campaign. The Harness
validates and forwards the selection unchanged; it never infers the only scenario.
Linking an exploratory receipt to an objective at finish does not change origin.

Input is exactly one of `json`, `text`, `base64`, or `artifact` (a returned handle).
Direct content supports the shared JSON, UTF-8, and base64 encodings, with a
host-configured `size_limits.direct_input_bytes` allowance and JSON depth limit of 16; the attempt request is
bounded to the 4 MiB ordinary frame. Target-specific limits also apply. Use `artifact_publish`
for larger or reusable content, then use its returned `artifact` handle. Operator resolves
artifact descriptors; the model does not repeat hashes, sizes, or canonicalization
metadata. Product code assigns execution bookkeeping and binding identities.

Omitted setup actions mean none. Omitted observation selection uses all permitted
feedback. A supplied `parent` execution handle expresses a follow-up experiment;
Operator derives the corresponding bookkeeping. Defaults never repair an invalid
supplied value.

## Evidence and references

Use `observation_read` with the returned observation handle:

```json
{"observation": "observation-1"}
```

Omitted offset means zero; omitted size uses the bounded shared default. Reads
preserve campaign membership, visibility, availability, integrity and range
checks. A partial read returns `citation` for precisely the inspected range and
`readable_observation` for further reads. Follow the returned `continuation`
request; it stays inside the original handle's permitted range. Listing a handle is not inspection.
Unavailable content and truncation remain explicit.

Harness keeps a typed handle map in campaign memory, outside the model context.
Execution, observation, artifact, historical-record, hypothesis, injection and
checkpoint handles are distinct. Rejected submissions have no execution handle.
Handles resolve only through verified runtime state, never identifier prefixes or
model prose. Canonical receipts remain in Operator evidence. Compaction preserves
returned handles; after a healthy restore, Operator revalidates injection cleanup
against the current target binding while Harness retains
immutable historical evidence.

## Finish and final state

Call `finish` once with root `finish_reason`, `summary`, and `objectives` fields.
There is no nested `assessment` wrapper. For example, after inspecting the returned
observation (using the actual objective ID and handle):

```json
{
  "finish_reason": "objectives-addressed",
  "summary": "The requested marker appeared.",
  "objectives": [{
    "objective_id": "configuration-check",
    "outcome": "supported",
    "summary": "Observed the expected response.",
    "observations": ["observation-1"]
  }]
}
```

Harness expands observation handles and derives the corresponding execution
receipt lists. The model does not repeat those receipts or assign claim/gap IDs.
Optional hypothesis and uncertainty labels are only needed for cross-references.
Normalization is supplied by the exact shared contract. Before submission,
Harness retains observation selections for objectives, hypotheses and coverage
through bounded diagnostic batches; retention failure prevents submission.

Alternatively, supply `finish_reason` with a committed conclusion `artifact`
handle or an explicit `unavailable_reason`, excluding inline assessment fields. The
ordinary assessment contains a summary and objective outcomes; hypotheses,
claims, historical records, and other optional collections are not prerequisites.
Local hypotheses may be defined in the assessment without registration. Unknown
references, duplicate IDs, self-parenting, and cycles remain invalid.

A campaign with no executed attempt can report an untested or inconclusive
assessment with empty evidence references. It cannot claim evidentiary success.
Operator validates and retains the assessment, closes execution, and controls
cleanup. Invalid assessments remain correctable and are not reported as accepted.

The model is instructed to evaluate scenario requirements against inspected
observations, follow up on requests for supplied details, and identify skipped
actions and unresolved effects. Invocation success does not imply scenario or
objective achievement. Missing evidence calls for partial/untested coverage and
an appropriate inconclusive, not-tested, or not-observed outcome. Reference checks
remain structural and evidence-based; Harness does not use keyword matching to
decide whether free-text requirements were satisfied.

After a correctable finish rejection, Harness enters assessment repair. It keeps
the rejected submission and precise correction, and asks the model to repair the
assessment using existing evidence. Prose or a menu of other tasks does not
resume exploration. The dispatcher permits only corrected finish submissions,
observation/input/tool-guidance reads, and conclusion-purpose artifact publication;
it rejects new target actions, injection changes, snapshots, restores, and record
appends before dispatch, including later calls in the same model response.

Repair state, original objectives, and verified handles survive compaction
independently of the model summary. Existing limits still apply. If repair cannot
finish, the unresolved correction is reported separately from the actual stopping
cause; the bounded unavailable-finish path does not imply assessment success.
An accepted finish remains the authority for closing execution. See the
[assessment-repair specification](../specs/assessment-repair.md) for the dispatch
and retention requirements.

Accepted finish reports `execution_admission: "closed"`,
`finalization_status: "pending"`, and requires exit within 5,000 ms. A healthy
Harness exits with code 0, including for an honest unsuccessful assessment.
Operator's final state establishes whether cleanup completed; acceptance alone
does not establish it. Duplicate delivery retains operation identity and must not
duplicate effects. Interrupted finalization does not trigger campaign replay.

## Optional capabilities and failure handling

`artifact_publish` takes `purpose`, `media_type` and one of `json`, `text`, or
`base64`. `attempt_execute.setup` contains selector/placement decisions but no
action ID/type wrapper; `injection` carries its content choice. Database row keys
are native objects; existing state-collection record keys are strings. Harness
uses shared normalization for the host encoding and keeps database key policies
in verified runtime context.
`record_append` uses `kind` and flat kind-specific fields. Snapshot inspection and
restore use `snapshot`; deletion uses `injection`; reads use `reference` or
`observation`. Snapshot creation keeps optional `label` and `description`.
See the exact shared
[tool normalization contract](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/schemas/MODEL_TOOL_NORMALIZATION.md)
for all fields, defaults, and handle categories.

Artifacts, retained injections and their deletion, snapshots, restores, and
historical assessment records are exposed only when the admitted operation set
supports them. Capability exposure does not depend solely on whether a scenario
mentions that capability. A successful restore updates the active revision and
skips remaining calls in that model response; healthy campaign context survives.
Uncertain effects or failure after execution closes do not cause automatic replay.

Invalid calls produce bounded errors with the field path, failed rule, correction,
source, and execution/resubmission status. Host rejection details remain
identifiable. Configured invalid-call limits, budgets, and deadlines still apply.
The Harness reports stopping diagnostics through the shared runtime channel when
available; fatal exits also emit bounded structured stderr and exit with code 1.
Cleanup failures do not replace the primary failure.

## Discovered injection targets

The compact target view includes service resources with endpoint-detail handles.
Read the selected endpoint with `reference_read` before constructing setup; the
verified detail contains its selector constraints and delivery schema. Detailed
examples are available through `tool-guide:attempt_execute`.

- `http-route-set` endpoints advertise independent exact method/path allowlists.
  Empty or omitted lists impose no endpoint restriction, but do not authorize
  arbitrary routes: Operator still requires an administrator-permitted concrete
  method/path. `HEAD` is not injectable; these paths are not templates.
- `state-collection` endpoints advertise a collection, existing string `keys`,
  and `mutable_fields`. Select an existing key and a pointer into a mutable field.
  Injection content is the selected field's JSON value; endpoint delivery schemas
  describe the complete record. Unknown keys, root replacement, immutable writes,
  and implicit record creation/deletion are not permitted.

Discovery does not grant authorization. Operator retains route, scope, placement,
ownership and budget checks. Deleting an injection does not undo an applied state
mutation; use permitted snapshot/restore operations when rollback is required.
Database table selectors continue to require their declared key-column objects.

## PostgreSQL and pgvector

Use an Interceptor environment with declared PostgreSQL services and a reviewed
application input contract. Operator's admitted capability projection supplies
services, operations, injection surfaces, table-policy IDs, keys, writable fields
and creation limits. It carries no database credentials or private oracle SQL.
The Harness invokes the application and uses the existing optional setup actions;
it does not connect to PostgreSQL or implement vector queries.

- `database_response` uses `simulation` mode. Select a permitted service and
  call ordinal/request-body predicates. Result pointers such as `/rows/0/0`
  address eligible text/JSON cells, not metadata or binary values. HTTP/MCP
  selectors do not apply. This changes the delivered result, not stored rows.
- `environment_state` uses `fidelity` mode. `collection` names the declared table
  policy; `key` is a native JSON object, for example `{"id":"one"}`. Include exactly its non-null scalar key columns.
  Field pointers must be writable. Row creation requires explicit permission,
  a record limit and authorized root replacement; it is not an implicit upsert.
- Deleting an injection removes its definition, not an already committed database
  mutation. Use a checkpoint restore to return to a saved baseline. Restore keeps
  the healthy Harness conversation and applies the normal batch-skip boundary.

These actions require admitted capabilities and Operator authorization; scenario
prose cannot grant them. Small invocation and injection inputs use direct content;
large/reusable payloads retain the existing artifact-receipt path.

With effective `oracle-assisted` feedback, the all-permitted default includes
`oracle_outcome`; explicit selection must request it. Read the returned entry
with `observation_read` before choosing the next attempt. A normalized
`database_query_match` verdict includes an opaque detector ID and `fired: true`,
not SQL, private query results or baseline contents. Black-box and diagnostic
profiles do not expose these verdicts.

A positive verdict establishes an observed condition, not injection causality.
An empty category means no positive verdict was captured, not proof of attack
failure. Unavailable/partial results, including `oracle_evaluation_unavailable`,
remain unknown; valid entries in a partial category are still readable. Old
receipt bytes remain fixed after later writes and restores. Session-wide retained
evidence may contain additional historical outcomes and must not be treated as
a fresh attempt verdict.

For the controlled native database workflow, use the matching Operator checkout
and its [PostgreSQL guide](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/docs/POSTGRESQL.md#local-integration-verification).
It runs this Harness's production Python entrypoint over spool against real local
Interceptor/PostgreSQL with deterministic model responses, then checks response
and state injection, live oracle inspection, snapshot restore, accepted finish,
process exit, cleanup and exported evidence. This is local integration coverage,
not paid-provider or Harness-container qualification.

### Target model-response injection

When admitted, `attempt_execute` also supports `setup.surface: model_response`.
This changes a successful non-streaming model response delivered to the target
application; it does not change Harness's own model response. Select the advertised
application-facing `model_codec`, use simulation mode and permitted once/standing
scope, and address placement pointers from the whole response JSON. Target input
fields remain those of the selected operation. Read `tool-guide:attempt_execute`
for the shared selector, placement and payload guidance.

Valid JSON injection content may deliberately contain malformed tool names or
argument strings. It is still subject to size, placement and authorization checks.
Streams, raw invalid JSON, embeddings and HTTP status/header mutation are not
supported. Missing pointers and incompatible placements remain unapplied outcomes.
An `applied` result establishes mutation, and `response_written` establishes bytes
written; neither proves SDK acceptance or target tool execution. Inspect permitted
observations for those outcomes. Black-box feedback does not reveal private
delivery details. See [Operator's model-response injection guide](https://github.com/intrusiveai/operator_sandbox/blob/5504e7dc7288e2629de9c34b8cea4c2391fd8e5f/docs/MODEL_RESPONSE_INJECTION.md).

## Build and verify an integration

Use the [development commands](../README.md#development) to build the verified
distribution and images. Run integration tests with a matching Operator:

```sh
make test-integration OPERATOR_ROOT=/absolute/path/to/matching-operator PYTHON=.ci-venv/bin/python
```

The default selects cross-component `TestPython*`/`TestHarness*` cases; host-only
unit/service checks run in Operator CI. For diagnostic runs of the entire host
packages, invoke `build/verify_integration.py` with `--run .` and the same required
Operator/Python arguments. Contract packaging and the inspection CLI are reused
within a test process; campaign state stays isolated. Before submitting a candidate
change, run the complete default suite: a focused `--run` expression does not cover
all inherited process fixtures. Harness-local Go overlays adapt model-conversation
expectations (current repair blocks and local history reduction) while retaining
Operator's execution, diagnostic, cleanup, report, and export checks.

This runs the production Python entrypoint against Operator's Go service over
FIFO and spool with controlled model responses and local targets. The fixture
relocates guest paths and uses a confinement shim; image inspection and actual
container campaigns exercise different boundaries. Use the same contract and
image identities when running a deployed integration through Operator.

## Context behavior

Matching Operator and Harness builds require the version and exact document hash
identified in [the contract lock](../build/contract-lock.json). Mismatched interface versions or byte hashes fail before campaign execution;
implementation-only Operator changes do not require a Harness identity update.
Frozen injection surfaces select the same tools in Go and Python; restores keep
that catalog. Context budget results are validated against native response usage.

Controlled FIFO/spool process tests cover resource reads, warning-triggered
local history reduction without an extra model call, follow-up scenario execution,
finish and retained report/export facts.
They do not qualify a live provider or native Docker containment. See Operator's
`docs/MODEL_CONTEXT_VERIFICATION.md` for measured JSON byte reductions. The baseline
has no exact token preflight. Context/budget-limit finalization remains honest when
another bounded, funded model call is impossible.

## Configured waits and sizes

Operator supplies `operation_timeouts_ms` and `size_limits` in verified EngineContext.
The timeout map has exactly one entry per admitted ordinary operation. Harness uses
that value as its default request wait; an explicit shorter wait remains possible.
There are no ordinary-operation duration constants in the registry or a separate
Harness timeout configuration. Missing startup policy is incompatible and fails
before execution. Snapshot restore preserves the frozen policy.

Operator's installation settings control direct-input bytes, assessment bytes,
whole-artifact bytes, upload-part bytes, observation-read bytes and snapshot page
length. Harness retains those limits internally and validates requests against the
shared implementation before sending them. The ordinary task omits startup limit
maps; applicable rejection and finalization notices explain current constraints. Artifact publication and
full observation reads select their chunks from the supplied limits. Local invalid
calls remain correctable and do not dispatch target execution. The host independently
checks every received request and retains the original integrity and budget checks.

A typical multi-step target uses a 60-second native target turn, a 90-second Operator
complete-attempt allowance, and a 120-second Harness wait configured by Operator.
The native turn setting belongs to the target. Setup and observations consume the
same complete-attempt budget. Smaller request/campaign deadlines still apply.
An Operator timeout response can report successful target invocation with incomplete
observations; Harness must retain that distinction, stop on a terminal result and
never retry the invocation. Its eventual exit is supporting evidence, not a reason
to replace Operator's structured timeout cause.

Transport frame, JSON depth, numeric, eager-decoding and integrity-verification
ceilings remain fixed for interoperability. Changing operating values within them
requires no release or contract change. See Operator's authoritative
[operating-limit contract](https://github.com/intrusiveai/operator_sandbox/blob/candidate-v0.1.4/schemas/OPERATING_LIMITS_CONTRACT.md)
and [configuration guide](https://github.com/intrusiveai/operator_sandbox/blob/candidate-v0.1.4/docs/HOST_CONFIGURATION.md).

## Evidence pagination and model-budget finalization

Observation reads return `readable_observation` for further reads and `citation`
for the exact inspected bytes. A partial read includes an executable `continuation`
with the original readable handle, next offset and bounded maximum length. Follow
that request unchanged. Continuation is absent at EOF, unavailability, or the end
of the handle's permitted range. Reading pages does not mark the unread whole-entry
handle inspected. Assessment references accept inspected citations only; rejection
feedback offers applicable inspected handles. Conversation compaction preserves
handle categories while the campaign resource map retains ranges and inspection state.

The shared tool guides provide pagination and minimal inline finish examples;
replace illustrative identities with submitted objective IDs and returned handles.
Use execution handles in `attempts`,
inspected citation handles in supported assessment entries' `observations`, and
accepted historical-record handles in `records`. Optional elaboration is separate.
Malformed entries and wrong categories receive shared field paths and corrections;
correcting a finish does not re-execute target operations. Finish acceptance closes
execution and requires exit; Operator confirms cleanup afterward.

Harness protects capacity for an assessment request and one correction opportunity
from exploration and model-based compaction. For the current profile, let
`R = maximum_prompt_tokens + maximum_completion_tokens`. Before the first and every
subsequent exploration or compaction request, remaining tokens must be at least
`3 × R` and at least three model calls must remain. Equality permits the request;
below either boundary, Harness permanently enters protected finalization. With
`R = 36,864`, the protected token allowance is `73,728`. This is admission policy,
not another charge against Operator's accounting; both host allowances and local
model-call limits remain in force. The adaptive loop does not purchase model-generated summaries.

Protected finalization uses the same dispatch restriction as assessment repair:
only finish, retained observation/reference reads, and conclusion-purpose artifact
publication are allowed. Budget pressure does not invent a rejected assessment.
A later real rejection retains its request and stronger repair guidance. Finalization
requests may use the protected capacity whenever the ordinary limits can fund
one request; they do not have to leave another reserve behind.

Context reduction is local during both exploration and protected finalization.
Harness starts a fresh native conversation containing original requirements,
privileged instructions, finalization/repair state, verified handles and unresolved
corrections. No old assistant, tool-call, or thinking blocks cross that boundary. It records omissions without generating a summary or
marking unread evidence inspected. Full evidence remains available from Operator.
If mandatory context cannot fit safely, Harness reports `context_limit` rather
than making an oversized model request or dropping requirements.

The task contains campaign requirements, one `scenario_index`, one complete
`active_scenario`, applicable operation input shapes, and compact `evidence` records.
The index links scenario handles with instruction-delivery and execution facts.
Evidence records retain inspection ranges, content visibility, snapshot parentage,
and restore associations; they do not assign objective outcomes. No startup budget,
internal operation inventory, capability digest, producer metadata, or general
reference inventory is repeated in the task. All remain in verified runtime/audit
state. Target schemas are preserved intact, including their real input field names.

Supporting campaign documents retain usable references. Advanced target resources
have detail handles beside their service/namespace; capabilities needed later stay
discoverable. The prompt and complete bundle are not advertised as routine reading.
`reference_read` also accepts `tool-guide:<tool_name>` for detailed arguments and
examples. These references use the existing verified lookup, not new aliases.
Stable purpose and trust rules live in the short privileged prompt; complete
scenario requirements remain task data. Independent reads can share a model response;
dependent actions wait for the earlier results.

Successful invocation feedback presents execution and observation handles plus
relevant evidence limitations. Failed or uncertain outcomes retain stage, effect,
and retry distinctions. An empty oracle category means no positive verdict was
returned, not proof of either attack success or failure. Complete JSON observations
are displayed as JSON values with source/assurance metadata. Their original bytes,
byte counts, citations and readable ranges remain unchanged. Partial, binary, or
ambiguous JSON (including duplicate keys) remains text/base64; nested target fields
are never removed or interpreted as Harness handles. All original evidence remains
available for rereading. The shared native tool declarations and validation remain
authoritative, independent of this presentation.

Within each conversation, messages are append-only. Tool feedback and automated
continuations are appended; activity changes never rewrite earlier task messages.
A local invariant detects accidental prefix or model-policy changes before another
request. Native reasoning and signatures stay unchanged with the prefix that
produced them. Scenario changes, context reduction and entry into finalization or
repair start fresh conversations without old native reasoning or continuation IDs.
Checkpoints wait for the complete current tool batch; they do not replay operations,
reset counters, change accounting, or imply a scenario completed successfully.

At the context warning threshold, the same checkpoint path renews the conversation.
It may carry up to four complete recent verified evidence/reference envelopes,
within an 8 KiB combined limit, as attributed task data. These optional pages are
removed oldest-first if needed for headroom. A page is never truncated while
retaining its whole-page citation. All other content remains rereadable. Checkpoints
record omissions and distinguish previously inspected evidence from bytes actually
included. Current tool results supply subsequent progress. Target prose never
supplies handles or permissions. Full request/response records and original evidence
are not rewritten. Estimates do not lower reservations; Operator remains the
request-validation and accounting authority. Irreducible mandatory context produces
an honest context-limit termination.

During repair, the new checkpoint includes the exact rejected submission (including
duplicate JSON keys) and its correction. Later rejections are appended as native
feedback. Any subsequent checkpoint reinstates the latest rejection from retained
state; it is never reconstructed from a model summary. The dispatcher continues
to prevent new target actions. A campaign-wide assessment can selectively revisit
requirements and observations from earlier scenarios; it need not reload every
scenario or observation. An ordinary accepted finish is not delayed for another
assessment request. Finish acceptance and confirmed cleanup remain distinct.

This guarantees that exploration and compaction cannot consume the protected
allocation. It does not guarantee two valid finish submissions or assessment
acceptance: necessary reads, prose-only replies, invalid calls, deadlines, and
other failures can still prevent completion. An initially underfunded campaign
skips exploration and uses its actual remaining allowance for an honest assessment.
If no request can be funded, the bounded model-free unavailable finish remains
unsuccessful even when Harness exits zero.

The matching Operator diagnostics retain `finalization_capacity_protected` as an
informational transition, separately from `model_call_limit`, `context_limit`, and
`finish_repair_unresolved`. Actual token exhaustion retains the structured
`model_reservation_unavailable` allowance, consumption, remaining tokens and
reservation. Earlier recoverable tool errors remain separate history. No assessment
is invented and no target action is replayed.

The controlled process suite covers partial-read continuation, rejected unread
citations, corrected finish without replay, and both 524288-token budget cases
(493460 consumed / 30828 remaining; 502198 / 22090; reservation 36864). It checks
Operator inspection, reports and exported events, accepted assessment, exit zero
and confirmed cleanup. These tests exercise production Harness processes with
controlled model responses; they are not live-cloud qualification.

See [tool corrections](tool-corrections.md) for schema-rule references, correction preservation and no-progress stopping. The approved contract lock is authoritative for the version and exact document-byte hash.

## Model relay

Use the [model conversation relay](MODEL_RELAY.md). Operator owns provider
configuration and adds the frozen prompt and tools. Harness sends only purpose
and native conversation history, then interprets the returned native response
using Operator's validated accounting. Provider metadata is not a shared-schema
compatibility gate. The direct-input, evidence-read, and single-finish workflow,
assessment repair, and budget/no-progress diagnostics remain unchanged.
