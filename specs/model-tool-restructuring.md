# Model tool restructuring

## Outcome and scope

Attack Harness MUST let the model execute a permitted input, inspect the returned
evidence, and finish with an honest assessment without assembling receipt pairs,
repeating derived receipt lists, or constructing protocol envelopes. The ordinary
workflow MUST remain `attempt_execute` → `observation_read` → `finish`. Additional
executions and reads remain necessary when the experiment requires them.

This specification covers all 11 existing model-facing tools. It defines a
coordinated contract change, not a second interface implemented independently in
Harness. It retains the current transport, execution architecture, capability
checks, deadlines, budgets, and cleanup. It MUST NOT introduce another model,
service, planner, hypothesis-registration prerequisite, or mandatory assessment
builder/upload/commit sequence.

Tool calls still use provider-native JSON arguments. The goal is fewer fields,
shallower structures, and fewer relationships for the model to reproduce, not
elimination of JSON. Arbitrary target input and optional multi-item assessments
can still require objects and arrays. Implementations MUST NOT conceal complex
objects inside strings containing JSON or replace named inputs with positional
tuples or an invented mini-language.

## Baseline and contract ownership

The implementation baseline is `candidate-v0.1.4` at
`bd5379834206803ce0be796d3386255323bbae9d`. Its authoritative contract identity is:

- Package version: `0.5.0`.
- Package digest: `sha256:9db8d03e9d759eba0c002444c9c96dbbe77991d47f97e2e9fd1b4b182bec74c3`.
- Operator source: `485042787cc75e1776acaac11023ba9d210cc1f3`.

These identify the comparison baseline, not the version to assign to the new
interface. Operator MUST own the revised model-tool definitions, projections,
normalization rules, validators, error semantics, and shared fixtures. The exact
new package identity MUST be agreed and pinned before Harness implements the new
interface. A new identity is required even if ordinary host-operation messages
remain unchanged. Harness MUST consume those shared definitions; it MUST NOT
maintain a competing tool schema or quietly accept both old and new interfaces.

The host wire format SHOULD remain unchanged wherever deterministic translation
is sufficient. Short handles are a Harness presentation of authoritative state,
not a new host authorization or compatibility protocol. Operator MUST still
validate the expanded request against its retained state. Any necessary host
change MUST be specified in the same shared package before implementation.

The existing lock, embedded compatibility metadata, runtime digest bindings, and
image/catalog publication mechanism MUST carry the resulting identity. This work
does not authorize release publication or a paid/live cloud campaign.

## Shared rules for simpler arguments

1. Keep the existing 11 tool names. Do not add per-field setters, per-claim tools,
   or an obligatory prepare step. This avoids extra calls and partial assessment
   state merely to move JSON construction out of one submission.
2. Model inputs MUST contain decisions and content. Product code MUST construct
   envelopes, generated identifiers, hashes, binding metadata, and mechanically
   derived reference lists. It MUST NOT invent analytical outcomes or evidence.
3. All argument objects MUST reject unknown fields. Omitted optional collections
   resolve to empty collections only where specified below. Invalid supplied
   values, including nulls where not allowed, MUST NOT be repaired or ignored.
4. Defaults and cross-field rules MUST be defined in the shared contract and
   tested across provider projections. Provider schema limitations do not weaken
   runtime validation. Strict mode is optional per codec and MUST NOT substitute
   for reference, ownership, or semantic validation.
5. Existing host-supplied size limits and fixed transport/JSON safety ceilings
   MUST continue to apply to decoded content and expanded requests. Expansion
   beyond an allowance MUST produce a correctable error before dispatch; it MUST
   NOT silently truncate content. This change MUST NOT increase invalid-call,
   target-attempt, model-turn, or other budgets.

### Content arguments

Use this common choice wherever this spec permits content:

| Field | Meaning |
| --- | --- |
| `json` | A native JSON value; Harness serializes it under the shared canonicalization rules. |
| `text` | A UTF-8 string. |
| `base64` | Valid base64 encoding of binary content. |
| `artifact` | A handle returned by successful artifact publication, where explicitly permitted. |

