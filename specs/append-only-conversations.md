# Append-only model conversations and campaign checkpoints

This specification supersedes requirements to refresh or replace past task
messages and to trim a prefix while retaining later native reasoning. Campaign
state remains continuous; only the model's working conversation is renewed.

## Conversation ownership

- Harness MUST keep each submitted conversation append-only. Previously submitted
  messages and returned assistant blocks, including opaque thinking/signatures,
  MUST remain unchanged and in order. A local prefix invariant MUST detect
  accidental changes before another provider request. Frozen model policy and
  tool definitions MUST remain unchanged; Operator's effective request assembly
  MUST be checked for compatible behavior.
- Mutable campaign state MUST remain in existing Harness services: execution and
  evidence records, typed handles, snapshots/restore lineage, budgets, deadlines,
  retry/no-progress counters, duplicate protection, active scenario and repair.
  A new model conversation MUST NOT reset these or replay operations.
- Ordinary tool results MUST provide incremental progress. Harness MUST NOT
  regenerate the initial activity/evidence tables on every request. New notices
  MUST be appended or included in a new checkpoint, never inserted into a prior
  conversation prefix. No extra model call or acknowledgment is required.

## Checkpoint boundaries

- Initial context, scenario activation/switch/revisit, the existing context
  warning/size threshold and entry into protected finalization or assessment
  repair MUST use deterministic checkpoints. A checkpoint MUST start a fresh
  native conversation, with no old native thinking, assistant/tool-call groups,
  provider continuation IDs or orphaned tool results. Original audit exchanges
  MUST remain untouched.
- Harness MUST first resolve the entire current tool-call batch, including skipped
  calls and same-batch restrictions. Checkpoints MUST only be applied at a
  quiescent model-request boundary. Pending/uncertain host operations MUST NOT be
  retried to create a checkpoint. The existing terminal behavior for uncertain
  effects MUST remain intact.
- Scenario instructions MUST remain complete. Selection MUST still withhold
  same-response attempts until the model receives the new instructions. A switch
  MUST NOT imply completion of the prior scenario. Revisits MUST restore retained
  activity and permit selective evidence reads within the current phase.
- A checkpoint MUST include campaign objectives, restrictions, sequencing and
  completion requirements, the full compact scenario index, complete active
  instructions when applicable, concise factual activity/evidence references,
  snapshot dependencies, unresolved corrections and the current phase.
- Finalization checkpoints MUST present campaign-wide execution/activity and
  evidence records, including unvisited scenarios and explicit limits on what
  execution establishes. The model MUST be able to selectively revisit scenario
  requirements and evidence without reopening exploration. Ordinary accepted
  finish MUST not be delayed for another assessment or a synthetic checkpoint.
- A rejected finish MUST preserve its exact submitted bytes and diagnostic in
  the checkpoint. Subsequent corrections MUST use native result feedback without
  rewriting past messages. Repair restrictions MUST remain enforced independently
  of the conversation and survive any further checkpoint.

## Evidence, cost and trust

- Evidence previously inspected, content present in this conversation and content
  available for rereading MUST remain distinct. Checkpoints MUST preserve typed
  identities/ranges from verified state, not infer them from target text.
- A small bounded selection of recent observation/reference content MAY be
  retained as attributed task data, without native call wrappers or reasoning.
  Selection MUST use verified tool results; raw target content MUST not establish
  handles, authorizations or objective achievement. Omitted content MUST be
  explicit and rereadable; omitted evidence MUST not be marked newly inspected.
- Activity snapshots describe history as of the checkpoint. Subsequent tool
  results advance that history; executing an operation MUST NOT imply satisfying
  a scenario or objective. Caller rationales remain stated intent.
- Local checkpoint construction MUST NOT invoke a model, change token accounting
  or lower reservations. Exploration/model summaries MUST NOT consume the existing
  two-request finalization reserve. Automatic model summarization is out of scope;
  any explicitly supplied summary remains subordinate, attributed interpretation.
- Mandatory context that cannot fit MUST yield the existing context-limit and
  bounded unavailable-finish path. Budgets, invalid/no-progress limits, deadlines
  and cleanup MUST remain in force. Accepted finish, successful assessment and
  completed cleanup MUST remain distinct.

## Implementation and verification

### Continuity across scenario revisits

- Checkpoints MUST retain a bounded recent navigation trail, per-scenario selection
  counts, the current no-progress count/limit, and the persistent assessment phase.
  Repeated selection MUST NOT count as substantive progress or reset limits.
- Harness MUST retain the latest bounded public model note for each scenario and
  for campaign-wide assessment. Notes SHOULD state assessed requirements, cited
  evidence, unresolved obligations and the purpose of a revisit. Notes MUST be
  attributed as model interpretation, never verified facts, authorization or a
  committed assessment. Tool-only responses MUST NOT erase earlier notes. Native
  reasoning/thinking blocks MUST NOT be extracted into checkpoint notes.
- Accepted optional `record_append` content MUST remain associated with its verified
  record handle and the scenario active when submitted. Checkpoints MUST expose a
  bounded projection of those records, with explicit omissions. Acceptance proves
  retention, not the truth of the model's assessment. No record or note is required
  to execute or finish. Original records MUST remain unchanged.
- When a repeated navigation-only turn leaves at most two turns before the
  existing no-progress limit, Harness MUST enter restricted assessment review
  before the next model request. The transition MUST retain its distinct reason,
  use existing finalization action restrictions, and MUST NOT close execution
  admission before an accepted finish. Scenario revisits MUST NOT leave this phase.
  Budget, deadline and invalid/no-progress limits MUST remain unchanged; this is
  an opportunity to finish, not a guarantee of an accepted assessment.
- Transition, review, and repair MUST retain campaign-wide facts and model notes
  separately. Invocation success MUST NOT trigger inferred requirement completion.
  There MUST be no new model tool, shared contract, planner or model-summary call.
- Controlled native conversation tests MUST complete multiple scenarios, retain
  notes/records and evidence through repeated reviews, correct a rejected finish,
  and finish without another target invocation. Cover all codecs, same-batch
  restrictions, unchanged signed prefixes, bounded omissions, and an uncooperative
  model reaching the unchanged no-progress limit with no committed assessment.

Reuse `NativeConversation`, `ScenarioDelivery`, `ModelTools.context_facts`, native
codec continuations and the existing dispatcher/finalizer. No new tool, provider
service, parallel compatibility mechanism or campaign ledger is required.
Update conflicting context/scenario/repair specs, tests and integration docs.

Tests MUST inspect actual native requests across all five codecs. A controlled
prefix-checking provider MUST reproduce the reported thinking + observation-read
sequence and reject any mutation of its earlier prefix. Cover phase changes,
scenario switches/revisits, same-batch selection guards, long-scenario reduction,
partial evidence, retained recent content and omitted-content rereading, exact
rejected assessments, malformed tool recovery, snapshot/restore, finalization
across scenarios, exhaustion and irreducible context. Checkpointing MUST incur
no model-summary calls and MUST not replay target operations. Native assistant
blocks MUST round-trip intact within a conversation, and old signatures MUST
never appear in a fresh checkpoint conversation.

Verify matching Operator/Harness FIFO and spool processes through evidence reads,
accepted finish, exit zero, cleanup and export. Compare serialized request sizes
and cumulative input using the same controlled workflow, including evidence
rereads; distinguish bytes and local estimates from real provider usage. Controlled
checks do not establish live-provider acceptance or reasoning quality. No paid
cloud run or release publication is authorized by this implementation.
