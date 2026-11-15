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
- Harness MUST NOT copy arbitrary public commentary, text prefixes or native
  reasoning into checkpoint notes. Verified activity/evidence remains product-owned.
- Purpose-built model handoffs MUST use the shared `record_progress` tool
  with a nonempty `summary`, an optional `decision`, and its
  existing validated reference fields. Summary SHOULD identify requirements
  assessed, findings and unresolved obligations; decision SHOULD identify the next
  step or specific revisit purpose. No new shared schema or semantic keyword
  validator is permitted. Missing model assessments MUST be explicit, not inferred.
- The complete canonical progress arguments MUST fit a per-handoff allowance of
  min(2048, floor(16384 / (scenario count + 1))) bytes. The extra slot is for
  campaign-wide review. Harness MUST disclose this allowance in task guidance.
  An oversized handoff MUST receive a correctable pre-send
  diagnostic. It MUST NOT be truncated, retained at Operator, or replace the last
  accepted handoff. Shared argument/reference validation remains authoritative.
- Harness MUST keep the latest complete validated handoff for each scenario and
  campaign-wide review, including its accepted record handle when available and submission scope. It MUST
  replace that scope's previous handoff rather than accumulate prose. Model
  assertions MUST remain separate from verified facts and MUST NOT imply assessed
  success or amend requirements. Superseded records remain in the audit history.
  Model guidance MUST require carrying forward unresolved obligations when revising
  a handoff; structural validation cannot establish the truth/completeness of prose.
- A host `gap-and-continue` rejection after shared/local validation (for example,
  the existing progress-record rate limit) MUST NOT become a correction/retry gate.
  Harness MUST retain the complete validated handoff locally with the host rejection,
  explicitly marked `harness-only`, without an accepted record handle. It MUST
  preserve the original disposition and allow navigation. It MUST NOT bypass the
  host limit, retry automatically, or promote local retention to host acceptance.
- A correctable rejected progress handoff MUST preserve its exact submission and correction.
  Subsequent scenario selection in that batch MUST be withheld. A selection queued
  earlier in the same batch MUST be cancelled before delivering a new task, with
  that cancellation made explicit. Current native history MUST remain available
  for correction while it fits; forced context renewal MUST preserve the rejected
  handoff, or fail honestly if mandatory context cannot fit.
- An accepted corrected handoff MUST clear only handoff rejection state, never
  assessment repair or restricted finalization. Progress handoff records MAY be
  submitted during finalization/repair; other optional record kinds remain blocked.
  No handoff is a prerequisite for a valid finish, deadline enforcement, or cleanup.
  Checkpoints without a submitted assessment MUST report that absence and preserve
  verified facts; they MUST NOT manufacture assessment prose or another model call.
- When a repeated navigation-only turn leaves at most two turns before the
  existing no-progress limit, Harness MUST enter restricted assessment review
  before the next model request. The transition MUST retain its distinct reason,
  use existing finalization action restrictions, and MUST NOT close execution
  admission before an accepted finish. Scenario revisits MUST NOT leave this phase.
  Budget, deadline and invalid/no-progress limits MUST remain unchanged; this is
  an opportunity to finish, not a guarantee of an accepted assessment.
- Transition, review, and repair MUST retain campaign-wide facts and complete model handoffs
  separately. Invocation success MUST NOT trigger inferred requirement completion.
  There MUST be no new model tool, shared contract, planner or model-summary call.
- Controlled native conversation tests MUST complete multiple scenarios, retain
  handoffs/records and evidence through repeated reviews, correct a rejected finish,
  and finish without another target invocation. Cover all codecs, same-batch
  restrictions, unchanged signed prefixes, whole-record limits, and an uncooperative
  model reaching the unchanged no-progress limit with no committed assessment.
- Tests MUST cover an oversized replacement with a material unresolved finding at
  its end, a concise correction preserving that finding, and both orders of
  same-batch record/selection calls. The failed submission MUST reach neither
  Operator's record store nor a partial accepted handoff. Shared reference errors,
  duplicate JSON keys and correctable Operator rejections MUST retain corrections.
  Host rate-limit gaps MUST retain whole local assertions without false record handles. A forced
  checkpoint MUST carry the whole rejected submission and last accepted handoff.
  A replacement MUST supersede only its delivered scenario's handoff, including
  when a later selection in the same response names another scenario. Matching
  process tests MUST verify accepted finish, exit zero, cleanup and exported
  scenario attribution without target replay.

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
