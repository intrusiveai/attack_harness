# Attack Harness — Python Implementation Specification

Status: implementation in progress; see [current coverage](IMPLEMENTATION_STATUS.md)
Date: 2026-09-16  
Harness identity: `operator-native`

## 1. Outcome and reading order

Implement a custom Python 3 harness that runs as one disposable Operator Sandbox
container guest. It consumes the full submitted ScenarioBundle, invents concrete attack
payloads, submits typed experiments through Operator, reads permitted feedback,
and adapts its next experiment until it finishes or Operator closes execution.
The deliverable is a working adaptive agent, including its model conversation,
tools, evidence handling and conclusion, packaged in the immutable OCI release.

Read these documents before coding, in order:

1. [Operator product specification](../operator_sandbox/OPERATOR_SANDBOX_SPEC.md),
   especially Sections 5–8, 10 and 11: shared authority and execution semantics.
2. [Operator container contract](../operator_sandbox/GUEST_CONTAINER_SPEC.md):
   process, descriptors, startup gates and containment.
3. [Attack Harness artifact specification](GUEST_ARTIFACT_LAYOUT_SPEC.md): image, mounts,
   prompt, skills, limits and release qualification.
4. This document: application implementation and functional acceptance.
5. [Accepted shared host/harness contract](../operator_sandbox/schemas/SHARED_CONTRACT.md):
   authoritative package, wire, startup/manifest, identity/deadline and stop rules.
6. [Current attempt/feedback contract](../operator_sandbox/schemas/FEEDBACK_CONTRACT.md)
   and current v1alpha2 attempt schemas: shared source for generated validators.

Operator owns shared schemas and host authorization. This document specifies
engine responsibilities under that accepted contract; it does not establish
a competing schema registry. All identifiers, field names and versions must be
checked against the Operator-owned package selected at implementation time.

The [public objectives/scenarios input](../operator_sandbox/schemas/SCENARIO_BUNDLE_CONTRACT.md)
defines producer-neutral ScenarioBundle content. User-authored and generator-authored
inputs use the same shared package and startup path. Objectives-only input uses the
existing exploratory attempt origin. Source/catalog/model provenance is optional;
retain it when supplied without making it an execution prerequisite.

## 2. Contract work required before integration

The inspected repositories contain container design documents and retained draft
attempt schemas, not a complete runnable host/guest SDK. Implement isolated
components and test doubles while the accepted package is authored and tested.
Design decisions in HC-01/HC-04/HC-05 are resolved by the shared contract; their
publication and implementation gates remain open.
Production startup must reject incomplete or incompatible contract packages.

| ID | Required decision or artifact | Owner and implementation requirement |
|---|---|---|
| HC-01 | Shared package publication | Design accepted in the shared contract. Operator must author the remaining closed container/input/skill/ScenarioBundle/record/artifact/lifecycle/pipe schemas, registry/catalog and semantic rules, and publish package 0.1.0 after shared Go/Python vectors pass. Engine pins exact version/content digest. |
| HC-02 | Observation bytes available to the adaptive loop | Design resolved by Operator’s shared feedback contract and current schemas. Implement/qualify the broker and harness wrapper, byte assembly and model-visible content; Interceptor implements the native manifest/chunk operations. |
| HC-03 | Attempt observation selection | Design resolved: current v1alpha2 attempt request has optional `observation_selection`, defaulting to all-permitted, or an explicit selected subset. Pin/generate validators and qualify deterministic native translation without broadening feedback profiles. |
| HC-04 | Conclusion and finalization publication | Design accepted: engine-conclusion/v1alpha2, typed conclusion record and exact request_stop/acknowledgement in shared contract Sections 10–11. Author schemas/validators and pass conclusion, missing-conclusion, duplicate/lost acknowledgement and terminal-stop fixtures. |
| HC-05 | Manifest delivery publication | Design accepted: required immutable /run/operator/manifests/ mount, fixed descriptors, inventories outside their own hashes and explicit manifest limits in shared contract Section 7. Publish schemas/fixtures and qualify both startup ends, including inventories exceeding 64 KiB. |
| HC-06 | Model and target compatibility | Pin the supported native codec subsets and source-bound delivery schema dialects. Qualify actual host routes. Interceptor implements campaign-based access; qualify the exact native source/image and container deployment. |

For HC-05, the required host mount is `/run/operator/manifests/`,
read-only with the same regular-file/no-link protections as inputs. It contains
`input-tree.json` and `skill-set.json`, plus only explicitly declared per-skill
manifests if needed by the shared format. Startup descriptors bind their fixed
paths, raw byte lengths/digests and schema identities. InputTreeManifest does not
list itself or this manifest directory in its hashed input file set; it binds the
completed skill descriptors using the shared acyclic recipe. Manifest limits are
fixed in shared contract Section 7: 8 MiB input-tree, 64 KiB
skill-set, 2 MiB per-skill and 40 MiB aggregate, with relative paths at most 1,024
UTF-8 bytes/depth 16. Read them incrementally after `initialize`, following
confinement. No startup message chooses an arbitrary path. This is a required
host-created
mount; the guest cannot create or select it.

Track these decisions in a checked-in contract compatibility document during
implementation. A fake host may exercise the accepted design, labeled test-only until package
conformance and native integration pass.
Never present a fake-only schema, shim or passing fixture as native compatibility.

Operator selects an administrator-installed local Docker image and validates its
[HTTPS release record](../operator_sandbox/schemas/ENGINE_RELEASE_CONTRACT.md)
before guest execution. Registry authentication, pulling and updates are deployment
work, not harness or Operator startup operations. The release service identifies
the exact contract package already installed on both ends; guest network access
or runtime schema download is never required.

## 3. Implementation layout and component responsibilities

Use a normal Python package with a fixed composition root. The following source
layout is recommended; module boundaries are required even if filenames change.

```text
pyproject.toml
src/operator_native/
  bootstrap.py             trusted startup and confinement gate
  runtime.py               FIFO/spool control scheduler and lifecycle
  protocol.py              strict framing, envelopes, correlations, deadlines
  contracts/               adapters to pinned generated/shared contract package
  inputs.py                verified immutable input/manifest access
  skills.py                exact instruction-only skill loading
  context.py               bundle index, model context and coverage of reads
  model/                   native codec registry and conversation handling
  tools.py                 fixed catalog-to-handler map
  artifacts.py             byte encoding, upload, committed byte cache
  attempts.py              structural/semantic validation and lineage
  observations.py          receipt-scoped reads and evidence provenance
  loop.py                  model/tool/adaptation orchestration
  records.py               typed guest assertions and host receipts
  conclusion.py            structured finalization
native/                    minimal release-owned confinement component
share/                     default prompt, catalog and engine manifest inputs
tests/                     unit, contract, fake-host and native integration tests
Dockerfile                 multi-stage release image build
build/                     locks, build scripts, inventory and qualification
```