Exactly one content field MUST be present, determined by field presence rather
than truthiness. For example, `json: null` is a supplied JSON value, subject to the
target's own constraints. `json` MUST NOT contain a stringified object as a
workaround for schema limitations; a genuine JSON string value remains valid.

`media_type` is optional for `text`, required for `base64`, and forbidden alongside
`artifact`. JSON resolves to `application/json`; text without a media type
resolves to `text/plain`, preserving the existing shared default. For JSON, an
explicit media type MUST be `application/json`. Harness MUST NOT guess target
encoding from prose. When the target
requires an object, a text argument MUST NOT be silently wrapped in one.

For `artifact_publish`, `media_type` remains required for all content choices,
preserving the caller's explicit publication intent. Artifact publication accepts
`json`, `text`, or `base64`, not another artifact handle.

### Returned handles and deterministic expansion

Harness MUST maintain a bounded mapping from short opaque handles to verified
resources, extending existing attempt, artifact, observation, and record state.
The mapping MUST distinguish executions, observations, artifacts, records,
hypotheses, input references, injections, checkpoints, and permitted source sessions. Prefixes in
examples are for readability; prefix inspection MUST NOT establish resource type
or authority. Submitted scenario, objective, operation, and principal IDs remain
their existing admitted identities and MUST NOT receive unnecessary aliases.

- Handles MUST originate from verified task resources or successful authoritative
  results. Model prose, target output, and JSON embedded in observations MUST NOT
  register handles. A rejected submission MUST NOT acquire an execution handle.
- Handles MUST bind the authoritative identity, resource kind, ownership, and
  applicable campaign/revision/lifecycle information. Resolving a handle MUST
  preserve admission, visibility, integrity, purpose, and range checks.
- A handle MUST NOT be reused for a different resource. Wrong-kind, fabricated,
  stale, and out-of-scope handles MUST produce correctable errors. A failed or
  uncertain execution receipt MUST retain its actual status; its existence does
  not prove successful execution or objective achievement.
- Results MUST provide short handles with sufficient kind, status, and meaning
  to choose them correctly. Raw descriptors and duplicate long identities SHOULD
  be removed from ordinary model results, but MUST remain in the authoritative
  journal/export or existing diagnostic evidence for audit.
- Mapping state MUST survive conversation compaction. Restore MUST preserve
  immutable historical evidence and revalidate live resources under the existing
  restore rules. A resume path MUST restore mappings from trusted retained state
  or reject unavailable handles explicitly; it MUST NOT reconstruct them from a
  model-generated summary or replay an uncertain operation.
- Mapping storage MUST be bounded using existing campaign/resource limits. On
  exhaustion, report a specific limit failure; do not evict still-referenceable
  resources silently. No new external store is required.

An observation handle resolves to its execution receipt, entry, availability,
and optional byte range. Listing an observation does not mean it was inspected.
A complete verified read may retain the original handle. A partial read MUST
return a handle for exactly the verified range; the full-entry handle remains
uninspected until its required content has actually been read. Repeated reads of
the same immutable range SHOULD reuse its handle. Positive content claims MUST
reference inspected, available content. Unavailable or unread handles may be
used to describe evidence gaps, never to assert unseen contents. Byte offsets
remain relative to the original entry; reads through a range handle MUST remain
inside that range.

For each assessment item, Harness MUST expand selected observation handles into
the authoritative observation references and derive the associated execution
receipt list. Explicitly selected execution handles may add receipts for facts
about execution or absent observations. The resulting list MUST be a stable,
deduplicated union. The model MUST NOT be required to repeat an observation's
receipt in an adjacent list. This derivation supplies identifiers only: it does
not establish that a claim is true or that a scenario is covered.

## Changes to every tool

`?` below means optional. Unlisted fields are not accepted. Reusable fields and
advanced item shapes are specified after the table.

