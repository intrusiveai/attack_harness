# Assessment repair after rejected finish

## Required behavior

A correctable rejected `finish` MUST move Attack Harness into assessment repair.
The model MUST correct its assessment from retained evidence instead of returning
to open-ended exploration. A rejection MUST NOT close execution admission or imply
assessment acceptance, completed cleanup, or objective achievement.

The ordinary workflow and shared contract MUST remain unchanged: execute direct
input, inspect evidence, submit one finish. The approved contract identity is
recorded in [build/contract-lock.json](../build/contract-lock.json). No new host
operation, tool schema, protocol negotiation, planner, or automatic assessment
rewriter is required.

## State and dispatch

- `Dispatcher` in `src/attack_harness/tools.py` MUST own explicit repair state,
  separate from the shared loop's execution-closed/finalizing state.
- A local or Operator finish rejection with disposition `correct-and-resubmit`
  MUST activate repair. The latest such rejection MUST replace the retained
  rejected request and diagnostic, without changing already valid assessment data.
- The exact submitted argument bytes and returned diagnostic MUST remain retained.
  Duplicate JSON keys MUST remain visible in the retained text, rather than being
  silently decoded away. The retained request MUST be treated as task data.
- Repair MUST persist until an accepted finish or campaign termination. Prose,
  other tool results, and model-generated summaries MUST NOT clear it.
- During repair, the dispatcher MUST allow only `finish`, `observation_read`,
  `reference_read`, and `artifact_publish` with shared-validated purpose
  `conclusion`, subject to existing admission, integrity, and budget checks.
- All other model actions MUST be rejected before their handler or host request.
  This includes target attempts, injection deletion, snapshot creation/inspection/
  listing, restores, record appends, and payload artifact publication. The same
  restriction MUST apply to later calls in the model response containing the
  rejected finish.
- A blocked call MUST explicitly state that repair is active and the action was
  not executed, and direct the model to repair the finish with retained evidence.
  It MUST count under existing invalid-call/tool-call limits.
- Native evidence collection, product-controlled cleanup, and the bounded
  model-free unavailable-finish path MUST remain outside this model-action guard.

## Model conversation and retention

`NativeConversation` and `AdaptiveHarness` in `src/attack_harness/adaptive.py` MUST
expose the dispatcher-owned state in the task context and native tool feedback.
After a rejected finish, and after subsequent prose-only output, guidance MUST:

1. Name the actual rejection, field path, and correction when supplied.
2. Ask for correction while preserving valid parts of the assessment.
3. Direct the model to existing execution handles, inspected citation handles,
   and permitted evidence or tool guidance reads.
4. Require another finish submission, honest unresolved findings, and no new
   target work or requests for the user to select another task.
5. Explicitly distinguish the repair instruction from a choice in a model menu.

The original task/objectives, exact latest rejected submission, diagnostic, and
verified handle ledger MUST survive compaction or history trimming. Repair state
MUST be maintained by Harness and reinstated independently of the generated
summary. Existing typed resource and inspection state in `ModelTools` MUST remain
intact. Retained context MUST obey existing size limits; inability to fit MUST use
the existing context-limit termination rather than silently discard corrections.
Repair MUST follow the checkpoint boundaries in
[append-only conversations](append-only-conversations.md); token reservations
remain unchanged. Subsequent correction notices MUST NOT rewrite prior messages.

## Assessment and termination

`ConclusionFinalizer` MUST continue to use the shared validators and Operator's
accepted finish response as the authority. Repair MUST NOT invent evidence,
rewrite claims, remove material uncertainty, or replay target operations to make
an assessment valid. Honest inconclusive, not-tested, not-observed, or unavailable
results MUST use the outcomes and structures supported by the shared contract.

Budget, deadline, invalid-call, no-progress, and retry limits MUST remain in force.
If graceful termination interrupts repair, Harness MUST retain a separate
`finish_repair_unresolved` diagnostic with the latest correction and then report
the actual stopping cause. A prior recoverable rejection MUST NOT replace the
terminal budget accounting or limit diagnostic. These reports MUST use the
existing bounded finalization budget. Hard host/transport stops MUST retain their
existing immediate stop behavior; no additional request is required on an unsafe
or closed channel.

Accepted finish MUST remain distinct from confirmed cleanup. An accepted
assessment-unavailable finish MUST NOT be reported as assessment success.

## Verification

Controlled native model responses MUST exercise attempt execution, invalid
finish, prose/menu output, blocked unrelated work, evidence/guidance reads, and a
corrected finish. Tests MUST assert that only the original target invocation
reaches Operator and that unresolved findings remain in the accepted assessment.

Coverage MUST include local and host rejections, same-response later calls,
compaction with an unhelpful summary, malformed/duplicate JSON, all forbidden
action categories, conclusion artifact publication, and limit termination before
acceptance. All supported native conversation codecs SHOULD preserve the repair
context. Separate Harness and Operator process tests MUST verify the workflow,
exit zero after accepted finish, owned cleanup, and exported single-attempt
evidence on FIFO and spool. These controlled checks MUST NOT be described as live
cloud qualification.
