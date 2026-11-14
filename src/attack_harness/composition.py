"""Fixed post-admission composition root for one campaign process."""

from dataclasses import dataclass
from copy import deepcopy
import json
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import HarnessLoop
from operator_contracts.target_context import compact_target_context
from operator_contracts.validation import decode, ORDINARY_LIMIT

from .adaptive import AdaptiveHarness, NativeConversation
from .artifacts import ArtifactPublisher
from .attempts import AttemptExecutor
from .conclusion import ConclusionFinalizer
from .handlers import FixedHandlers
from .observations import ObservationReader
from .tools import Dispatcher, ToolError


TASK_LIMIT = 768 << 10
SCENARIO_CONTEXT_MESSAGE = "Complete active scenario and required campaign context exceed the task context limit."
TASK_CONTEXT_MESSAGE = "Required campaign context exceeds the task context limit."


def _scenario_references(bundle):
    return [{"scenario_id": scenario["scenario_id"],
             "description": scenario.get("hypothesis", "")[:256],
             **{k: scenario[k] for k in ("required", "priority", "objective_refs") if k in scenario},
             "reference_id": "scenario-" + raw_digest(_canonical_value(
                 {"bundle_id": bundle.get("bundle_id", ""), "scenario_id": scenario["scenario_id"]}, 1024))[7:]}
            for scenario in bundle["scenarios"]]


def _target_view(inputs, context):
    """Presentation only: shared references and runtime capability checks stay intact."""
    raw, resources = compact_target_context(inputs._protocol,
        _canonical_value(context["target"], ORDINARY_LIMIT))
    for identifier, content in resources.items():
        _, retained = inputs.entry(identifier)
        if retained != content:
            raise ContractError("Target detail reference differs from verified startup.")
    caps = decode(raw, ORDINARY_LIMIT)["capabilities"]
    operations = []
    for item in caps["operations"]:
        delivery = item.get("delivery", {})
        entry = {"operation_id": item["operation_id"]}
        if delivery.get("description"):
            entry["purpose"] = delivery["description"]
        if "input" in delivery:
            # Do not walk the input schema: names like 'source' or 'basis' may
            # be actual target arguments. Only remove known envelope metadata.
            entry["input"] = {k: v for k, v in delivery["input"].items() if k != "basis"}
        else:
            entry["details_reference"] = item["details_reference"]
        operations.append(entry)
    result = {"operations": operations}
    selected = context["model"]["tool_selection"]["injection_surfaces"]
    if "model_response" in selected and "engine.injection_delete" in context["operations"]:
        action = next((a for a in caps.get("actions", []) if a.get("surface") == "model_response"), None)
        if action is not None:
            result["model_response"] = {k: action[k] for k in ("model_codecs", "placement_root") if k in action}
    # Advanced resources remain discoverable, without advertising their setup
    # mechanics during every ordinary invocation. Never infer permission from
    # natural-language restrictions; the complete active scenario remains visible.
    advanced = []
    for group in ("services", "file_namespaces"):
        for item in caps.get(group, []):
            advanced.append({k: item[k] for k in
                ("service_id", "namespace_id", "kind", "details_reference",
                 "endpoints", "database_tables", "creatable_collections") if k in item})
    if advanced:
        result["resources"] = advanced
    if caps.get("features"):
        result["features"] = caps["features"]
    return result, resources.keys()


def _supporting_references(inputs, target_references, context, bundle):
    """Only submitted supporting material, not runtime inputs or generated guides."""
    artifacts = {item["artifact_id"]: item for item in bundle.get("artifacts", [])}
    bound = {item["entry_id"]: artifacts[item["artifact_id"]]
             for item in context.get("artifact_bindings", []) if item["artifact_id"] in artifacts}
    result = []
    for entry in inputs.reference_index():
        if (entry.get("role") not in ("reference", "skill-reference")
                or entry["entry_id"] in target_references
                or entry["entry_id"].startswith("tool-guide:")):
            continue
        item = {"reference": entry["entry_id"]}
        if entry["entry_id"] in bound:
            artifact = bound[entry["entry_id"]]
            item.update(artifact_id=artifact["artifact_id"], purpose=artifact["purpose"], required=artifact["required"])
        else:
            # A supplied filename can distinguish otherwise unnamed documents.
            item["description"] = entry.get("description", entry.get("path", entry["entry_id"]))[:256]
        result.append(item)
    result.extend({k: item[k] for k in ("artifact_id", "purpose", "required", "omission_reason")}
                  for item in artifacts.values() if "omission_reason" in item)
    return result