| Tool | Current model burden | Revised arguments and result |
| --- | --- | --- |
| `attempt_execute` | Nested encoding envelope; artifact receipt; parent receipt; setup action IDs/type envelopes. | Required `origin`, `operation_id`, and one of `json`, `text`, `base64`, `artifact`. `scenario_id` required only for scenario origin. Optional `media_type`, `parent`, `caller_principal_id`, `rationale`, `observations`, `setup`, `injection`, `retain_injections`, `strategy_provenance_ref`, `technique_refs`. Return an execution handle, authoritative dispatch/effect status, observation handles, and any injection handles. |
| `observation_read` | Receipt ID plus entry ID, mandatory offset. | Required `observation`; optional `offset`, `max_bytes`. Resolve the pair internally. Return inspected observation/range handle, content, availability, truncation, and continuation metadata. |
| `finish` | Nested `assessment`, claim/gap IDs, repeated receipt lists, cross-reference bookkeeping. | Required `finish_reason`, plus exactly one of inline assessment fields, `artifact`, or `unavailable_reason`. Inline fields and expansion are defined below. Return the existing authoritative acceptance/finalization state. |
| `artifact_publish` | `content.encoding` plus encoding-specific nested value. | Required `purpose`, `media_type`, and exactly one of `json`, `text`, `base64`. Return a committed artifact handle, purpose, media type, and size. Hashes, chunking, descriptors, and commit receipts stay product-owned. |
| `reference_read` | Reference ID and mandatory offset. | Required `reference`; optional `offset`, `max_bytes`. Accept the trusted task/reference handle, including existing scenario/resource/tool-guide references. Return content, source/range identity, and continuation metadata. |
| `injection_delete` | Execution receipt plus action ID. | Required `injection`. Resolve the original action and execution binding. Return authoritative removal/effect state. Removal MUST NOT imply reversal of an already committed target mutation. |
| `record_append` | Record-kind wrapper, nested record, repeated receipts and generated IDs. | Required `kind` plus the flattened fields for that kind below. Return an accepted record handle and, when relevant, a hypothesis handle. Keep one optional historical-record tool. |
| `snapshot_request` | Already simple: optional label/description. | Keep `label?`, `description?`; `{}` remains valid. Return a checkpoint handle only when an actual checkpoint identity exists, plus authoritative status. A pending identity MUST NOT imply readiness. |
| `snapshot_list` | Optional raw source session and numeric pagination. | Keep optional `offset`, `limit`; replace raw `source_session` with `session?`. Return checkpoint handles and `next_offset`/end-of-list information. Omission retains current authorized session scope, not a wider search. |
| `snapshot_inspect` | Source session plus checkpoint ID. | Required `snapshot`. Resolve both identities and return authoritative state and permitted metadata. |
| `restore_request` | Source session plus checkpoint ID. | Required `snapshot`. Resolve both identities and preserve the existing restore result, invalidation, and remaining-call handling. No automatic retry after uncertain effects. |

The read tools MUST default omitted `offset` to zero. Omitted read size and
snapshot page size MUST resolve to the existing defaults within admitted limits,
not to an unbounded read. A response MUST identify the next offset when content
remains. Requiring multiple reads for large content is acceptable; requiring an
extra lookup merely to reconstruct a known identifier pair is not.

`reference_read` MUST preserve complete active-scenario delivery, resource detail
reads, and the existing context-switch gate. Shortening tool arguments MUST NOT
reduce a scenario to its hypothesis or weaken the task-data trust boundary.

### Execution and optional setup

`origin` MUST remain explicit: `scenario` requires the exact submitted
`scenario_id`; `exploratory` forbids it. No inference from the sole scenario,
parent attempt, objective, or final evidence linkage is allowed.

`parent` is an execution handle. Harness/Operator derive lineage bookkeeping from
it, without inventing an origin choice. `observations`, when omitted, means the
existing all-permitted selection. When present it is a nonempty array of admitted
observation kinds; an empty or unsupported selection MUST be rejected. This
replaces the redundant `observation_selection.mode` wrapper.

