# Integrating Attack Harness v0.1.1

Attack Harness runs as an Operator-managed container guest. Operator owns model
and target access, campaign admission, execution, evidence retention, and cleanup.
Harness consumes the shared contract below and supplies its adaptive model loop.
There is no standalone Harness service or user-facing command-line interface.

## Locked contract and runtime

The release consumes Operator shared contract **0.2.1**, pinned in
[`build/contract-lock.json`](../build/contract-lock.json). A matching version string
alone is insufficient: both products validate the exact package digest.

| Identity | Locked value |
| --- | --- |
| Shared package version | `0.2.1` |
| Shared package digest | `sha256:6ecefb5354a4fe2d1baf591bace2fb8457d87106f6a8f99ebc9c9abede4a98d9` |
| Contract source commit | `754b7119f49850727c6df506f050eae11d7af915` |
| Contract source tree | `0a13cb86dde4ae2605a9f3ce0d17638cc3f500c3` |
| Integration/inspection Operator commit | `d9255aeba9618bd53f4c3344e6f1c4284e99a353` |
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

- [Shared protocol and startup](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/SHARED_CONTRACT.md)
- [Attempt execution and permitted feedback](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/FEEDBACK_CONTRACT.md)
- [Objectives and scenarios](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Embedded image compatibility](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/ENGINE_RELEASE_CONTRACT.md)
- [Schemas, semantic rules, and fixtures](https://github.com/intrusiveai/operator_sandbox/tree/754b7119f49850727c6df506f050eae11d7af915/schemas)
- [Shared Python validators and provider projections](https://github.com/intrusiveai/operator_sandbox/tree/754b7119f49850727c6df506f050eae11d7af915/contracts/python)

These sources and the checked-in locks govern field names, validation, defaults,
and limits. Do not substitute a floating branch, recreate a local schema, or
silently fall back to an older protocol.

## Install and select the image

1. Install Operator and configure its model provider and target according to
   [Operator's guide](https://github.com/intrusiveai/operator_sandbox/blob/d9255aeba9618bd53f4c3344e6f1c4284e99a353/README.md).
2. Pull `ghcr.io/intrusiveai/attack_harness:v0.1.1` into the Docker daemon used by
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
