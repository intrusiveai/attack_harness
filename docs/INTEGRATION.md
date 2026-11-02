# Integrating Attack Harness v0.1.4

Attack Harness runs as an Operator-managed container guest. Operator owns model
and target access, campaign admission, execution, evidence retention, and cleanup.
Harness consumes the shared contract below and supplies its adaptive model loop.
There is no standalone Harness service or user-facing command-line interface.

## Locked contract and runtime

The release consumes Operator shared contract **0.4.0**, pinned in
[`build/contract-lock.json`](../build/contract-lock.json). A matching version string
alone is insufficient: both products validate the exact package digest.

| Identity | Locked value |
| --- | --- |
| Shared package version | `0.4.0` |
| Shared package digest | `sha256:9c50335bda8b5442cae3e11b60319d9f41e5d626032096161cda985add909bfe` |
| Contract source commit | `f84ccf374b859af66a32201a0f953dd9e3a3fc3c` |
| Contract source tree | `b32b619335764feb2ada1c7b3e2cca3d3b311b9d` |
| Integration/inspection Operator commit | `f84ccf374b859af66a32201a0f953dd9e3a3fc3c` |
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

- [Shared protocol and startup](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/schemas/SHARED_CONTRACT.md)
- [Attempt execution and permitted feedback](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/schemas/FEEDBACK_CONTRACT.md)
- [Objectives and scenarios](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Embedded image compatibility](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/schemas/ENGINE_RELEASE_CONTRACT.md)
- [Schemas, semantic rules, and fixtures](https://github.com/intrusiveai/operator_sandbox/tree/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/schemas)
- [Shared Python validators and provider projections](https://github.com/intrusiveai/operator_sandbox/tree/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/contracts/python)

These sources and the checked-in locks govern field names, validation, defaults,
and limits. Do not substitute a floating branch, recreate a local schema, or
silently fall back to an older protocol.

## Install and select the image

1. Install Operator and configure its model provider and target according to
   [Operator's guide](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/README.md).
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
32,768-byte decoded limit and JSON depth limit of 16; the attempt request is
bounded to 64 KiB. Target-specific limits also apply. Use `artifact_publish`
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
and its [PostgreSQL guide](https://github.com/intrusiveai/operator_sandbox/blob/f84ccf374b859af66a32201a0f953dd9e3a3fc3c/docs/POSTGRESQL.md#local-integration-verification).
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

This runs the production Python entrypoint against Operator's Go service over
FIFO and spool with controlled model responses and local targets. The fixture
relocates guest paths and uses a confinement shim; image inspection and actual
container campaigns exercise different boundaries. Use the same contract and
image identities when running a deployed integration through Operator.

## Context behavior

Matching Operator and Harness builds require shared package 0.4.0 and its exact
locked digest. Old packages fail compatibility before campaign execution.
Frozen injection surfaces select the same tools in Go and Python; restores keep
that catalog. Context budget results are validated against native response usage.

Controlled FIFO/spool process tests cover resource reads, warning-triggered
compaction, follow-up scenario execution, finish and retained report/export facts.
They do not qualify a live provider or native Docker containment. See Operator's
`docs/MODEL_CONTEXT_VERIFICATION.md` for measured JSON byte reductions. The baseline
has no exact token preflight. Context/budget-limit finalization remains honest when
another bounded, funded model call is impossible.