`setup` is an optional bounded array. Each item contains the existing semantic
fields `surface`, `mode`, `scope`, `selector`, and `placement` directly. Product
code assigns `action_id` and the fixed action type. `selector` and `placement`
remain structured because their values express real target selection and
mutation decisions; they MUST NOT become strings containing JSON.

- The existing five surfaces and their selector/placement rules MUST remain
  available when admitted: `model_tool_result`, `service_response`,
  `mcp_tool_result`, `environment_state`, and `database_response`.
- The shared contract MUST preserve required selectors, simulation/fidelity
  restrictions, once/next-turn/standing scope, JSON pointers, insert indices,
  merge allowed-field lists, and target policy limits. It MUST NOT default a
  destructive operation, a selector, or a mutation destination.
- For database environment-state selectors, model input for the row `key` MUST
  be a native JSON object. Shared normalization MUST serialize it to any existing
  host string representation after exact key-column/type validation. This removes
  a second JSON-escaping task without broadening database permissions.
- `injection`, when supplied, is one common content-choice object, including an
  artifact option and applicable media type. It replaces `injection_input`'s
  encoding envelope. Nonempty setup requires injection content; injection content
  and `retain_injections` require nonempty setup. Missing carrier/payload content
  MUST identify the missing field and valid choices, not trigger inference.
- Omitted `setup` means no setup. Omitted `retain_injections` means false. Returned
  injection handles MUST retain each generated action's identity and effects.

Provider projections MUST include only admitted injection surfaces, preserving
the existing frozen capability selection. They MUST NOT hide an admitted surface
merely because a scenario does not mention it. Arbitrary JSON values SHOULD use
the existing compact provider projection strategy rather than recursive schema
expansion; shared validators MUST still enforce exact runtime depth/size rules.

### One finish operation

Inline finish arguments MUST place `summary`, `objectives`, and optional assessment
collections at the root alongside `finish_reason`. There is no `assessment`
wrapper. `summary` and `objectives` are required for inline assessment. The allowed
`finish_reason` values remain `objectives-addressed`, `no-useful-next-experiment`,
`capabilities-exhausted`, `budget-limit`, `context-limit`, and `harness-error`.

Optional root fields are `status`, `hypotheses`, `claims`, `coverage`,
`uncertainties`, and `records`. Omitted status retains the existing `partial`
default; omitted collections are empty. Explicit status uses `completed`,
`partial`, or `failed`. Acceptance is not a declaration of objective success.

The revised item shapes are:

| Collection | Required fields | Optional fields |
| --- | --- | --- |
| `objectives` | `objective_id`, `outcome`, `summary` | `observations`, `attempts`, `records` |
| `claims` | `statement`, `interpretation`, `assurance`, `confidence` | `observations`, `attempts`, `uncertainties` |
| `hypotheses` | `origin`, `outcome`, `summary`; `scenario_id` for scenario origin | `label`, `parent`, `objective_refs`, `observations`, `attempts`, `records` |
| `coverage` | `objective_id`, `status`, `reason` | `hypothesis`, `alternative`, `observations`, `attempts` |
| `uncertainties` | `kind`, `description` | `label`, `observations`, `inputs`, `records` |

`observations`, `attempts`, `records`, and `inputs` are arrays of handles of the
appropriate kind. `inputs` identifies task/reference entries or verified ranges,
not arbitrary artifacts masquerading as supplied input. Objective `outcome`
retains `supported`, `inconclusive`, `not-observed`, and `not-tested`; hypothesis
outcome uses the same values. Claim `interpretation` retains `supported`,
`inconclusive`, and `not-observed`; `confidence` retains `low`, `medium`, and
`high`. `assurance` remains the model's bounded explanation under the existing
contract, not a value inferred from tool success. Coverage status remains
`tested`, `untested`, or `partial`.

Uncertainty `kind` retains `unresolved-effects`, `unavailable-feedback`,
`truncated-feedback`, `unread-input`, `summarized-input`, `omitted-range`,
`coverage-limit`, and `evidence-gap`. `inputs` and observation range handles remove
the need to assemble receipt/entry/range objects. An unread whole-entry reference
remains valid for describing an unread-input gap.