def build_task(inputs, *, active_scenario=None):
    """Campaign requirements and one complete scenario, separate from runtime state."""
    context, bundle = inputs.context(), inputs.bundle()
    campaign = {k: v for k, v in bundle.items()
                if k not in ("schema_version", "bundle_id", "producer", "target_requirements", "scenarios", "artifacts")
                and v not in (None, [], {}, "")}
    requirements = bundle.get("target_requirements", {}).get("required_capability_refs")
    if requirements:
        campaign["required_capability_refs"] = requirements
    target, target_references = _target_view(inputs, context)
    document = {
        "campaign": campaign,
        "scenario_index": _scenario_references(bundle),
        "active_scenario": next((s for s in bundle["scenarios"]
                                 if s["scenario_id"] == active_scenario), None),
        "target": target,
        "permitted_feedback": context["feedback"],
    }
    references = _supporting_references(inputs, target_references, context, bundle)
    if references:
        document["campaign"]["references"] = references
    if inputs.skills:
        document["skills"] = [{"name": skill.name, "instructions": skill.instructions}
                              for skill in inputs.skills]
    # Navigation is Harness presentation, not a local replacement tool catalog.
    document["navigation"] = (
        "Select or revisit a scenario with reference_read using its reference_id and offset 0. "
        "Its complete instructions replace active_scenario; the result confirms activation, "
        "not a paginated read. Construct attempts only after receiving those instructions. "
        "Progress snapshots describe instruction delivery and execution at conversation start; "
        "Use subsequent tool results for newer progress. Execution does not establish objective achievement."
        " active_scenario_activity tracks retained action outcomes, not satisfied requirements; "
        "requested_purpose is the caller's stated intent. Prior activity returns when a scenario is revisited."
    )
    try:
        return _canonical_value(document, TASK_LIMIT).decode("utf-8")
    except ContractError:
        # Optional skill content remains reachable through its verified references.
        if inputs.skills:
            document["skills"] = [{"name": skill.name, "description": skill.description,
                                   "instructions_deferred": True} for skill in inputs.skills]
    try:
        return _canonical_value(document, TASK_LIMIT).decode("utf-8")
    except ContractError:
        raise ContractError(
            SCENARIO_CONTEXT_MESSAGE if active_scenario is not None else TASK_CONTEXT_MESSAGE,
            reason="scenario_context_limit" if active_scenario is not None else "task_context_limit",
            field_path="/active_scenario" if active_scenario is not None else "/campaign",
            correction="Reduce the submitted campaign context; do not omit active scenario requirements.",
        ) from None


