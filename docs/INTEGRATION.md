# Integrating Attack Harness v0.1.4

Attack Harness runs as an Operator-managed container guest. Operator owns model
and target access, campaign admission, execution, evidence retention, and cleanup.
Harness consumes the shared contract below and supplies its adaptive model loop.
There is no standalone Harness service or user-facing command-line interface.

## Locked contract and runtime

The release consumes Operator shared contract **0.7.1**, pinned in
[`build/contract-lock.json`](../build/contract-lock.json). A matching version string
alone is insufficient: both products validate SHA-256 of the exact `schemas/asyncapi.json` bytes,
including formatting and the final newline.

| Identity | Locked value |
| --- | --- |
| Shared package version | `0.7.1` |
| Shared package digest | `sha256:5f1f545701e68d057592f892c573667391df844008ec385f5cdcfbdb42e63e88` |
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

- [Shared protocol and startup](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas/SHARED_CONTRACT.md)
- [Attempt execution and permitted feedback](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas/FEEDBACK_CONTRACT.md)
- [Objectives and scenarios](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Embedded image compatibility](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas/ENGINE_RELEASE_CONTRACT.md)
- [Schemas, semantic rules, and fixtures](https://github.com/intrusiveai/operator_sandbox/tree/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas)
- [Shared Python validators and provider projections](https://github.com/intrusiveai/operator_sandbox/tree/aa2cec69c063136377cd0b807bd1116f8ffb484c/contracts/python)

These sources and the checked-in locks govern field names, validation, defaults,
and limits. Do not substitute a floating branch, recreate a local schema, or
silently fall back to an older protocol.

## Install and select the image

1. Install Operator and configure its model provider and target according to
   [Operator's guide](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/README.md).
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

Harness includes complete scenario objects, bundle completion guidance, and
evidence limitations in the initial task message when they fit its 768 KiB task
budget. Supplied content stays in user/task data and cannot override system
instructions or admitted capabilities. The portfolio derives scenario IDs and
counts from the submitted bundle, independently of the number of invocations.

For larger bundles, Harness retains complete campaign requirements and one active
scenario, deferring skill and target details to the existing reference reader.
The task lists local scenario read handles: `reference_read` loads the selected
scenario's complete requirements into the next task message, even if the requested
read returns only a small chunk. These handles are views of verified bundle data,
not execution or artifact receipts. As a backstop, an attempt call selecting an
unloaded scenario is withheld before target dispatch. Harness
loads that scenario in full, then requires a new model turn to read it and
reconstruct the call; other calls in the same response cannot bypass this boundary.
Context switches consume the existing tool, model-turn, and read budgets. The
complete active instructions survive history compaction. If they cannot fit with
required campaign context, `scenario_context_limit` reports the failure without
reducing requirements to a hypothesis or executing the call.

The model uses three tools: `attempt_execute`, `observation_read`, and `finish`.
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
are native objects; Harness uses shared normalization for the host encoding.
`record_append` uses `kind` and flat kind-specific fields. Snapshot inspection and
restore use `snapshot`; deletion uses `injection`; reads use `reference` or
`observation`. Snapshot creation keeps optional `label` and `description`.
See the exact shared
[tool normalization contract](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/schemas/MODEL_TOOL_NORMALIZATION.md)
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
and its [PostgreSQL guide](https://github.com/intrusiveai/operator_sandbox/blob/aa2cec69c063136377cd0b807bd1116f8ffb484c/docs/POSTGRESQL.md#local-integration-verification).
It runs this Harness's production Python entrypoint over spool against real local
Interceptor/PostgreSQL with deterministic model responses, then checks response
and state injection, live oracle inspection, snapshot restore, accepted finish,
process exit, cleanup and exported evidence. This is local integration coverage,
not paid-provider or Harness-container qualification.

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
within a test process; campaign state stays isolated.

This runs the production Python entrypoint against Operator's Go service over
FIFO and spool with controlled model responses and local targets. The fixture
relocates guest paths and uses a confinement shim; image inspection and actual
container campaigns exercise different boundaries. Use the same contract and
image identities when running a deployed integration through Operator.

## Context behavior

Matching Operator and Harness builds require shared package 0.7.1 and its exact
locked digest. Mismatched interface versions or byte hashes fail before campaign execution;
implementation-only Operator changes do not require a Harness identity update.
Frozen injection surfaces select the same tools in Go and Python; restores keep
that catalog. Context budget results are validated against native response usage.

Controlled FIFO/spool process tests cover resource reads, warning-triggered
compaction, follow-up scenario execution, finish and retained report/export facts.
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
length. Harness includes those limits in model task context and validates requests
against the shared implementation before sending them. Artifact publication and
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

Task context includes Operator's shared pagination guidance and minimal inline
finish example, with a submitted objective ID. Use execution handles in `attempts`,
inspected citation handles in supported assessment entries' `observations`, and
accepted historical-record handles in `records`. Optional elaboration is separate.
Malformed entries and wrong categories receive shared field paths and corrections;
correcting a finish does not re-execute target operations. Finish acceptance closes
execution and requires exit; Operator confirms cleanup afterward.

Harness asks the model to finalize when remaining tokens or turns approach three
current request reservations, preserving space for an assessment request and one
correction where possible. Every model request, including compaction, still needs
funding. This is best effort; it does not guarantee a valid assessment. If admission
cannot reserve another request, Harness sends `model_reservation_unavailable` with
allowance, confirmed consumption, remaining tokens and next-request reservation.
Earlier recoverable tool errors remain separate history. No assessment is invented:
the bounded model-free unavailable finish exits normally but remains unsuccessful.

The controlled process suite covers partial-read continuation, rejected unread
citations, corrected finish without replay, and both 524288-token budget cases
(493460 consumed / 30828 remaining; 502198 / 22090; reservation 36864). It checks
Operator inspection, reports and exported events, accepted assessment, exit zero
and confirmed cleanup. These tests exercise production Harness processes with
controlled model responses; they are not live-cloud qualification.

See [tool corrections](tool-corrections.md) for schema-rule references, correction preservation and no-progress stopping. The approved contract lock is authoritative for the version and exact document-byte hash.
