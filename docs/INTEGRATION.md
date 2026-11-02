# Integrating Attack Harness v0.1.4

Attack Harness runs as an Operator-managed container guest. Operator owns model
and target access, campaign admission, execution, evidence retention, and cleanup.
Harness consumes the shared contract below and supplies its adaptive model loop.
There is no standalone Harness service or user-facing command-line interface.

## Locked contract and runtime

The release consumes Operator shared contract **0.5.0**, pinned in
[`build/contract-lock.json`](../build/contract-lock.json). A matching version string
alone is insufficient: both products validate the exact package digest.

| Identity | Locked value |
| --- | --- |
| Shared package version | `0.5.0` |
| Shared package digest | `sha256:9db8d03e9d759eba0c002444c9c96dbbe77991d47f97e2e9fd1b4b182bec74c3` |
| Contract source commit | `485042787cc75e1776acaac11023ba9d210cc1f3` |
| Contract source tree | `992210e4d42f3aa30a1ea740ccb16f88941a250a` |
| Integration/inspection Operator commit | `485042787cc75e1776acaac11023ba9d210cc1f3` |
| Minimum Operator product version | `0.1.0` |
| Runtime profile | `operator-container/v1` |
| Image platforms | `linux/amd64`, `linux/arm64` |

The integration and inspection revision is pinned independently in
[`build/operator-runtime-commit.txt`](../build/operator-runtime-commit.txt). Its
shared contracts and schemas match the package source. CI checkout, local
integration, and publication's inspection check use this same runtime pin.
The minimum product version does not replace exact contract matching.

The [release catalog](https://releases.intrusive.ai/docs/releases/attack_harness.json)
records `contract_package_version` from the published images. The releases site's
**Shared contract** indicator helps select matching Operator and Harness packages;
admission still checks the exact embedded package identity.

Operator's immutable source defines the integration interface:

- [Shared protocol and startup](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/schemas/SHARED_CONTRACT.md)
- [Attempt execution and permitted feedback](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/schemas/FEEDBACK_CONTRACT.md)
- [Objectives and scenarios](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Embedded image compatibility](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/schemas/ENGINE_RELEASE_CONTRACT.md)
- [Schemas, semantic rules, and fixtures](https://github.com/intrusiveai/operator_sandbox/tree/485042787cc75e1776acaac11023ba9d210cc1f3/schemas)
- [Shared Python validators and provider projections](https://github.com/intrusiveai/operator_sandbox/tree/485042787cc75e1776acaac11023ba9d210cc1f3/contracts/python)

These sources and the checked-in locks govern field names, validation, defaults,
and limits. Do not substitute a floating branch, recreate a local schema, or
silently fall back to an older protocol.

## Install and select the image

1. Install Operator and configure its model provider and target according to
   [Operator's guide](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/README.md).
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
  "input": {
    "encoding": "json",
    "value": {
      "prompt": "Reply exactly QA_CONFIG_OK. Do not call tools."
    }
  }
}
```

The scenario and operation must exist in the admitted campaign. The Harness
validates and forwards the selection unchanged; it never infers the only scenario.
Linking an exploratory receipt to an objective at finish does not change origin.

Input is exactly one direct content value or a committed artifact receipt.
Direct content supports the shared JSON, UTF-8, and base64 encodings, with a
host-configured `size_limits.direct_input_bytes` allowance and JSON depth limit of 16; the attempt request is
bounded to the 4 MiB ordinary frame. Target-specific limits also apply. Use `artifact_publish`
for larger or reusable content, then use its returned receipt. Operator resolves
artifact descriptors; the model does not repeat hashes, sizes, or canonicalization
metadata. Product code assigns execution bookkeeping and binding identities.

Omitted setup actions mean none. Omitted observation selection uses all permitted
feedback. A supplied parent execution receipt expresses a follow-up experiment;
Operator derives the corresponding bookkeeping. Defaults never repair an invalid
supplied value.

## Evidence and references

Use the returned execution receipt and observation entry ID with
`observation_read`. Reads enforce campaign membership, permitted visibility,
availability, integrity, and bounds. Responses distinguish empty output,
unavailable content, and truncation. Inspect content before making claims about it.

| Reference | Source and meaning |
| --- | --- |
| Tool call/submission ID | Correlates a submitted call; does not prove execution. |
| Execution receipt | Returned by Operator for an attempt; carries the authoritative execution disposition. |
| Artifact receipt | Returned after successful artifact publication; identifies retained content and its purpose. |
| Assessment-record receipt | Returned by accepted `record_append`; identifies an optional historical assessment record. |

These categories are not interchangeable. A rejected submission has no execution
receipt. Receipt validity is determined from runtime state and authoritative host
records, not from a prefix. When an optional evidence range is supplied, both
offset and length are required; omitting the range references the whole entry.

## Finish and final state

Call `finish` once with a finish reason and exactly one of an inline assessment,
a committed assessment-draft receipt, or a specific unavailable reason. The
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
  policy; `key` is a JSON object encoded as a string, for example
  `"{\"id\":\"one\"}"`. Include exactly its non-null scalar key columns.
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
and its [PostgreSQL guide](https://github.com/intrusiveai/operator_sandbox/blob/485042787cc75e1776acaac11023ba9d210cc1f3/docs/POSTGRESQL.md#local-integration-verification).
It runs this Harness's production Python entrypoint over spool against real local
Interceptor/PostgreSQL with deterministic model responses, then checks response
and state injection, live oracle inspection, snapshot restore, accepted finish,
process exit, cleanup and exported evidence. This is local integration coverage,
not paid-provider or Harness-container qualification.

## Build and verify an integration

Use the [development commands](../README.md#development) to build the locked
package and images. Run integration tests with the separately pinned runtime:

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

Matching Operator and Harness builds require shared package 0.5.0 and its exact
locked digest. Old packages fail compatibility before campaign execution.
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