Harness MUST assign claim IDs, gap IDs, and new hypothesis IDs. A model-defined
uncertainty `label` is needed only when a claim references it through
`uncertainties`. A hypothesis `label` is optional unless another item references
that hypothesis; it is not an execution or record receipt. Hypothesis `parent`
and coverage `hypothesis` may select a local
label or an already known hypothesis handle. These references MUST be resolved
against typed state and all local declarations, independent of declaration order.
Ambiguous labels, duplicates, unknown references, self-parenting, and cycles MUST
be rejected. Generated identifiers MUST be stable across duplicate delivery of
the same call. Hypotheses MUST NOT require prior `record_append` calls.

For every item selecting observations, normalization MUST derive execution
references automatically. Where the host shape lacks an observation field (for
example objectives), the selection MUST still be inspection-validated and retained
in local diagnostic evidence, while its receipts map to the existing host field.
Do not create additional analytical claims just to accommodate the host shape.
Optional record references remain typed historical-record handles, never artifact
handles. All shared evidence sufficiency and reference rules continue to apply.

The two non-inline alternatives are:

- `finish_reason` plus `artifact`: a committed conclusion artifact handle. Its
  content MUST meet the authoritative assessment format and binding rules; the
  tool MUST NOT require prior conclusion registration. The ordinary path MUST
  never require this alternative merely to avoid argument construction.
- `finish_reason` plus `unavailable_reason`: no assessment can honestly be
  constructed. Allowed reasons remain `context-limit`, `budget-limit`,
  `local-error`, `serialization-failed`, `invalid-call-limit`, `deadline`,
  `provider-failure`, and `target-failure`.

Inline fields, `artifact`, and `unavailable_reason` are mutually exclusive.
Harness MUST NOT invent an assessment when the unavailable path is used.
Invalid finish arguments MUST remain correctable before acceptance. Accepted
finish MUST retain execution closure, required timely Harness exit, and pending
cleanup semantics. Duplicate delivery MUST not create duplicate effects;
interrupted or uncertain finalization MUST not cause campaign replay.

### Optional historical records

`record_append` MUST flatten `record_kind`/`record` into `kind` and the fields
below. It MUST remain optional and MUST NOT become a staging API for finish.

| `kind` | Required fields | Optional fields |
| --- | --- | --- |
| `hypothesis` | `origin`, `statement`; `scenario_id` for scenario origin | `parent`, `objective_refs`, `assumptions`, `predicted_observations`, `surface_ref`, `records` |
| `progress` | `summary` | `decision`, `objective_refs`, `hypotheses`, `attempts`, `observations`, `records`, `interpretation`, `confidence`, `assurance`, `assessment_summary`, `gaps` |
| `lineage` | `hypothesis`, `attempt`, `mutation_summary` | `parent`, `records` |
| `coverage` | `entries` | `records` |

Hypothesis records receive generated hypothesis IDs and return hypothesis handles.
Their `parent` is a known hypothesis handle; lineage `parent` is an execution
handle. The shared validators MUST preserve provenance, origin, ancestry, and
ownership rules. `entries` uses the revised coverage item shape. Omitted optional
reference/list fields resolve to empty arrays. Surface and objective IDs retain
their existing meaning; `assumptions` and `predicted_observations` retain their
current bounded semantic types.

Progress assessment fields `interpretation`, `confidence`, `assurance`, and
`assessment_summary` MUST either all be absent or all be supplied. When supplied,
`gaps` is optional and defaults to the existing empty collection; `gaps` without
the assessment fields is invalid. Product code constructs the existing nested
assessment. This preserves optional analysis without obligating it in every
progress record. Observation-selected receipts are derived as for finish.

## Ordinary example and reduction in burden

All identifiers below are illustrative. The model receives the exact scenario
and objective IDs from task data and handles from tool results.