class ScenarioDelivery:
    """Withhold unloaded scenarios until a subsequent model turn sees all requirements."""

    def __init__(self, inputs, conversation, loop):
        self.inputs, self.conversation, self.loop = inputs, conversation, loop
        self.delivered = set()
        self.visits = {}
        self.navigation = []
        self.handoffs = {}
        self.handoff_rejection = None
        self.response_task = conversation.task
        self.response_generation = conversation.task_generation
        self.last_navigation_turn = None
        self.navigation_only_turns = 0
        conversation.on_task_delivered = self.mark_delivered
        conversation.on_model_response = self.begin_response
        bundle = inputs.bundle()
        self.handoff_limit = min(2048, 16384 // (len(bundle['scenarios']) + 1))
        self.references = {entry["reference_id"]: scenario for entry, scenario in
                           zip(_scenario_references(bundle), bundle["scenarios"])}
        if self.references.keys() & {entry["entry_id"] for entry in inputs.reference_index()}:
            raise ContractError("Scenario reference collides with an input reference.")

    def mark_delivered(self):
        active = json.loads(self.conversation.task)["active_scenario"]
        if active is not None:
            self.delivered.add(active["scenario_id"])

    def begin_response(self, _batch):
        # Bind records to the task actually delivered, not a selection later in
        # the same response. Public prose and opaque reasoning are not handoffs.
        self.response_task = self.conversation.task
        self.response_generation = self.conversation.task_generation

    def validate_handoff(self, arguments):
        if not arguments.get('summary', '').strip() or not arguments.get('decision', '').strip():
            raise ToolError('invalid_arguments', 'A checkpoint handoff needs a summary and next-step decision.',
                path='/decision' if not arguments.get('decision', '').strip() else '/summary',
                correction='Use summary for assessed requirements and unresolved findings; use decision for the next step or revisit purpose. Keep evidence handles in the existing reference fields.')
        size = len(_canonical_value(arguments, ORDINARY_LIMIT))
        if size > self.handoff_limit:
            raise ToolError('configured_size_exceeded', f'Checkpoint handoff is {size} bytes; allowance is {self.handoff_limit} bytes. No progress record was accepted.',
                correction=f'Resubmit a complete progress record within {self.handoff_limit} UTF-8 canonical JSON bytes. Preserve unresolved obligations, findings, relevant evidence references and the next decision; remove narration and repeated instructions. Then select the scenario again.')

    def reject_handoff(self, call, rejection, *, known_progress=True):
        active = json.loads(self.response_task)['active_scenario']
        scope = (self.handoff_rejection['scenario_id'] if self.handoff_rejection else
                 active['scenario_id'] if active else None)
        self.handoff_rejection = dict(rejected_arguments=call.arguments.decode('utf-8', errors='replace'),
            tool_call_id=call.call_id, scenario_id=scope, known_progress=known_progress, rejection=deepcopy(rejection))
        # Scenario activation only selects a future task. Cancel uncommitted
        # navigation, without modifying any sealed message or native response.
        if self.conversation.task != self.response_task:
            self.conversation.cancel_scenario_change(self.response_task, self.response_generation)
            for entry in self.navigation:
                if entry['model_turn'] == self.loop.snapshot()['model_turns']:
                    entry['cancelled'] = 'handoff-rejected'

    def accept_handoff(self, record, arguments, *, host_rejection=None):
        active = json.loads(self.response_task)['active_scenario']
        key = (self.handoff_rejection['scenario_id'] if self.handoff_rejection else
               active['scenario_id'] if active else None)
        self.handoffs[key] = dict(scenario_id=key, record=record,
            model_turn=self.loop.snapshot()['model_turns'], submitted=deepcopy(arguments),
            **({'retention': 'harness-only', 'host_rejection': deepcopy(host_rejection)} if host_rejection else {}))
        self.handoff_rejection = None
        return key

    def require_handoff_correction(self):
        if self.handoff_rejection:
            raise ToolError('invalid_arguments', 'Scenario selection was withheld because the progress handoff needs correction.',
                path='/reference', correction='Correct the retained progress record, then select the scenario again. No target operation occurred; the current conversation remains active. You may still finish with an honest assessment.')

    def navigation_stalled(self, limit):
        state = self.loop.snapshot()
        # A successful activation-only batch, with repeated reads recognized by
        # the existing shared loop. No synthetic progress or semantic completion.
        return (self.last_navigation_turn == state['model_turns']
                and self.navigation_only_turns >= 2
                and 2 <= state['no_progress_turns'] < limit
                and limit - state['no_progress_turns'] <= 2)

    def record_navigation_batch(self, calls, results):
        turn = self.loop.snapshot()['model_turns']
        if calls and len(calls) == len(results) and all(
                call.name == 'reference_read' and result.outcome == 'success'
                and json.loads(result.content).get('status') == 'scenario-selected'
                for call, result in zip(calls, results)):
            self.navigation_only_turns = self.navigation_only_turns + 1 if self.last_navigation_turn == turn - 1 else 1
            self.last_navigation_turn = turn
        else:
            self.navigation_only_turns = 0

    def task_context(self, task, facts, *, assessment=False):
        active = task["active_scenario"]
        activity = facts.pop("scenario_activity", [])
        records = facts.pop('model_records', None)
        if records:
            task['model_records'] = records
        task["active_scenario_activity"] = [
            {k: v for k, v in entry.items() if k != "scenario_id"}
            for entry in activity
            if active and entry["scenario_id"] == active["scenario_id"]]
        if assessment:
            task['campaign_activity'] = activity
            task['assessment_scope'] = ('Assess the entire submitted campaign, including unvisited scenarios, '
                'unmet requirements and evidence gaps. Selectively revisit requirements or read evidence; '
                'do not resume target actions. Execution completion does not establish objective success.')
        for entry in task["scenario_index"]:
            handoff = self.handoffs.get(entry['scenario_id'])
            entry['handoff'] = (handoff['record'] or 'harness-only') if handoff else 'not-submitted'
            entry['selections'] = self.visits.get(entry['scenario_id'], 0)
            entry["instructions"] = ("active" if active and active["scenario_id"] == entry["scenario_id"]
                                     else "previously-loaded" if entry["scenario_id"] in self.delivered
                                     else "not-loaded")
            executions = [e for e in facts["executions"] if e.get("scenario_id") == entry["scenario_id"]]
            entry["executions"] = [e["execution"] for e in executions]
        task['continuity'] = dict(
            phase='assessment' if assessment else 'exploration',
            phase_reason=('finish-repair' if self.conversation._repair else
                          'navigation-stalled' if self.conversation._assessment_review else
                          'protected-finalization' if self.conversation._finalizing else 'campaign-execution'),
            recent_navigation=self.navigation,
            navigation_only_turns=self.navigation_only_turns,
            no_progress_turns=self.loop.snapshot()['no_progress_turns'],
            no_progress_limit=self.conversation.no_progress_limit,
            assessment_handoffs=dict(provenance='model-interpretation-not-evidence',
                entries=list(self.handoffs.values()), maximum_argument_bytes=self.handoff_limit),
            guidance=('Use record_append(kind=progress) for a checkpoint handoff: summary states requirements assessed, '
                'findings and unresolved obligations; decision states the next step or revisit purpose. Supply existing '
                'attempts/observations/records fields for validated references. Carry forward unresolved work when '
                'replacing a handoff. Submit the record before scenario selection; independent calls may share a response. '
                'Keep complete arguments within maximum_argument_bytes. Oversized handoffs are rejected, never cut. '
                'A harness-only handoff has no accepted historical-record handle. Public commentary is not a handoff. '
                'Handoffs do not establish success or change requirements. Missing handoffs mean no assessment supplied. '
                'Repeated navigation is not progress; finish honestly when review adds nothing.'))
        if self.handoff_rejection:
            task['checkpoint_handoff_rejection'] = deepcopy(self.handoff_rejection)
        if any(facts.values()):
            task["evidence"] = facts
        return task

    def reference(self, identifier):
        """A local read view of verified bundle data, not a new host artifact or receipt."""
        scenario = self.references[identifier]
        # Building the task first yields the specific context-limit diagnostic.
        task = build_task(self.inputs, active_scenario=scenario["scenario_id"])
        raw = _canonical_value(scenario, TASK_LIMIT)
        return {"entry_id": identifier, "scenario_id": scenario["scenario_id"],
                "bundle_reference_id": self.inputs.context()["scenario_bundle"]["entry_id"],
                "media_type": "application/json", "size_bytes": len(raw), "digest": raw_digest(raw)}, raw, task

    def activate(self, raw, task):
        self.require_handoff_correction()
        previous = json.loads(self.conversation.task)['active_scenario']
        selected = json.loads(task)['active_scenario']['scenario_id']
        turn = self.loop.snapshot()['model_turns']
        changed = task != self.conversation.task
        if changed:
            self.loop.reserve_read("content", raw_digest(raw), 0, len(raw))
            self.loop.settle_read(len(raw))
        self.visits[selected] = self.visits.get(selected, 0) + 1
        handoff = self.handoffs.get(previous['scenario_id'] if previous else None)
        self.navigation.append(dict(model_turn=turn, from_scenario=previous['scenario_id'] if previous else None,
            to_scenario=selected, selection=self.visits[selected],
            handoff_record=handoff['record'] if handoff else None))
        del self.navigation[:-8]
        if changed:
            self.conversation.replace_task(task)

    def require(self, scenario_id):
        task = json.loads(self.conversation.task)
        loaded = {task["active_scenario"]["scenario_id"]} if task["active_scenario"] else set()
        delivered = self.conversation.task_generation == self.conversation.delivered_task_generation
        if scenario_id in loaded and delivered:
            return
        if delivered:
            try:
                task_raw = build_task(self.inputs, active_scenario=scenario_id)
            except ContractError as error:
                raise ToolError.from_contract(error) from None
            # Use the same read accounting as reference_read, for newly delivered
            # immutable scenario content. The model need not discover a reference.
            selected = next(s for s in self.inputs.bundle()["scenarios"] if s["scenario_id"] == scenario_id)
            raw = _canonical_value(selected, TASK_LIMIT)
            self.activate(raw, task_raw)
        raise ToolError("scenario_context_required",
            "No target invocation occurred. Complete scenario instructions must be read before execution.",
            outcome="preflight-rejected", path="/scenario_id",
            correction="Read the active scenario in the updated task message, then reconstruct the call on the next turn. Do not replay this withheld submission blindly.")


@dataclass(frozen=True)
class Campaign:
    adaptive: AdaptiveHarness
    handlers: FixedHandlers
    attempts: AttemptExecutor
    finalizer: ConclusionFinalizer

    def run(self):return self.adaptive.run()


def compose_campaign(protocol,session,*,clock=lambda:int(time.monotonic()*1000)):
    """Create every mutable campaign-lifetime service exactly once."""
    inputs,client,admission=session.inputs,session.client,session.admission
    context=inputs.context();remaining=admission["remaining_limits"]
    loop=HarnessLoop(admission["limits"]["harness"])
    codec=context["model"]["codec_id"]
    policy_raw=_canonical_value(context["model"], ORDINARY_LIMIT)
    conversation=NativeConversation(protocol,policy_raw,build_task(inputs),remaining=remaining,
        model_allowance=admission['limits']['campaign']['model_tokens'],
        fixed_context_bytes=len(inputs.prompt_raw) + len(protocol.model_tools(codec,
            context['operations'],
            context['model']['tool_selection']['injection_surfaces'])))
    scenario_delivery=ScenarioDelivery(inputs,conversation,loop)
    artifacts=ArtifactPublisher(protocol,client)
    observations=ObservationReader(client)
    attempts=AttemptExecutor(protocol,client,artifacts,context,inputs.bundle(),loop,
        scenario_delivery=scenario_delivery)
    record_receipts=set();now=clock()
    finalizer=ConclusionFinalizer(
        protocol,client,inputs,loop,artifacts,attempts=attempts,
        observations=observations,record_receipts=record_receipts,
        campaign_deadline_ms=now+remaining["campaign_time_ms"],
        artifact_remaining=remaining["artifact_bytes"],clock=clock)
    handlers=FixedHandlers(
        protocol,inputs,client,loop,artifacts=artifacts,observations=observations,
        attempts=attempts,finalizer=finalizer,record_receipts=record_receipts,
        scenario_delivery=scenario_delivery)
    dispatcher=Dispatcher(protocol,loop,handlers.handlers(),raw_handlers=handlers.raw_handlers(), client=client)
    conversation.resource_context = handlers.model_tools.context_facts
    conversation.no_progress_limit = admission['limits']['harness']['max_no_progress_turns']
    conversation.navigation_stalled = lambda: scenario_delivery.navigation_stalled(conversation.no_progress_limit)
    conversation.on_dispatched = scenario_delivery.record_navigation_batch
    conversation.task_context = lambda task, citations: scenario_delivery.task_context(
        task, handlers.model_tools.context_facts(citations), assessment=conversation._assessment_phase)
    conversation.finalization_task = lambda: build_task(inputs)
    adaptive=AdaptiveHarness(protocol,client,loop,dispatcher,conversation,finalizer,limits=admission["limits"]["harness"])
    return Campaign(adaptive,handlers,attempts,finalizer)