No agent framework, provider network SDK or tool server is necessary. Prefer
small dependencies whose imports and live behavior can be qualified without
sockets, threads, subprocesses or runtime downloads. Select the Python version
from the actual pinned runtime ABI, not from a developer machine.

Use explicit typed interfaces between components. In particular, separate:

- provider tool-call IDs, local call IDs, transport correlation IDs, durable
  operation/request IDs, attempt IDs and host receipt IDs;
- immutable input descriptors, provisional artifact bytes and committed outputs;
- host execution results and guest interpretations of those results;
- scenario provenance and actual capability/policy authorization.

Use distinct types or validation constructors to prevent accidental substitution.
Local state is campaign-lifetime memory or bounded scratch, retained across
healthy target revisions but never used as a failed-process resume database.
Imports resolve only from fixed immutable release locations. Payload text, JSON,
references, skills and model output must never become Python source or callables.

## 4. Startup, transport and lifecycle

Implement the artifact specification's startup sequence exactly:

1. Start the fixed interpreter with `-I -S -B` and the literal bootstrap path.
   Establish reviewed imports and the transport scheduler using release code only.
   Initialize the OS-selected transport: Linux mounted FIFOs at FD 3–6 or macOS
   regular-file spool lanes, before receiving `bootstrap`. Do not parse
   scenario, skill or model data yet.
2. Receive host `bootstrap` on the host control channel; validate assigned campaign/launch/container/
   revision and pinned package/release/profile/RunManifest. Install the irreversible
   live filter, check every result and send `confinement_ready` on the guest control channel.
3. Receive `initialize` only after Operator's runtime, journal and Docker lifecycle
   gates. Validate fixed manifest descriptors and deadline, then verify complete
   immutable manifests, required input bytes, prompt and selected skill files.
4. Send `initialized` with verified identities/digests. Wait for `admission_open`
   with current revision, registered operations and effective/remaining budgets
   before sending model, artifact, record or attempt requests. Confinement/readiness
   and input initialization each have a 60-second ceiling.
5. Enter the adaptive loop. Stop on host closure, failure or completion. Healthy
   target restores retain this process/context and do not repeat the handshake.
   No reconnect, replacement process or failed-campaign conversation resume.

