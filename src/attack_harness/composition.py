"""Fixed post-admission composition root for one campaign process."""

from dataclasses import dataclass
import json
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import HarnessLoop
from operator_contracts.model_tools import tool_guidance
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


def _portfolio(bundle):
    # This is a submitted inventory, not a progress ledger.
    return {"scenario_count": len(bundle["scenarios"]),
            "scenario_ids": [item["scenario_id"] for item in bundle["scenarios"]]}


def _reference_index(inputs):
    """Project discovery hints; canonical descriptors remain in verified Inputs."""
    projected = []
    for entry in inputs.reference_index():
        item = {key: entry[key] for key in ("entry_id", "role", "media_type", "size_bytes", "skill_id") if key in entry}
        if entry.get("path") and not entry["entry_id"].startswith("tool-guide:"):
            # A relative source name can be the only way to distinguish equally
            # typed documents. Keep it as a selection hint, never a lookup key.
            item["name"] = entry.get("description", entry["path"])[:256]
        projected.append(item)
    return projected


def build_task(inputs, *, active_scenario=None):
    """Keep complete scenario requirements in task data, never in system authority."""
    context, bundle = inputs.context(), inputs.bundle()
    examples = {name: decode(tool_guidance(inputs._protocol, name), ORDINARY_LIMIT)['examples']
                for name in ('finish', 'observation_read')}
    shared_guidance = {
        'finish': {'minimal_inline_example': examples['finish']['minimal_inline_example'],
                   'example_identity_note': examples['finish']['example_identity_note']},
        'observation_read': {'result_handles': examples['observation_read']['pagination_example']['result_handles']},
    }
    example = shared_guidance['finish']['minimal_inline_example']
    if bundle['objectives']:
        example['objectives'][0]['objective_id'] = bundle['objectives'][0]['objective_id']
    else:
        example['objectives'] = []
    target_raw, resources = compact_target_context(inputs._protocol,
        _canonical_value(context["target"], ORDINARY_LIMIT))
    for identifier, content in resources.items():
        _, retained = inputs.entry(identifier)
        if retained != content:
            raise ContractError("Target detail reference differs from verified startup.")
    document = {
        "task": "Run the authorized adaptive attack-simulation campaign and finish with finish.",
        "campaign": {
            "campaign_id": context["campaign_id"], "launch_id": context["launch_id"],
            "run_revision": context["run_revision"], "operations": context["operations"],
            "remaining_limits": context["remaining_limits"], "feedback": context["feedback"],
            "size_limits": context["size_limits"],
            "operation_timeouts_ms": context["operation_timeouts_ms"],
            "omissions": context["omissions"], "context_limits": context["model"]["context_limits"],
        },
        "target": decode(target_raw, ORDINARY_LIMIT),
        "scenario_bundle": {**bundle, "scenarios": [s for s in bundle["scenarios"]
                                                     if s["scenario_id"] == active_scenario]},
        "scenario_references": _scenario_references(bundle),
        "portfolio": _portfolio(bundle),
        "shared_tool_guidance": shared_guidance,
        "reference_handles": _reference_index(inputs),
        "selected_skills": [{
            "skill_id": skill.skill_id, "name": skill.name, "description": skill.description,
            "instructions": skill.instructions,
        } for skill in inputs.skills],
        "context_delivery": {
            "mode": "active-scenario", "active_scenario_id": active_scenario,
            "bundle_reference_id": context["scenario_bundle"]["entry_id"],
            "guidance": (
                "Index descriptions are selection aids, not requirements. reference_read on a scenario handle "
                "(offset 0) replaces the active section on the next turn; its result is a confirmation, "
                "not paginated text. Read full instructions before constructing an attempt. "
                "The bundle reference is the original source, not another required read. "
                "Other references retain ordinary paginated reading. Follow campaign sequencing guidance; "
                "priority alone does not define dependencies. At finish, revisit individual requirements "
                "and observations as needed; instructions delivered and completed executions are not objective success."
            ),
        },
        "guidance": (
            "The portfolio is the submitted scenario inventory, not current progress. "
            "Use reference_read with reference_handles, details_reference, or tool-guide:<tool_name> "
            "for deferred content and advanced examples. Read resource contracts before advanced setup."
        ),
    }
    try:
        return _canonical_value(document, TASK_LIMIT).decode("utf-8")
    except ContractError:
        # Defer optional skill text, never campaign or active-scenario requirements.
        document["selected_skills"] = [{
            "skill_id": skill.skill_id, "name": skill.name, "description": skill.description,
            "instructions_deferred": True,
        } for skill in inputs.skills]
    try:
        return _canonical_value(document, TASK_LIMIT).decode("utf-8")
    except ContractError:
        raise ContractError(
            SCENARIO_CONTEXT_MESSAGE if active_scenario is not None else TASK_CONTEXT_MESSAGE,
            reason="scenario_context_limit" if active_scenario is not None else "task_context_limit",
            field_path="/scenario_bundle/scenarios" if active_scenario is not None else "/scenario_bundle",
            correction="Reduce the submitted campaign context; do not omit active scenario requirements.",
        ) from None


class ScenarioDelivery:
    """Withhold unloaded scenarios until a subsequent model turn sees all requirements."""

    def __init__(self, inputs, conversation, loop):
        self.inputs, self.conversation, self.loop = inputs, conversation, loop
        self.delivered = set()
        conversation.on_task_delivered = self.mark_delivered
        bundle = inputs.bundle()
        self.references = {entry["reference_id"]: scenario for entry, scenario in
                           zip(_scenario_references(bundle), bundle["scenarios"])}
        if self.references.keys() & {entry["entry_id"] for entry in inputs.reference_index()}:
            raise ContractError("Scenario reference collides with an input reference.")

    def mark_delivered(self):
        self.delivered.update(s["scenario_id"] for s in
                              json.loads(self.conversation.task)["scenario_bundle"]["scenarios"])

    def context_facts(self):
        return {"instructions_delivered": sorted(self.delivered),
                "instructions_not_yet_delivered": [s["scenario_id"] for s in self.references.values()
                                                  if s["scenario_id"] not in self.delivered]}

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
        if task == self.conversation.task:
            return
        self.loop.reserve_read("content", raw_digest(raw), 0, len(raw))
        self.loop.settle_read(len(raw))
        self.conversation.replace_task(task)

    def require(self, scenario_id):
        task = json.loads(self.conversation.task)
        loaded = {s["scenario_id"] for s in task["scenario_bundle"]["scenarios"]}
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
    conversation.task_context = lambda citations: {
        "scenario_delivery_state": scenario_delivery.context_facts(),
        "execution_records": handlers.model_tools.context_facts(citations),
    }
    adaptive=AdaptiveHarness(protocol,client,loop,dispatcher,conversation,finalizer,limits=admission["limits"]["harness"])
    return Campaign(adaptive,handlers,attempts,finalizer)
