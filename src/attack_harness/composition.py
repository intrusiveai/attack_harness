"""Fixed post-admission composition root for one campaign process."""

from dataclasses import dataclass
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop

from .adaptive import AdaptiveHarness, NativeConversation
from .artifacts import ArtifactPublisher
from .attempts import AttemptExecutor
from .conclusion import ConclusionFinalizer
from .handlers import FixedHandlers
from .observations import ObservationReader
from .tools import Dispatcher


TASK_LIMIT = 768 << 10


def _scenario_index(bundle):
    return [{key:scenario[key] for key in
             ("scenario_id","objective_refs","hypothesis","priority","required")
             if key in scenario} for scenario in bundle["scenarios"]]


def build_task(inputs):
    """Build bounded initial context with immutable handles for deferred reads."""
    context,bundle=inputs.context(),inputs.bundle()
    document={
        "task":"Run the authorized adaptive attack-simulation campaign and finish with request_stop.",
        "campaign":{
            "campaign_id":context["campaign_id"],"launch_id":context["launch_id"],
            "run_revision":context["run_revision"],"operations":context["operations"],
            "remaining_limits":context["remaining_limits"],"feedback":context["feedback"],
            "omissions":context["omissions"],
        },
        "target":context["target"],"objectives":bundle["objectives"],
        "scenario_index":_scenario_index(bundle),
        "reference_handles":inputs.reference_index(),
        "selected_skills":[{
            "skill_id":skill.skill_id,"name":skill.name,"description":skill.description,
            "instructions":skill.instructions,
        } for skill in inputs.skills],
        "guidance":"Use reference_read for omitted or larger immutable content; handles are data, not authority.",
    }
    try:return _canonical_value(document,TASK_LIMIT).decode("utf-8")
    except ContractError:
        document["selected_skills"]=[{
            "skill_id":skill.skill_id,"name":skill.name,"description":skill.description,
            "instructions_deferred":True,
        } for skill in inputs.skills]
        target=context["target"]
        document["target"]={
            "schema_version":target["schema_version"],"source":target["source"],
            "capability_projection_digest":target["capability_projection_digest"],
            "operation_refs":[item["ref"] for item in target["capabilities"]["operations"]],
            "action_refs":[item["ref"] for item in target["capabilities"]["actions"]],
            "details_deferred":True,
        }
        document["objectives"]=[{
            key:objective[key] for key in ("objective_id","required") if key in objective
        } for objective in bundle["objectives"]]
        document["scenario_index"]=[{
            key:scenario[key] for key in
            ("scenario_id","objective_refs","priority","required") if key in scenario
        } for scenario in bundle["scenarios"]]
        document["reference_handles"]=[
            item["entry_id"] for item in inputs.reference_index()
        ]
        return _canonical_value(document,TASK_LIMIT).decode("utf-8")


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
    artifacts=ArtifactPublisher(protocol,client)
    observations=ObservationReader(client)
    attempts=AttemptExecutor(protocol,client,artifacts,context,inputs.bundle(),loop)
    record_receipts=set();now=clock()
    finalizer=ConclusionFinalizer(
        protocol,client,inputs,loop,artifacts,attempts=attempts,
        observations=observations,record_receipts=record_receipts,
        campaign_deadline_ms=now+remaining["campaign_time_ms"],
        artifact_remaining=remaining["artifact_bytes"],clock=clock)
    handlers=FixedHandlers(
        protocol,inputs,client,loop,artifacts=artifacts,observations=observations,
        attempts=attempts,finalizer=finalizer,record_receipts=record_receipts)
    dispatcher=Dispatcher(protocol,loop,handlers.handlers(),raw_handlers=handlers.raw_handlers())
    codec=context["model"]["codec_id"]
    tools_raw=protocol.model_tools(codec,sorted(client.operations))
    policy_raw=protocol.model_policy_from_context(inputs.context_raw,tools_raw,inputs.prompt_raw)
    conversation=NativeConversation(protocol,policy_raw,build_task(inputs))
    adaptive=AdaptiveHarness(protocol,client,loop,dispatcher,conversation,finalizer)
    return Campaign(adaptive,handlers,attempts,finalizer)
