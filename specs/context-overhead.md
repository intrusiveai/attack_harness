# Recurring model context contract

Harness MUST reduce repeated request content without changing the shared tool
schemas, canonical reference identities, runtime validation, evidence retention,
model reservations, or configured campaign limits. This change builds on
`52f0678` and remains local to Harness.

## Required behavior

- `composition.py` MUST project input descriptors for model discovery: exact
  `entry_id`, purpose/role, useful media/size and skill identity, and a bounded
  descriptive source name where needed. Full descriptors MUST stay in verified
  `Inputs`; reading a projected handle MUST use existing verification.
- Task context MUST preserve complete active-scenario requirements, bundle
  completion guidance, objective IDs, and discovery of deferred references.
  Portfolio IDs/counts MUST describe the submitted inventory, not stale progress.
- The privileged prompt MUST retain instruction boundaries and stable execution
  guidance. Task context MUST retain the shared minimal finish example with an
  actual objective ID and readable-handle/citation example. Uncertainty labels
  MUST remain explained. Larger optional examples and repeated enum lists SHOULD
  remain in existing shared tool guides/schemas rather than every task message.
- Independent evidence reads SHOULD share one model response within existing
  call limits. Dependent requests MUST wait for their prerequisites. No speculative
  prefetching or target replay is permitted.
- Dispatcher MUST retain the exact latest rejected finish and diagnostic. One
  current repair block MUST carry its correction; original arguments MAY be
  referenced by native call identity while retained, but MUST be included exactly
  after that exchange is omitted. Duplicate-key input MUST NOT be rewritten.
  Model-facing result/reminder projections MUST NOT replace canonical records.
- `NativeConversation` MUST use deterministic fresh-conversation checkpoints at
  the existing context warning threshold, rather than dropping a prefix beneath
  retained reasoning. Recent bounded evidence MAY carry forward as attributed
  task data. Mandatory context MUST NOT be omitted to meet a soft headroom target;
  if it cannot fit, use the existing context-limit/unavailable finish.
- The adaptive loop MUST NOT purchase model-generated summaries. Existing summary
  interpretation/provenance helpers MUST continue to treat supplied historical
  summaries as subordinate to original requirements and independent repair state.
- Reduction MUST preserve small factual associations from the verified resource
  map: execution origin/scenario, its observations and permitted ranges, inspected
  citations, and whether their bytes remain in this prompt. Other returned handle
  categories and unresolved corrections MUST remain available. No target prose or
  model-generated summary may establish handles, authorization, or objective success.
- Inspected evidence MUST remain distinct from present evidence content and from
  available rereadable evidence. Claims requiring omitted content MUST reread it
  or report the limitation. Whole unread observations MUST remain invalid citations.
- Assessment repair and protected finalization MUST remain sticky dispatch
  restrictions, including same-response batches. Local reduction MUST NOT reset
  counters, charge tokens, alter reservations, or weaken native codec checks.
  Full request/response and evidence records MUST remain intact outside the prompt.

## Verification and delivery

Controlled tests MUST cover exact reference discovery/readability; complete and
oversized scenario delivery; accepted execution/scenario/observation associations;
partial-range citation integrity; local and host finish correction without replay;
duplicate-key repair through reduction; target-content boundaries; protected
finalization; irreducible context; and complete native groups across all five codecs.
Representative separate Operator/Harness FIFO and spool processes MUST still
complete inspection, accepted assessment, exit, cleanup and retained evidence.

`build/measure_context.py` MUST run the same input fixtures and controlled response
policy against the baseline and changed sources. Report serialized request bytes,
local estimates, compaction calls, evidence reads/rereads, unchanged tool-schema
bytes, and cumulative overhead including rereads. Record actual provider usage as
unavailable when none was measured; synthetic fixture accounting MUST NOT be
reported as live token savings. Include request-size regressions as well as savings.
No paid cloud campaign or release publication is part of this verification.

[Append-only conversations](append-only-conversations.md) supersedes any older
requirement to rewrite task messages or retain native suffixes after trimming.