```json
{
  "origin": "scenario",
  "scenario_id": "configuration",
  "operation_id": "invoke",
  "json": {"prompt": "Reply exactly QA_CONFIG_OK. Do not call tools."}
}
```

The execution result identifies execution `exec-1` and its target-output
observation `obs-1`, with authoritative status. The model reads:

```json
{"observation": "obs-1"}
```

After a complete verified read, an honest minimal finish can be:

```json
{
  "finish_reason": "objectives-addressed",
  "summary": "The configuration response matched the requested marker.",
  "objectives": [{
    "objective_id": "configuration-check",
    "outcome": "supported",
    "summary": "Observed QA_CONFIG_OK in the target response.",
    "observations": ["obs-1"]
  }]
}
```

An optional detailed claim, if warranted by the actual observation, is:

```json
{
  "statement": "The target returned the requested marker.",
  "interpretation": "supported",
  "assurance": "Directly observed in the complete target response.",
  "confidence": "high",
  "observations": ["obs-1"]
}
```

The current interface instead requires a claim ID, an observation pair such as
`{"attempt_receipt_id":"receipt-123","entry_id":"entry-456"}`, and repetition
of `receipt-123` in that claim's `attempt_receipt_refs`. The revised call supplies
one selected handle; product code fills both host reference fields. It does not
infer the claim, confidence, assurance, or supported outcome.

## Guidance and correctable diagnostics

The trusted prompt and tool descriptions MUST explain the common content choice,
use of returned handles, explicit attempt origin, inspection before content
claims, and one finish call. Keep explanations short and place field-specific
guidance at the relevant tool. Essential ordinary-use instructions MUST NOT be
hidden behind an optional guide read. Existing advanced `tool-guide` references
may carry longer examples and explanations of specialist selectors.

Scenario delivery, follow-up on requested missing details, evidence-based coverage,
and non-replay of uncertain changes MUST retain the existing guidance. Model
instructions MUST distinguish dispatched execution, scenario coverage, assessment
acceptance, and completed cleanup. A completed invocation does not settle the
assessment. Counts and identities MUST come from the submitted scenario bundle.

Local diagnostics MUST identify tool/call, stable code, model-facing field path,
what failed, a bounded correction, execution/effect state, and resubmission safety.
The translator MUST retain path mappings so an error in an expanded host receipt
list points to the corresponding model-selected handle, not a field absent from
the tool. Host error codes and primary causes MUST be preserved. Errors MUST NOT
include credentials or unrestricted submitted bodies.

Examples of required feedback:

- `/claims/0/observations/0`: "This handle identifies an artifact, not an
  observation. Select an observation returned by an attempt and inspect it first.
  This finish was not accepted; correct and resubmit."
- `/origin`: "Choose scenario with a valid scenario_id, or exploratory without
  one. No target invocation occurred; correct and resubmit."
- `/summary`: "Duplicate JSON key. Supply summary once. This finish was not
  accepted; correct and resubmit."

Raw argument decoding MUST continue to reject duplicate keys before they are
discarded where the provider supplies raw JSON. For provider-decoded objects,
Harness MUST NOT claim it detected duplicate keys that the provider already
discarded. Unknown fields and invalid types remain errors; the implementation
MUST NOT salvage malformed arguments by guessing intended content.

Exhaustion MUST retain the observed count, configured limit, last actionable
diagnostic, whether any target invocation occurred, and whether an assessment was
accepted. Automatic unavailable finalization MUST preserve the actual stopping
reason. Exit code zero after accepted finish MUST NOT be reported as proof of a
committed assessment, successful campaign, or completed cleanup.

## Context-window requirements

The handle table MUST stay in program state, not be appended in full to every
model request. Tool results MUST return the handles relevant to that result.
Existing compaction MUST preserve exact referenced handles and their bounded
meaning/status separately from model-authored summaries; it MUST NOT copy the
entire descriptor table into the prompt or lose the ability to recover a valid
handle needed by ongoing work. Handle availability does not imply observation
content survived compaction: preserve evidence provenance and uncertainty, and
permit bounded rereads using the existing tools.

