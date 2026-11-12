# Focused model context

This change simplifies presentation while preserving the active-scenario workflow,
shared contract, native codecs, dispatch, evidence verification and accounting.

## Required behavior

- The privileged prompt MUST state purpose, campaign scope, source trust,
  investigative relevance, safe handle use, uncertainty and campaign-wide finish.
  It MUST NOT contain target-specific examples, backend architecture, database
  mechanics or argument tutorials. It SHOULD remain below 2 KiB.
- `composition.py` MUST present campaign-wide requirements, a scenario index, one
  complete active scenario, operation input requirements and relevant verified
  facts. Producer/integrity/adapter identifiers and startup accounting dictionaries
  MUST remain internal. Target input schemas and complete active requirements MUST
  NOT be recursively filtered or summarized. Submitted completion and sequencing
  guidance MUST remain intact; priority is not a dependency specification.
- The scenario index MUST keep original handles and distinguish delivered
  instructions from execution handles. Evidence facts MUST distinguish inspection
  from content still in the prompt and objective achievement. Snapshot readiness,
  parentage and restore associations MUST survive switching and trimming.
- Scenario activation MUST replace instructions without adding their body to tool
  history. The confirmation MUST identify instructions as present in the current
  task. Existing delivery-generation guards MUST prevent same-response execution
  before those instructions have reached the model; no acknowledgment is added.
- Reference discovery MUST omit the prompt, execution-context dump, original bundle
  and repeated guide inventory. Supporting documents and target details MUST remain
  discoverable where useful. Lookup, identities and byte verification MUST remain
  unchanged. Detailed examples stay in the existing shared tool guides.
- `model_tools.py` MUST compact confirmed ordinary success only. Error, partial
  feedback and uncertain effects MUST retain meaningful stage, cleanup and retry
  facts. The complete host result MUST remain retained by execution services/audit.
- Complete, uniquely keyed, supported JSON observation bytes MAY be displayed as
  JSON values. Partial pages, invalid/duplicate-key JSON and binary data MUST retain
  their lossless existing presentation. The model view MUST keep every target field,
  source/evidentiary meaning, byte extent, truncation and continuation. Nested JSON
  strings MUST NOT be peeled or treated as transport metadata. Neither JSON content
  nor target prose may create trusted handles or progress facts during trimming.
- Empty oracle feedback MUST be described as absence of a positive verdict, not
  evidence of attack success or failure.
- Existing complete-group history reduction MUST remain the only history manager.
  Full evidence stays retained. Assessment repair, precise corrections, protected
  finalization and honest context-limit termination MUST remain enforced.

## Shared catalog boundary

Harness MUST NOT locally rewrite shared descriptions, schemas or frozen selection.
The requested catalog corrections require Operator's generated interface change.
The user requested a handoff rather than Operator implementation in this branch:
[Operator coordination](../../maintainers/attack_harness/operator-context-presentation.md). Until adopted,
the existing tool descriptions, including their known limitations, remain intact.
No contract pin or compatibility identity changes as part of this Harness-local work.

## Verification

MUST exercise actual native provider requests and controlled multi-scenario
conversation/dispatch: activation → action → inspect → next scenario, snapshot and
restore, history trimming, earlier evidence citations, rejected assessment repair,
accepted incomplete assessment, process exit and confirmed cleanup. Tests MUST
cover all supported codecs, wrong-handle/field corrections, duplicate JSON,
untrusted content handles and mandatory context failure.

Measurements MUST use the same controlled sequence and inputs before/after,
report prompt/task/tool/history bytes separately, and include total request bytes,
model calls, summaries and rereads. Archive reconstructions MUST be distinguished
from recorded requests and actual usage. Controlled results and smaller prompts
MUST NOT be described as proving live-model improvement. No paid run or release
publication is authorized here.