On Linux hosts, bootstrap opens `/run/operator/ipc/{ordinary-in,ordinary-out,control-in,control-out}`
and maps ordinary response/request to FD 3/4 and host/guest control to FD 5/6.
Apply the [FIFO rendezvous/access rules](../operator_sandbox/GUEST_CONTAINER_SPEC.md#41-descriptor-inventory):
no O_RDWR/dummy endpoints, no opposite-direction access, bounded startup waits,
no reconnect after peer failure. Reopening the same permitted FIFO paths need not
be prevented by the kernel; it cannot reset transport state or resume failed work.

On macOS hosts, initialize the private regular-file lanes under `/run/operator/spool/`.
Use atomic publication and bounded polling as specified by the
[spool contract](../operator_sandbox/GUEST_CONTAINER_SPEC.md#411-macos-file-spool-transport).
FD 3–6 and FIFO EOF semantics do not apply. Poll control during ordinary waits,
hashing and artifact work. Implement the
[accepted shared spool rules](../operator_sandbox/schemas/SHARED_CONTRACT.md#41-macos-file-spool-wire-rules):
20-digit sequence filenames, atomic temporary publication, 10 ms polling and
cumulative `consumed.json` ACKs (1 KiB maximum) in each producer's control lane.
ACK after copying/validating a message into a bounded queue, not after completing
the operation. Producer deletion reclaims acknowledged files; no ACK-of-ACK, TTL
deletion of outstanding messages or crash replay. Count in-progress publications
against queue limits and serialize one temporary file per writer/lane.

Operator checks the combined macOS spool size once per second with administrator
setting `spool.max_bytes`, default 536870912 bytes (512 MiB). Excess triggers host
Docker termination even if the harness is unresponsive; the harness cannot raise
the limit. The periodic check permits overshoot and does not change wire limits.
Host shutdown deletes spools after container exit and host writers stop; healthy
target restore keeps the same harness transport. Follow the
[host file-management rules](../operator_sandbox/HOST_RUNTIME_PROFILES.md#host-spool-size-check).

Input/skill/manifests stay read-only and are read only after `initialize` on both
profiles. Stdout/stderr are bounded diagnostics only. Use a reviewed single-threaded
event loop with nonblocking FIFO I/O or bounded file polling, without socket pairs
or helper threads. Each FIFO message has a four-byte big-endian length prefix;
each ready spool file contains one complete JSON object without that prefix.
Enforce 4 MiB ordinary/64 KiB control JSON ceilings, depth 32, consecutive per-direction
sequences and exact correlation. One ordinary operation is outstanding.
Reject oversized lengths/files before allocation; parse only bounded complete messages.

Use the accepted shared envelope: `call_id` correlates one exchange,
`operation_id` identifies the durable submission, and nested attempt `request_id`
equals `operation_id`. Requests carry positive relative `timeout_ms`; Operator
uses a monotonic deadline capped by operation policy and remaining campaign time.
Model/create-or-restore/other operation ceilings are 120/300/30 seconds, also
subject to adapter limits. FIFO partial-frame/blocked-write and spool publication/acknowledgement/full-queue waits time out
in five seconds; response availability uses the operation deadline.
Neither partial I/O nor progress renews limits. Consume the shared typed errors
and effect/disposition rules without inferring non-execution from a timeout.

Reject duplicate keys, nonfinite or out-of-range numbers, lone surrogates,
trailing values, unknown command fields/enums, excess depth and malformed native
tool envelopes. A generic `json.loads` call alone is not all these validations.
Schemas resolve offline; validators must not fetch arbitrary `$ref` locations.

Each ordinary queue holds at most two frames/8 MiB. Control has separate bounded
queues, at most 16 frames/1 MiB per direction,
and priority service during model/target waits, artifact transfer, file hashing,
context construction and diagnostics. Bound work per scheduling interval and
qualify worst-case parsing/canonicalization latency. Do not queue all frames of a
large artifact or block on a full stdout pipe. Close unrelated inherited FDs and
detect unexpected FIFO EOF, failed spool lanes, mismatched IDs and stalled required consumers
as terminal. Expected EOF after accepted graceful stop is normal teardown.

Guest progress records describe current work; they do not prove useful progress
or grant permission to extend a deadline. Admission is always
host-owned. Immediate stop prevents queued calls from dispatching and must not
wait for a model response, report upload or cleanup. Direct CLI Docker termination is independent of the worker and depends on responsive Docker.

## 5. Input understanding and scenario alignment

### 5.1 Verify before use

Verify fixed paths, regular-file types, immutable views, exact inventories,
canonical paths, sizes, raw digests, schema compatibility and cross-file bindings.
Use descriptor-relative no-follow reads; reject links, unexpected entries,
traversal, special files and mismatches. Verify required references before the
first model call. An included-but-missing reference is an initialization failure.
Only omissions already authorized and frozen by the host are valid omissions.

Keep the full original ScenarioBundle accessible at its immutable input path.
Build an index for model context without rewriting or replacing that bundle.
Preserve its verified authoring capability/source identity and supplied optional
catalog/context provenance. Operator's accepted validation record separately binds
the current live execution projection. By default admission checks compatibility:
unrelated live capability changes are allowed, and Attack Harness plans against the current
projection, not stale authoring descriptions. Only an explicit bundle
`capability_projection_digest` requests an exact static match. Do not reject an
accepted bundle merely because authoring and live source digests differ. The
[public capability contract](../operator_sandbox/schemas/CAPABILITY_EXPORT_CONTRACT.md)
defines copyable reference namespaces and required-versus-optional handling.
Objectives and prose need no capability enumeration; missing optional routes and
guidance become coverage gaps. Advertised action refs are distinct from the local
`action_id` handles Attack Harness assigns to particular attempts. Existing tool contracts
and host per-attempt permission checks remain unchanged.
Do not flatten it into EngineContext. Do not reopen analyst source paths or fetch
knowledge, links or dependencies from the network.

Read every selected SKILL.md in canonical skill-ID order using the frozen exact
skill manifests; a canonical empty set reads none. Validate the entire selected
set atomically. Reference files are passive data available only by manifest ID
and bounded byte range. Follow the existing closed frontmatter/format rules;
no hooks, plugins, tools, executable templates or installation instructions run.

Use the exact staged system-prompt bytes on every model turn. Operator composes
default/replacement/ordered extension before launch. Do not normalize whitespace,
recompose it, prepend hidden defaults in replacement mode or include unused
prompt source files. The release tool catalog stays separate from prompt text.

### 5.2 Map the bundle into an execution portfolio

Consume the ScenarioBundle from the pinned shared contract package. Its semantic
requirements are defined by [Operator's submission contract](../operator_sandbox/schemas/SCENARIO_BUNDLE_CONTRACT.md)
and the table below. HC-01 includes publication of the exact versioned schema.
The table describes required information and behavior rather than JSON field names.

| Bundle information | Required harness behavior |
|---|---|
| Bundle/target/source identities; optional producer, catalog and context versions | Preserve immutable provenance in the portfolio and guest records. Reject incompatible target bindings. A reference to protected provenance does not grant content access. |
| Objectives, priorities, coverage goals, limitations | Build an explicit work queue and coverage ledger; tell the model what remains untested and which facts are uncertain. |
| Stable scenario IDs and hypotheses | Associate experiments with their originating scenario; record explicit exploratory origin for unlisted hypotheses. |
| Optional source technique references and composition relations | Expose permitted descriptions and provenance. Preserve distinctions between source taxonomies; combinations are strategic knowledge, never executable recipes. |
| Prerequisites and required capabilities | Check against the actual projected operations, action types, schemas, selectors and assurance. Missing required runnable context fails initialization; unsupported optional routes become coverage gaps. |
| Suggested surfaces, variations, ordering and chaining | Let the model choose compatible payloads and combinations, reorder or abandon suggestions, and branch on observations. Do not require every suggested alternative surface to exist. |
| Expected live observations and success criteria | Establish what feedback could support or refute the hypothesis, and what remains unobservable. Post-run-only evidence is unavailable to live adaptation. |
| Suggested effort and stopping guidance | Use for prioritization and diminishing-return decisions. Only effective host/deployment/target limits are hard execution authority. |
| Supporting reference descriptors and allowed omissions | Maintain available/read/partially-read/unread/omitted distinctions with IDs, digests and ranges. |

The portfolio is an application data structure, not another authorization layer.
Do not reject an otherwise permitted experiment simply because its wording,
technique or ordering is absent from the submitted bundle. Conversely, scenario prose cannot add
an operation, destination, file namespace, observation class or credential.

An empty scenario array is valid. Build the work queue from objectives and actual
capabilities, use exploratory-origin attempts, and retain objective associations
in existing strategy/coverage records. Do not fabricate scenario or catalog IDs.
Required objectives may conclude untested/inconclusive when limits or safety require
completion. Scenario guidance cannot extend host limits or change stop semantics.

### 5.3 Construct bounded model context

Each native request includes the exact effective system prompt, supported tool
declarations, safe capability/delivery context, current objectives and work queue,
the selected scenario/hypothesis, relevant skills/references, exact correlated
recent tool results, current budget projection and remaining coverage gaps.
Keep system/task/reference/model/tool roles and content provenance distinct.
External text cannot register tools or become a new system message.

For a bundle larger than the selected model context, include a bounded index of
all scenarios and reference handles, then materialize relevant full entries and
references on demand. The local `reference_read` facility may expose validated
bundle-entry handles or bounded ranges in the immutable bundle; handles never
become arbitrary file paths. Selected skill entrypoints must all be read by the
loader; report separately how much of their content the model received.

Reserve context/output capacity for tool results and completion before requesting
generation. Use a pinned offline token counter or documented conservative bounds
compatible with the model profile; do not download tokenizers at runtime. The
host remains authoritative for billed usage. If mandatory system/catalog/context
content cannot fit, fail explicitly before submitting an oversized request.

Compaction preserves immutable identities, live hypothesis/lineage, known result
dispositions, evidence references, outstanding coverage and uncertainty. Compact
only complete provider-valid conversation segments: never orphan a tool call,
drop a required continuation item or turn a summarized inference into evidence.
Keep a record of omitted ranges/turns and summary provenance. No compaction is
persisted to resume another harness process. If safe compaction is impossible, finish
with a context-limit gap rather than silently dropping required information.

## 6. Native model loop and tool execution

### 6.1 Model client contract

The selected safe model profile determines one native codec and allowed features.
Build supported non-streaming native requests for `engine.model_generate`; the
host makes the actual provider call. Preserve native text/system roles, function
declarations and arguments, call IDs/order, tool results, finish reasons, usage
and required supported continuation fields. Never switch provider/model/route on
failure or flatten different providers into an invented universal wire protocol.

Implement each advertised family/variant against pinned host conformance vectors:
OpenAI Chat/Responses, Anthropic Messages, Bedrock Converse, Gemini Developer,
and the selected Azure OpenAI, Vertex Gemini and LiteLLM routes. Start with one
qualified route for a vertical slice; release metadata must advertise only routes
actually supported and tested. Hosted tools, streaming, background jobs, arbitrary
provider files/state, multimodal and embeddings are outside the initial subset.

A complete, validated, host-recorded response must arrive before executing any
of its tools. Preserve refusal, truncation, safety/finish status and usage as
native outcomes; do not parse truncated arguments or invent a tool call from
prose. A valid response without tool calls may produce bounded further reasoning
or a structured finish request within limits; plain final prose alone does not
complete a campaign. Transport/provider execution failure is terminal. No SDK
retry, hidden additional model call or zero-usage assumption after uncertainty.

### 6.2 Fixed tool catalog

Bind local tool schemas, generated provider projections and handlers into the
release. Use explicit dictionary entries for fixed callable handlers, never
model-selected imports, reflection, shell dispatch or a generic broker forwarder.
Tools visible to the model are:

| Tool | Handler contract |
|---|---|
| `reference_read` | Read one verified immutable input/skill/bundle handle and range; return source identity, actual range and bounded content. |
| `artifact_publish` | Encode supplied text, JSON value or explicit bytes as data; validate size/media/encoding, upload through begin/part/commit and return a committed receipt. No model-supplied source filename. |
| `injection_delete` | Remove one retained injection by `attempt_receipt_id` and `action_id`; Operator resolves the ID in the current campaign target. Confirmed absence succeeds. |
| `attempt_execute` | Submit the complete structured attempt after structural, artifact, lineage and capability checks; return the correlated typed result. |
| `observation_read` | Adopted HC-02 tool: read bounded permitted feedback by host result receipt and observation entry ID; never by a bare arbitrary digest/path/URL. |
| `record_append` | Record bounded typed hypotheses, decisions, coverage and evidence assertions; return the host record receipt. |
| `request_stop` | Local finalization wrapper taking a bounded structured conclusion draft and finish reason; Section 11 commits it, records its receipt and sends the host stop request. Accepted shared Sections 10–11 govern; HC-04 tracks schema publication/tests. |
| `restore_request` | Restore an explicit checkpoint; retain the live harness and adopt only a host-confirmed new revision. |
| `snapshot_request` | Optional `label` and `description` (UTF-8, at most 4,096 bytes); host supplies campaign ID and returns checkpoint metadata. |
| `snapshot_list`, `snapshot_inspect` | List with optional source handle/offset/limit, or inspect a source-session/checkpoint pair; return metadata including campaign ID and description. |

The local `request_stop` wrapper is deliberately richer than the wire stop
operation: it does not add conclusion bytes to an unversioned host stop envelope.
Internal model generation is never a recursive model-facing tool. Unknown names
and malformed arguments yield bounded correlated diagnostics without contact.
An `attempt_execute` argument rejection uses the shared typed rejected result,
not a contradictory success/error flag or duplicated prose representation.

Validate the complete native response envelope and tool-call ID uniqueness first.
For multiple supported calls, dispatch serially in declared order, validating each
call before its effect and preserving one result per executed/rejected call ID.
An argument error may be returned for correction; it does not turn other data
into commands. Fatal failure, unknown effect or host stop prevents all later
calls and model generation. Record undispatched calls for reporting without
delaying termination or fabricating successful results.

A successful restore is a nonterminal batch boundary. Adopt the confirmed new
revision, keep the actual restore result, and skip every remaining call from that
same model response, including reads, helpers, cleanup, another restore and stop.
Return exactly one correlated `not_executed` / `TARGET_REVISION_CHANGED` result
for each skipped tool-call ID using the
[shared local-result schema and batch rules](../operator_sandbox/schemas/SHARED_CONTRACT.md#91-tool-call-batch-boundary-after-restore).
Do not invoke per-tool argument decoders/validators or handlers for skipped calls,
or forward those calls under the new revision. This result is not a fabricated EngineAttemptResult or
host receipt. No skipped attempt/artifact/effect is admitted or charged.

Complete the provider-valid segment with the original assistant tool-call message,
actual results through restore and all skipped-call results in original order.
Only then request the next model response at the new revision and let it choose
fresh actions. Preserve the segment through compaction. Never auto-replay queued
calls. A known no-effect preflight rejection returns its real error and permits
normal later-call dispatch at the unchanged revision. Duplicate restore responses
must not append results or generate the next model turn twice; host termination
always takes precedence.

### 6.3 Adaptive state and decisions

Maintain campaign-lifetime records for hypotheses, threads, attempts, observations,
coverage, artifacts, model/tool turns and host receipts. A hypothesis carries its
objective, origin/source references, assumptions, chosen surface and predicted
observable signals. An attempt carries the exact tactic and immutable lineage.
An interpretation carries supporting observation references, confidence and gaps.
Store concise experimental rationale, not a requirement for hidden model reasoning.

The accepted `record_append` union has closed kinds `hypothesis`, `progress`,
`lineage`, `coverage` and `conclusion`. Represent decisions/interpretations within
the corresponding typed records; do not invent extra wire kinds. Record meaningful hypothesis/decision changes and evidence references
through that tool; the orchestrator also tracks actual calls, reads and receipts
automatically so a model's claimed activity cannot overwrite what happened.
Only host-acknowledged records are durable. Tie attempts to their hypothesis or
strategy record through the shared provenance fields; do not hide required
structure in a free-text rationale.

The loop executes this behavior:

```text
verified inputs + host admission
  -> choose hypothesis and predicted observable outcome
  -> model selects/generates payload and any separate trigger carrier
  -> publish exact bytes and obtain committed receipts
  -> validate and submit one complete attempt
  -> inspect execution disposition
       rejected/correctable: return diagnostics for bounded correction
       completed: read permitted feedback and interpret it
       failed/unknown/host stop: close the loop; never replace the attempt
  -> record evidence-backed interpretation and coverage
  -> refine / transform / combine / branch / pivot / finish
```

The arrows represent model/tool turns as needed, not a second fixed payload
generator or mandatory model call per step. Decisions may be made with several
tool calls across multiple turns. The orchestrator enforces the dependencies:
commit before submission, complete result before interpretation, known completed
experiment before adaptation, and stop before dispatching any later queued action.

After each completed experiment, prompt the model to distinguish delivery,
response and effect, identify the changed variable in the next variant, and
explain which evidence motivates refinement or a pivot. It may continue a thread,
start another scenario, combine hypotheses or start an exploratory branch.
Logical branching creates serial experiments, not cloned guests or target state.
The target may retain application effects; a new attempt is not a clean baseline.
Record carryover/contamination and use only explicitly available state operations.

Enforce the [shared harness execution rules](../operator_sandbox/schemas/HARNESS_EXECUTION_RULES.md)
using resolved `EngineContext.limits.harness`: defaults are 300 model turns,
2,000 dispatched tool calls, 16 calls per model response, 50 total/5 consecutive
invalid calls, 256 MiB cumulative reference/skill/feedback reads and 10 no-progress
turns. Configuration is finite and positive, narrowed by release/host/target policy.
Check before dispatch/read, count local rejection and model compaction as specified,
and retain all counters across restores. Skip after restore without allocating an
attempt or charging a dispatched call. Do not dispatch any of an oversized batch.
Progress means completed experiments, novel content reads or first payload/carrier
commitments; records, heartbeats and state management alone cannot reset it.
At a graceful threshold, stop exploring and construct completion from known records
without another model call, using the bounded finalization allowance in that
contract. Host hard stop/failure/unknown effect always takes precedence. Local
estimates never refund authoritative charges or extend admission.

## 7. Payloads, delivery and attempt lineage

### 7.1 Artifact construction

Keep attack content distinct from the application invocation that triggers its
retrieval. A direct-input experiment may invoke with the payload itself; an
indirect experiment often needs an injection payload plus a separate benign
carrier matching the application input schema. Commit both before submission.

Use deterministic release-owned encoders for UTF-8 text, bounded JSON values and
explicit binary data. Preserve the declared bytes and media type. Apply only the
canonicalization named by the artifact/delivery contract. Operator object
canonicalization, raw SHA-256, OCI digests and native Interceptor digests are
different recipes. A host cannot silently rewrite a payload to make it valid.

For retained Interceptor injection, the payload is one `jcs-v1` JSON value:
text append/prepend uses a JSON string, object merge uses a JSON object limited
to permitted fields, and insertion/replacement uses the advertised value schema.
Every setup action's payload digest must match the main committed payload.
Changing a payload requires new bytes and a new receipt. Generated code stays data.

`artifact_publish` wraps declared size/media/digest, ordered parts of at most
256 KiB raw, and commit verification. Check matching IDs, offsets, counts, total
bytes and the returned digest/media/size before exposing a usable receipt.
One artifact is at most 16 MiB and the campaign total at most 1 GiB, both narrowed
by policy. A model tool's smaller argument/envelope/output-token ceiling still
applies; 16 MiB storage does not promise a 16 MiB single model call. Larger
internally assembled outputs use fixed bounded helpers and streaming uploads.

Retain verified bytes needed for local attempt validation in a bounded cache or
non-executable scratch. Account for encoding copies, partial uploads and tmpfs
usage. A receipt does not prove evicted bytes are locally available; return
`ARTIFACT_UNAVAILABLE` if required validation bytes cannot be retained/recovered
through an explicitly authorized contract. No arbitrary host-store fetch exists.
Never reference a provisional upload or infer commit success from a lost reply.

### 7.2 Complete typed request

Use Operator’s current v1alpha2 request schema and port the semantic validators.
Required tactical fields include origin, thread/attempt/generation/index,
payload receipt, optional carrier, explicit ordered setup actions, one application
operation/input source/media type, profile-limited observation selection (HC-03) and
cleanup choice. Release helpers may supply fixed version/kind/generator identity
and allocate bookkeeping IDs according to the shared allocator; they must not
invent selectors, payloads, setup, caller identity, invocation or cleanup choices.

Scenario origin requires a valid scenario ID. Exploratory origin must not forge
one. Retain provenance for combined scenarios in the permitted strategy record.
New roots start generation 1; children reference known same-thread parents with
generation parent+1. Distinguish an attempt's request identity from provider/local
tool-call identities. Validate unique action/attempt IDs and monotonic attempt
indices under the [shared allocator](../operator_sandbox/schemas/HARNESS_EXECUTION_RULES.md#1-campaign-wide-attempt-numbering).
The model-facing projection omits request/attempt IDs and attempt_index; the
trusted wrapper assigns them once after bounded JSON-object decoding and before
validation, without changing tactics. Seed from EngineContext's host-provided
`attempt_index_high_watermark`, then preserve local allocation across revisions.
Rejected allocated submissions retain their number; corrections get fresh IDs and
the next index. Exact duplicates reuse their tuple/result without allocation.
Malformed/non-object arguments and skipped calls allocate nothing. Operator accepts
gaps and records observed high-water marks separately from execution admissions;
never reseed from a restored native registry or infer a budget from the index.

Local validation checks exact committed artifact bytes/descriptors, media/schema,
input source, selector/placement/action compatibility, scope/lifetime, logical
path safety, expected binding, observation visibility and effective limits.
The host repeats all authorization and content checks independently. Preserve the
256 KiB argument, 512 KiB local envelope, 16 setup action, 32 diagnostic,
64 observation reference and 128-character ASCII ID ceilings.

Use only advertised native combinations. `model_tool_result`, `service_response`,
`mcp_tool_result` and `environment_state` have different selectors, modes and
lifetimes; generic structural validity is insufficient. Placement pointers are
relative to the disclosed injection root; MCP structured content and text are
distinct. Missing pointers, unmatched calls or unknown output structure do not
authorize a guessed replacement field. Validate the pinned native delivery
schema profile without stripping unsupported constraints or resolving URLs.
Consume the pinned [Interceptor delivery contract](../interceptor_sandbox/specs/delivery-contracts.md)
through Operator's source-bound projection; the guest does not discover native
contracts by contacting Interceptor or a remote MCP service.

Operator owns registration, setup, one invocation, observation and cleanup. Setup
failure prevents invocation. Cleanup failure can follow successful application
effects, and removing an injection does not undo those effects. The harness
must never call Interceptor, HTTPS targets, target reset endpoints or host-native
translation/administrative operations directly.

### 7.2.1 Explicit cleanup of retained actions

Adopt the [typed cleanup contract](../operator_sandbox/schemas/INJECTION_CLEANUP_CONTRACT.md)
and its request/result schemas. The model-facing `injection_delete` tool calls
`engine.injection_delete` with `attempt_receipt_id` from EngineAttemptResult and
one original `pre_actions[].action_id`. No native injection/session ID is exposed.
Keep these references when `delete_actions_after_observation` is false. Removal
is also safe for a known auto-cleaned action: confirmed absence returns
`already_absent`, while an unknown or never-created action is rejected.

Handles remain valid within the campaign across restores and worker attribution
changes. A restore can resurrect an already-deleted injection; issue a new cleanup
operation in the current revision when removal is desired there. Replaying an old
operation returns its historical result, not a new deletion. Cleanup does not
invoke the application, erase original feedback, undo prior side effects, restore
a checkpoint or restart the harness. On failure/unknown outcome follow terminal
rules and preserve the original operation for host reconciliation.

### 7.3 Execution disposition is separate from experimental outcome

| Host result | Harness action |
|---|---|
| `rejected`, no target contact, `correct-and-resubmit` | Return field-specific errors; allow a corrected object with a new request ID within limits. |
| `rejected`, `do-not-retry` | Do not correct/replay that operation. Follow host terminal state; otherwise record the unavailable route and select another permitted hypothesis if appropriate. |
| `completed`, known feedback | Assess delivery/effect; a known negative result can motivate a new, distinct experiment even when the original request says `do-not-retry`. That flag prohibits replay of the original effect. |
| `failed` | Execution ends even if some effects or target output are known; retain invocation/cleanup dispositions. |
| `unknown` or unknown contact/invocation/cleanup | Execution ends; preserve the original IDs and uncertainty for host reconciliation. |
| Channel loss, timeout, conflicting receipt or protocol fault | Terminal local failure; do not reconnect or submit a replacement operation. |

Same accepted ID and same canonical content may return a previously known result
under the shared host contract without another effect. This does not authorize
the harness to poll/retry a lost or unknown operation: the connection is not
resumable and reconciliation belongs to the host. Same ID with changed content
is an idempotency conflict, not a variant. No guest-generated success flag can
override the host result's execution, target-contact or cleanup disposition.

## 8. Permitted feedback must include usable content

### 8.1 Adopted observation read contract — HC-02/HC-03

Use the canonical [Operator feedback contract](../operator_sandbox/schemas/FEEDBACK_CONTRACT.md)
and current v1alpha2 attempt request/result schemas. This resolves the operation
and observation-selection design; SDK generation, broker/harness implementation
and native end-to-end qualification remain required. Older hosts without the
advertised contract are incompatible, not a reason to silently omit feedback.

`observation_selection` defaults to `{"mode":"all-permitted"}`. A selected subset
uses `{"mode":"selected","kinds":["target_output","injection_delivery"]}`.
Kinds are target_output, operation_error, injection_delivery and oracle_outcome.
Selection narrows the effective harness policy disclosed by Operator, never
broadens it. This policy intersects the native session profile, bundle request
and host restrictions. Operator preserves Interceptor's exact native profile in
AttemptContext while translating selection; Attack Harness neither chooses nor overrides
that native field. The returned manifest reports the effective harness profile.
A valid selection containing disallowed kinds produces `withheld` categories;
allowed unselected kinds are `not_requested`. If nothing permitted is selected,
execution may still proceed with basic status and a manifest with no entries;
Operator skips native feedback collection. Do not retry execution or request a
broader profile to work around withholding. Invalid kinds,
duplicates or empty selected lists fail before target effects. Changing selection
changes attempt content and requires a new submission identity.

Black-box provides target output/basic status; diagnostic adds normalized errors
and delivery facts; oracle-assisted also provides supported attributed detector
outcomes. Operator may narrow feedback further. Never request raw event logs,
private fixtures, oracle definitions or protected values through these tools.

The attempt result has a fixed feedback manifest with per-kind state, up to 64
entries and the original attempt-result receipt. Each entry has an opaque ID,
source, assurance, visibility, availability, truncation and stored-artifact identity.
Target invocation, injection application and objective achievement are distinct.
A missing delivery/oracle observation is not proof of a negative result. Current
Interceptor live oracles report positive event-backed results only; unsupported
state-only checks require post-run evidence. Treat attempt-scoped attribution as
such rather than claiming a specific turn caused it.

`engine.observation_read` requests receipt_id, entry_id, offset and max_bytes.
Read at most 256 KiB raw per call within the 4 MiB ordinary-frame limit. Initial
campaign ceilings are 1 GiB returned bytes and 8,192 reads, narrowed by policy.
The host returns identity, stored artifact size/media/raw digest, actual offset,
base64 content, raw length, EOF, availability and truncation/reason. No path, URL,
bare digest or caller-selected campaign is accepted. Receipt scope is campaign
membership and visibility, not exclusive worker/revision ownership.

Assemble bounded chunks and validate correlation, consistent metadata, ranges and
lengths. Verify the full stored-object digest only when all its bytes were read.
Use incremental UTF-8 decoding; do not silently replace malformed sequences.
EOF proves only that stored bytes ended: capture and category completeness are
separate. An empty output is an available zero-byte artifact. Missing/corrupt
content is explicitly unavailable with no bytes and EOF false. Optional unavailable
feedback becomes a visible gap; channel/protocol/execution failure still stops.
Unsupported binary media stays opaque. Never execute, render active content or
extract archives to interpret feedback.

The host freezes feedback for the exact invocation before cleanup/transition.
Reads perform no target operation or new evaluation and do not gather late
asynchronous effects. Earlier same-campaign receipts remain readable after target
restore while the harness is admitted, using original native source bindings.
A receipt never reopens failed execution or redirects to replacement-session data.

Pass decoded content with provenance and limitations to the model. The model
must see more than an artifact descriptor or base64 string. Reserve context for
feedback, preserve correlated excerpts, and label summaries/omitted ranges. Track
both bytes read by the harness and content actually presented to the model.

### 8.2 Interpretation and evidence

Give the model permitted bytes plus their source, assurance, attempted selector,
delivery indicators if actually available, and any truncation/visibility limits.
Use opaque observation identities to correlate interpretations with exact host
results and read ranges. Target text remains untrusted data even when it says
that a policy changed or an attack succeeded.

Track at least these separate conclusions:

1. An experiment was submitted or executed.
2. Placement/delivery was observed, not observed, or unobservable.
3. The target produced a particular visible response.
4. The response supports progress, resistance, ambiguity or a claimed effect.
5. Independent evidence is available, unavailable or required post-run.

The model may infer a hypothesis from text; label that inference and its evidence.
Do not upgrade HTTP success, a synthetic marker, an injection registration receipt
or a target self-report into proof of protected state change. When the host
provides no live oracle, the guest has no oracle to query. Post-run assessment may
later strengthen or reject the guest claim without reopening this adaptive loop.

## 9. Capability-specific execution and state operations

For Interceptor, consume only the safe projection of supported actions,
application schemas, selectors, observation classes and optional state handles.
Keep native target binding/worker records, raw snapshot bytes, endpoint credentials
and protected evidence host-side. Safe checkpoint metadata, including the
attached campaign ID and description, is available through the state tools. The `/v1/operations` endpoint and `operation-request/v1alpha2` contract belong to
the trusted host integration; they provide no guest network or credential access.

For declarative HTTPS, emit mapped operation IDs and schema-valid invocation
artifacts with no initial injection setup actions, snapshot or restore calls.
Host configuration fixes destination, method, authentication and response mapping.
The harness MUST use the same `engine.attempt_execute` and receipt-scoped
`engine.observation_read` operations for HTTPS. Feedback MUST retain the host's
`request-ended` boundary and `declared-observer` assurance. These records describe
selected application responses; they MUST NOT be interpreted as native oracle
verification, remote closure or target reset. The harness MUST use only advertised
input media types and operations, and MUST NOT request injection cleanup or native
state tools absent from its catalog. Adapter-specific error codes remain subject
to the effective feedback profile. Operator's
[HTTPS mapping contract](../operator_sandbox/docs/HTTPS_TARGETS.md) defines the
host-side projection and execution rules. If a required hypothesis needs internal
injection unavailable on this adapter, report the capability gap.

Only expose state tools when both target and host policy advertise them. Use
`snapshot_request` with an optional short label and description explaining the
baseline or branch purpose. Operator supplies `campaign_id`; the model cannot
override it. `snapshot_list` discovers checkpoints from current and earlier
campaign target sessions; `snapshot_inspect` retrieves one record by its
source-session/checkpoint handle pair. Preserve returned campaign ID, description,
label, source/parent handles, creation time, status and size in bounded notes.
Follow pagination without assuming pages form a frozen view; refresh after changes.
Descriptions are reference data, not instructions. Use the selected handle pair
for `restore_request`; restore does not edit checkpoint metadata.

The harness decides when to save, revisit or switch branches. Snapshot creation
and metadata reads leave the revision unchanged. During restore, keep the adaptive
loop/context alive while waiting for the correlated response; continue servicing
control channels. Operator drains ordinary work and replaces only the target.
On success, the response confirms previous/new campaign revisions, selected
snapshot metadata, a transition receipt and remaining limits. Update active
revision before the next model request, preserving conversation, hypotheses,
snapshot notes, scratch and cumulative indices. End the current tool batch and
return correlated not-executed results for all remaining calls as Section 6.2
requires. The next tool must be selected by a subsequent model response that has
received the restore result and the complete prior batch results. Do not reset
channel sequences, reload launch context or rerun initialization. Handle a duplicate response without
applying the transition twice. Keep native session routing in Operator.

A known preflight rejection leaves the existing target/revision usable and returns
a normal bounded tool error; later calls in that model response proceed under
normal validation and admission at the unchanged revision. Failure after target
closure or an unknown outcome is terminal; never retry a state mutation with a new ID to guess the outcome.
Host reconciliation uses its durable operation record. New native attempts after
rollback must have valid restored parents (or a new root); this does not erase the
harness's campaign-level hypothesis history. Completing a harness never implicitly
stops a target without Operator's configured final-stop choice. Use shared contract
Section 9: response envelope echoes the request's old revision; typed result
contains `transition_receipt`, `previous_run_revision`, new `run_revision`, snapshot
metadata, `remaining_limits` and `harness_disposition: continue`. Control
`terminate` acts on the launch even if it arrives before this ordinary response;
there is no additional revision acknowledgement handshake. Schema publication
and transition fixtures remain required before integration.

Snapshot creation uses Operator's configurable campaign defaults of 20 admissions
and 1 GiB (1,073,741,824 bytes) of cumulative committed canonical file bytes.
`engine.snapshot_request` still accepts only optional label/description. Operator
supplies the remaining native-call allowance; the harness cannot override it.
Admitted requests consume one admission even on known failure; successful
checkpoints consume their complete `canonical_size_bytes` once, including repeated
or deduplicated files. Restores and deletion do not replenish these budgets.
Retain the remaining limits delivered by Operator and handle known exhaustion as
a bounded tool error; do not resubmit an uncertain mutation with a new ID.

## 10. Coverage, limits and stopping

Maintain structured coverage for original scenarios and exploratory work:
objective/hypothesis IDs, selected surface/variation, attempted and observed
stages, evidence, conditional goal triggers and reason for each gap. Suggested
coverage is resolved by evidence or an explicit limitation; merely loading a
scenario, generating a payload or skipping a branch never counts as testing it.
Do not claim exhaustive search from a finite set of attempts.

Stop gracefully when the model supplies a valid finish request, objectives have
sufficient permitted evidence, further variants are uninformative, compatible
work is exhausted, context cannot be retained safely, or remaining resources
cannot support another experiment. These are recorded reasons, not declarations
of independently verified success. Host budget/admission decisions always win.

Consume initial host ceilings: 100 durably admitted attempts (not allocated indices), 30 minutes and 250,000 cumulative
input+output model tokens; at most 120 seconds per model request; 2 CPU equivalents,
4 GiB RAM without swap, 256 descriptors and the artifact spec's work/tmp bounds.
These are maximums, not guaranteed allocations. Use the smaller release, host,
target, operation and remaining limit. Unknown usage is not zero. Report stop
without new effects if initialized with no experimental budget remaining.

Never wait for an additional reasoning/conclusion call when a hard stop is due.
An internal counter or heartbeat cannot keep the guest alive after Operator ends
execution. No automatic restart after failure, provider refusal escalation,
fallback target route or campaign budget reset exists.

## 11. Structured conclusion and completion

The model supplies bounded conclusion data through the typed local finish tool;
the deterministic handler validates schema and reference campaign association/correlation.
The orchestrator may produce a deterministic partial conclusion from recorded
facts when a graceful limit is reached and no further model generation is possible.
It must not invent claims or require provider structured-output support to finish.

The accepted `operator.dev/engine-conclusion/v1alpha2` contract requires:

- host-bound campaign/launch/final revision and input/release/skill/prompt/contract identities;
- objectives, investigated hypotheses, scenario/exploratory lineage and decisions;
- known attempt/result/observation receipts and supporting content ranges;
- claimed effects separated from execution status, inference and assurance;
- unresolved effects, optional omissions, unread context and compaction gaps;
- coverage, untested alternatives, remaining uncertainty and finish reason.

Use the shared Section 10 bounds: 1 MiB encoded conclusion, 8,192-character
summary, 100 claims, 100 objectives and hypotheses each, 100 gaps and 256 record
references, plus the defined field/reference limits. Preserve explicit partial
coverage if history cannot fit; commit detailed history separately. Retain statuses
`completed`, `partial`, `failed` and interpretations `supported`, `inconclusive`,
`not-observed`. Conclusion
`completed` means report completion, not successful exploitation. Reference
verification establishes that evidence exists, not that a model's interpretation
is correct. Mark unsupported evidence claims as inconclusive or reject the draft
for bounded correction; never manufacture an observation ID.

Graceful finalization is ordered and uses the same ordinary-operation scheduler:

1. Validate and serialize the structured conclusion within its exact schema.
2. Publish and obtain its committed artifact receipt.
3. Append the typed conclusion reference/finish record and receive its receipt.
4. Send `engine.request_stop` with `finish_reason` and a committed conclusion
   containing `artifact_receipt` and `record_receipt`, matching the record/content.
   If no conclusion can be produced, use the explicit unavailable variant and
   reason from shared Section 11; never invent receipts.
5. Consume the ordinary correlated accepted result with saved `stop_receipt`,
   closed execution admission, conclusion state, required exit within 5,000 ms
   and finalization pending. Send no further ordinary work and exit. This is not
   confirmation of completed target export, assessment or host-observed exit.

Reserve up to 1 MiB in the existing artifact budget and one conclusion slot, and
begin finalization with up to 30 seconds inside the hard campaign deadline.
Only conclusion artifact/record/stop operations remain admissible; do not request
another model/target experiment. If hard failure or exhaustion requires immediate
termination, retain partial records without extending the campaign.

Do not repeat an upload, record or stop request after an ambiguous failure. Exit
zero or stdout prose is insufficient proof of completion. Immediate termination
skips any pending reporting and leaves the host's partial records authoritative.
Logs carry bounded operational diagnostics without prompt/payload bodies, raw
observations or credentials; artifact/record operations are the output channel.

## 12. Functional acceptance fixtures

All criteria below are **not implemented / not run**. `AIH-AC` covers harness
functionality and complements the artifact spec's `AHC-AC` native gates.
Use synthetic local target data and scripted provider responses for deterministic
assertions; separately test actual provider/host/native integration. A scripted
model fixture must still traverse real harness codecs, tools, byte transfer and
state transitions, not call an alternate test-only adaptive loop.

| ID | Required evidence |
|---|---|
| AIH-AC-001 | Missing/corrupt/extra inputs, incompatible bundle/capability bindings and incomplete skills prevent all ordinary requests; empty and nonempty exact skill sets initialize. |
| AIH-AC-002 | Default, replacement and ordered-extension prompt bytes survive every provider turn and compaction without hidden base reinsertion; instruction-bearing data cannot register a tool. |
| AIH-AC-003 | Objectives-only and multi-scenario portfolios preserve supplied optional catalog/context/source provenance, required/optional routes, original bundle access, reference read ranges, omissions and untested coverage. |
| AIH-AC-004 | A scripted model creates and commits an injection payload and separate valid trigger, submits the explicit attempt, reads returned observation bytes, changes its payload after a known negative result, submits a child attempt and commits an evidence-referenced conclusion. Assert exact bytes and identities at each boundary. |
| AIH-AC-005 | Direct-input and exploratory-origin experiments work; the dispatcher permits a capability-valid unlisted hypothesis, while missing capabilities cannot be supplied by scenario prose. |
| AIH-AC-006 | Shared allocator fixtures cover rejected 7 → corrected 8, local-only gaps, malformed/skipped calls, duplicates, admission counts and restore/overflow boundaries. Full request and semantic checks reject invalid lineage, artifact/media/selector/placement combinations, unavailable bytes and oversized/prose arguments before target contact. Correctable rejection leads to a new request ID, not changed content under an old one. |
| AIH-AC-007 | `completed` negative feedback allows adaptation; `failed`, unknown cleanup, timeout or channel loss prevents every later queued effect. Retained known effects and original IDs survive in partial reporting. |
| AIH-AC-008 | Observation reads deny forged/cross-run receipts, hidden evidence and arbitrary digest/path lookup; chunking, UTF-8 boundaries, partial/full hash verification, truncation and unavailable feedback remain explicit. |
| AIH-AC-009 | Native multi-tool responses execute serially with exact call/result ordering; duplicate IDs, malformed/truncated responses, unsupported semantics and no-progress turns are bounded. Every advertised provider route has real non-streaming text/tool/follow-up qualification. |
| AIH-AC-010 | Oversized bundle/context and long conversations exercise incremental reads and compaction without losing system bytes, required continuation fields, lineage or uncertainty; impossible mandatory context fit stops explicitly. |
| AIH-AC-011 | Declarative HTTPS uses only mapped input operations and external-response assurance; Interceptor uses its exact projected injection roots and source-bound schema dialect. No guessed selector after missing-pointer feedback. |
| AIH-AC-012 | Every effective loop default/override, exact boundary, invalid-call streak, repeated read, no-progress case, compaction charge and bounded model-free finalization follows shared execution-rule traces. Paused reads/writes, worst-case parsing and model/target waits keep control responsive; finite queues, token/time budgets and independent host stop prevent further dispatch. |
| AIH-AC-013 | Graceful completion commits conclusion, record and stop in order; lost receipts and hard stop do not trigger replay or delay termination; unsupported effect claims remain inconclusive. |
| AIH-AC-014 | Successful restore skips every remaining call in its model response with correlated `not_executed` / `TARGET_REVISION_CHANGED` results and supplies the complete segment to the next model generation; cover reads, helpers, second restore/stop, duplicate response, compaction and terminate races per shared Section 9.1. Permitted healthy restore retains loop/conversation/hypotheses/scratch/channels, adopts the confirmed new active revision once and preserves cumulative limits. Create/list/inspect round-trip campaign ID and description across earlier sessions. Known preflight rejection continues unchanged; post-closure failure/uncertainty terminates. Unsupported state tools are absent. |
| AIH-AC-015 | Shared package version/digest, exact five-message startup, manifest bounds, call/operation identity, bounded errors/queues/deadlines and restore/control ordering match Go/Python golden fixtures and real FIFO and file-spool traces through accepted stop. Cover cumulative spool ACKs, producer deletion, five-second transport deadlines, ordinary/control priority and failed publication. Explicit missing conclusions, lost acknowledgements and expected teardown retain correct finalization status. |

For AIH-AC-004 use a benign marker-in-response hypothesis. The fake target first
records known delivery without the marker, then a distinct completed experiment
returns the marker. The conclusion claims only observed response influence in
that fixture, with both receipts, not arbitrary protected compromise. Add variants
for no observed delivery, partial response, target self-report without corroboration,
and a cleanup-unknown result that stops before the next planned call. Keep marker
and capability fixtures identified as synthetic and independent of production data.

## 13. Implementation milestones and handoff evidence

1. **Contracts and runtime feasibility:** publish the accepted package and complete
   HC-01–HC-06 implementation/qualification gates with the shared owner; pin exact
   version/content digest and pass shared Go/Python fixtures. Prove Linux FIFO/macOS spool bootstrap, confinement
   and responsive event loop before selecting incompatible dependencies.
2. **Guest foundation:** package/bootstrap, strict FIFO/spool scheduler, immutable input
   and skill verification, prompt handling, artifact commit and receipt cache.
3. **Adaptive vertical slice:** one native codec route, fixed tools including
   observation reads, multi-turn hypothesis/refinement, coverage and conclusion
   through a fake host. Complete AIH-AC-004, including actual feedback bytes.
4. **Breadth and failure handling:** provider variants, source-bound target schema
   checks, bounded context, exploratory branching, state operations and fault cases.
5. **Build and qualification:** implement the Dockerfile and release pipeline in
   [the artifact spec](GUEST_ARTIFACT_LAYOUT_SPEC.md#41-container-build-deliverables),
   then qualify the final Linux images with Operator on Linux/macOS amd64 and arm64
   hosts, including journaling and Docker termination failures.

The implementation session must leave reproducible commands, dependency/schema
locks, generated-artifact drift checks, fixture outputs, actual image digests and
an acceptance matrix recording pass/fail/not-run and environment/source identity.
Keep component, fake-host, real-provider, native-target and native-container
evidence separate. If Operator schemas or native integration remain unavailable,
complete independently testable code and document the precise remaining gates;
do not silently replace production paths with test doubles or mark the task fully
integrated. The build files and runtime implementation described here are future
deliverables; this specification does not claim they already exist.