Implementation MUST measure the baseline and revised serialized provider requests
for each supported codec: OpenAI Chat, OpenAI Responses, Anthropic Messages,
Bedrock Converse, and Gemini. Use identical admitted capabilities, scenarios,
limits, target content, and deterministic responses. Cover ordinary-only and
fully admitted catalogs, each injection surface, and representative combinations.

The measurement report MUST include:

- Per-tool and complete-catalog JSON bytes, descriptions included; token counts
  using the applicable local tokenizer when available, otherwise clearly labeled
  reproducible estimates with method/version. Estimates MUST NOT be described as
  exact provider token admission. No paid API calls are authorized for measurement.
- Combined trusted prompt, task guidance, and tool-catalog cost, so moving a long
  description from a schema to the prompt does not conceal growth.
- Required field counts and maximum envelope nesting for ordinary calls, excluding
  intrinsic target content; generated/repeated identity fields removed.
- Full request-history size, estimated/measured input tokens, peak prompt size,
  model/tool turns, retries, and compaction behavior for the representative flows.
  Include partial evidence reads and advanced setup, not only an empty campaign.

For each codec/configuration, complete catalog bytes and combined initial
instruction/catalog cost MUST NOT exceed baseline. Comparable token measurements
MUST also not increase. Any unavoidable exception requires an explicit user
decision supported by measurements; do not silently omit capabilities to pass.
The implementation SHOULD reduce ordinary-tool schema bytes by at least 25%; if
that target is missed, explain the measured tradeoff rather than inflating field
descriptions or claiming an unmeasured saving.

An equivalent successful ordinary experiment MUST NOT require more model/tool
round trips than baseline. Long-session tests MUST show that handle bookkeeping
does not cause earlier context exhaustion for the controlled workload. A larger
tool catalog or mandatory assessment-editing dialogue is not an acceptable
default solution to malformed finish arguments. Complete active scenario content,
required safety guidance, and actual evidence limitations MUST remain intact.

## Implementation locations and delivery

The implementation MUST update these existing components together:

| Area | Required change |
| --- | --- |
| Operator shared package | Authoritative argument/result definitions, concise descriptions, provider projections, normalization/validation semantics, path mapping rules, and Go/Python shared fixtures. |
| `src/attack_harness/tools.py`, `model_turns.py` | Validate revised arguments, preserve duplicate-key detection and native call correlation, translate actionable errors without changing retry limits. |
| `attempts.py`, `artifacts.py`, `observations.py`, `handlers.py` | Resolve/register typed handles, translate content/setup/read/snapshot/record inputs, and emit concise verified results. |
| `conclusion.py` | Expand assessment references and generated IDs, validate selected evidence, send exactly one authoritative finish, preserve duplicate/uncertain-finalization behavior. |
| `composition.py`, `adaptive.py` | Install shared projections, deliver unchanged complete scenario content, preserve handle identity and evidence limitations through existing context management. |
| `assets/default-system-prompt.txt` | Replace obsolete argument examples and receipt-bookkeeping instructions with the revised ordinary examples and concise handle guidance. |
| `build/contract-lock.json`, `build/operator-runtime-commit.txt`, existing generated build metadata | Pin the matching contract/runtime and regenerate source locks, compatibility data, and catalogs through existing build tooling. Do not hand-edit generated schemas. |
| `tests/`, `build/verify_integration.py`, existing Operator process fixtures | Add regression, projection, context-size, and representative cross-process checks described below. |
| `docs/INTEGRATION.md` | Document actual installed tool shapes, handle/range behavior, ordinary workflow, advanced options, compatibility identity, and context behavior. |

Handle storage SHOULD be a small shared in-process component only if needed to
avoid independent maps with inconsistent validation. Do not introduce a general
workflow engine or external registry. Existing artifacts, journal correlation,
read accounting, runtime finalization, and compaction facilities MUST be reused.

Work MUST remain on a feature branch targeting `candidate-v0.1.4`. Coordinated
Operator changes MUST land in a matching integration build before Harness's final
verification. Release publication remains a separate authorized action. Build
both image architectures and verify their embedded identities using the existing
build/inspection workflow; do not weaken required inspections to accept a new pin.

## Acceptance and regression verification

Controlled fixtures MUST exercise the actual serialized model request, tool
dispatch, matching Operator process, local target, retained assessment, and final
export. Validator-only tests are insufficient. No live reliability improvement
may be claimed solely from controlled responses.

1. **Basic campaign:** complete scenario input reaches the model; explicit scenario
   origin reaches Operator unchanged; direct execution, evidence read, and a
   single inline finish succeed. Export contains the correct scenario association,
   assessment and receipt bindings; Harness exits zero after acceptance; Operator
   reports cleanup separately and it completes. No artifact, hypothesis record,
   or model-authored bookkeeping is required.
2. **Observed finish regression:** reproduce the structural failures from
   `aws-openai-gpt-5-mini-001` using sanitized deterministic fixtures. Exercise four
   completed executions and claims selecting their actual observation handles.
   Assert every normalized claim includes the proper receipt list without the
   model supplying it. A duplicate summary remains a correctable error; the next
   valid finish can succeed. Root `finish_reason` is accepted; an obsolete
   `assessment` wrapper is rejected with guidance to use root fields. No target
   invocation is replayed while correcting finish.
3. **Invalid-call limit:** five consecutive invalid calls still trigger the
   configured limit of five in that fixture. Model feedback, exported diagnostics,
   unavailable finalization, assessment absence, and cleanup preserve the true
   cause. The implementation MUST NOT mark this as assessment success.
4. **Reference categories and ranges:** cover fabricated/wrong-kind/stale handles,
   rejected submissions, cross-campaign resources, unread/unavailable content,
   partial ranges, tampered content, duplicate reads, and host rejection. Positive
   claims require inspected evidence; errors point to the supplied handle field.
5. **Honest incomplete assessment:** zero attempts, empty evidence, untested
   objectives, missing retrieval/refund/attack evidence, and uncertain state-changing
   effects can finish honestly. Harness does not invent findings, declare coverage
   from invocation counts, or replay an uncertain action.
6. **Artifact and input choices:** text/JSON/base64/direct and artifact paths obey
   purpose, ownership, encoding, and host limits; missing or multiple choices fail
   locally. Retention failure prevents dispatch. Large reusable input still uses
   the existing artifact lifecycle with no model-authored digest or descriptor.
7. **All advanced tools:** test all four record kinds, inline new hypotheses,
   forward/local/historical references, cycles and duplicate labels; all admitted
   injection surfaces, deletion, snapshots, inspection, pagination and restore.
   Verify generated action IDs and handles preserve effect identity, selector
   restrictions, cleanup and ancestry. No action is hidden based only on scenario
   wording, and no new preregistration is required.
8. **Duplicate/uncertain delivery:** replay the same native call identity and
   simulate interruption around execution and finish. Generated identifiers and
   handle mappings are stable, accepted operations are not duplicated, and pending
   cleanup is not reported as complete. Changed arguments under an existing call
   identity must not be mistaken for an identical retry.
9. **Context and codec parity:** use all five supported codecs, capability-filtered
   schemas, full and oversized scenario bundles, partial reads, compaction, and
   long histories. Shared fixtures demonstrate the same accepted/rejected meanings
   even where native schema expressiveness differs. Record the context metrics
   above; essential active-scenario content is delivered or an explicit limit
   diagnostic prevents execution.
10. **Compatibility and packaging:** matching components pass the process workflow
    and both image inspections. Old/new incompatible combinations fail before
    execution using the existing compatibility mechanism. Verify the installed
    tool catalog, prompt, shared package, and runtime pins agree.

The delivery report MUST identify the exact matching package/runtime identities,
controlled workflows exercised, before/after context and formatting measurements,
and any unverified provider/container boundaries. Live model/cloud campaigns
require separate authorization and MUST be labeled separately from controlled
verification.
