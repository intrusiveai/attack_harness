"""Shared normalization over campaign-owned handles; host services stay canonical."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.tool_normalization import remap_tool_path
from operator_contracts.validation import ORDINARY_LIMIT, safe_argument_path, decode

from .runtime import RuntimeStopped
from .tools import HandlerResult, ToolError


@dataclass
class RecordedCall:
    signature: tuple
    result: HandlerResult | None = None
    activity: dict | None = None


class ModelTools:
    """One bounded resource map and duplicate-call ledger for the admitted campaign."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.protocol, self.client = handlers.protocol, handlers.client
        self.resources, self._identities, self._counts, self._calls = {}, {}, {}, {}
        self.database_keys = {}
        self.campaign_id = self.client.campaign_id
        inputs = handlers.inputs
        for entry in inputs.reference_index():
            self.register("reference", {"reference_id": entry["entry_id"],
                "entry_id": entry["entry_id"]}, handle=entry["entry_id"], available=True)
        delivery = handlers.scenario_delivery
        if delivery is not None:
            for identifier in delivery.references:
                self.register("reference", {"reference_id": identifier, "entry_id": identifier},
                              handle=identifier, available=True)
        # Capabilities are verified startup data, never observation/model content.
        target = inputs.context()["target"]
        for service in target.get("capabilities", {}).get("services", []):
            for policy in service.get("database_tables", []):
                self.database_keys[service["service_id"] + "/" + policy["id"]] = policy["keys"]

    def register(self, kind, value, *, handle=None, available=False, inspected=False, live=False):
        identity = (kind, _canonical_value(value, ORDINARY_LIMIT))
        previous = self._identities.get(identity)
        if previous is not None:
            resource = self.resources[previous]
            resource.update(available=available, inspected=resource["inspected"] or inspected, live=live)
            return previous
        if len(self.resources) >= 4096:
            self.client.fail("budget-limit")  # Never invite replay after a successful host effect.
        if handle is None:
            index = self._counts.get(kind, 0) + 1
            while f"{kind}-{index}" in self.resources:
                index += 1
            self._counts[kind] = index
            handle = f"{kind}-{index}"
        if handle in self.resources:
            raise ContractError("Conflicting verified resource identity.")
        self.resources[handle] = dict(kind=kind, campaign_id=self.campaign_id,
            value=deepcopy(value), available=available, inspected=inspected, live=live)
        self._identities[identity] = handle
        return handle

    def _context(self, arguments, call_id):
        selected = {}
        def collect(value):
            if isinstance(value, str) and value in self.resources:
                selected[value] = self.resources[value]
            elif isinstance(value, dict):
                for item in value.values(): collect(item)
            elif isinstance(value, list):
                for item in value: collect(item)
        collect(arguments)
        # Supply inspected siblings to the shared validator so its correction
        # can name real, applicable citations without exposing unrelated entries.
        entries = {(r['value'].get('attempt_receipt_id'), r['value'].get('entry_id'))
                   for r in selected.values() if r['kind'] == 'observation'}
        for identity in entries:
            siblings = [(h, r) for h, r in self.resources.items()
                        if r['kind'] == 'observation' and r['inspected'] and r['available']
                        and (r['value'].get('attempt_receipt_id'), r['value'].get('entry_id')) == identity]
            selected.update(sorted(siblings)[:3])
        return dict(campaign_id=self.campaign_id, call_id=call_id,
                    resources=selected, database_keys=self.database_keys)

    def _retain_selections(self, call, selections):
        for offset in range(0, len(selections), 32):
            report = dict(tool_name=call.name, diagnostic={
                "source": "harness-local", "stage": "references", "reason": "observation_selection",
                "message": "Selected inspected observations for assessment references.",
                "execution_occurred": "no", "resubmission_safe": True,
            }, observation_selections=selections[offset:offset + 32])
            reply = self.client.request("engine.diagnostic_report", report,
                operation_id=self.client.operation_id("observation-selection"))
            if reply.error is not None:
                # A required retention failure prevents assessment submission.
                raise ToolError.from_host(reply.error)

    @staticmethod
    def _remap(value, paths):
        result = deepcopy(value)
        if "instance_path" in result:
            result["instance_path"] = safe_argument_path(remap_tool_path(paths, result["instance_path"]))
        diagnostic = result.get("diagnostic")
        old_path = diagnostic.get("field_path", "") if diagnostic else ""
        new_path = safe_argument_path(remap_tool_path(paths, old_path))
        if diagnostic and "field_path" in diagnostic:
            diagnostic["field_path"] = new_path
        # Change only schema vocabulary and known path mappings, never arguments.
        for container in (result, diagnostic or {}):
            for key in ('message', 'correction'):
                if key not in container:
                    continue
                text = container[key]
                if old_path and new_path:
                    text = text.replace(old_path, new_path)
                for canonical, model in (('attempt_receipt_refs','attempts'),('observation_refs','observations'),('record_refs','records'),('uncertainty_refs','uncertainties'),('parent_hypothesis_id','parent'),('execution receipt and entry ID','readable observation handle')):
                    text = text.replace(canonical, model)
                container[key] = text
        for error in result.get("errors", []):
            if "instance_path" in error:
                error["instance_path"] = remap_tool_path(paths, error["instance_path"])
        return result

    def dispatch(self, call):
        key = (call.batch_id, call.call_id, call.correlation)
        signature = (call.name, call.arguments)
        if key in self._calls:
            recorded = self._calls[key]
            if recorded.signature != signature:
                error = ToolError("call_identity_conflict", "Call identity was reused with different arguments.",
                    correction="Inspect the prior result before choosing another action; do not replay uncertain effects.")
                error.value["diagnostic"].update(execution_occurred="unknown", resubmission_safe=False)
                raise error
            if recorded.result is None:
                self.client.fail("operation-failed")
            return deepcopy(recorded.result)
        recorded = RecordedCall(signature)
        self._calls[key] = recorded
        stable = "native-" + hashlib.sha256(_canonical_value(list(key), 4096)).hexdigest()
        paths = {}
        try:
            arguments = self.protocol.validate_tool_arguments(call.name, call.arguments)
            normalized = self.protocol.normalize_tool_arguments(call.name, call.arguments,
                self._context(arguments, stable))
            paths = normalized["paths"]
        except ContractError as error:
            if call.name == "attempt_execute":
                self.handlers.attempts.reject_submission(call.call_id)
            result = HandlerResult(ToolError.from_contract(error).value, "invalid")
            recorded.result = result
            return deepcopy(result)
        recorded.activity = self._activity_context(call.name, arguments)
        try:
            body = normalized["arguments"]
            self._retain_selections(call, normalized["observation_selections"])
            if call.name == "attempt_execute":
                handled = self.handlers.attempts.execute(call, body)
            else:
                handled = self.handlers.canonical_handlers()[call.name](body)
            if handled.outcome in ("invalid", "preflight-rejected"):
                result = HandlerResult(self._remap(handled.value, paths), handled.outcome)
            else:
                result = HandlerResult(self._present(call.name, body, handled.value, arguments), handled.outcome)
        except ToolError as error:
            result = HandlerResult(self._remap(error.value, paths), error.outcome)
        except ContractError as error:
            if isinstance(error, RuntimeStopped) or error.reason != "configured_size_exceeded":
                raise
            error = ToolError.from_contract(error)
            result = HandlerResult(self._remap(error.value, paths), "invalid")
        recorded.result = deepcopy(result)
        return result

    def _activity_context(self, name, arguments):
        """Associate a validated action with its scenario, not its claimed success."""
        delivery = self.handlers.scenario_delivery
        if delivery is None or name not in (
                'attempt_execute', 'snapshot_request', 'restore_request', 'injection_delete'):
            return None
        if name == 'attempt_execute':
            if arguments['origin'] != 'scenario':
                return None
            scenario_id = arguments['scenario_id']
        else:
            active = json.loads(delivery.conversation.task)['active_scenario']
            if active is None:
                return None
            scenario_id = active['scenario_id']
        return dict(scenario_id=scenario_id, tool=name,
            **({'operation_id': arguments['operation_id']} if name == 'attempt_execute' else {}),
            **({'requested_purpose': arguments['rationale'][:160]} if arguments.get('rationale') else {}))

    def scenario_activity(self, executions):
        """Project retained call outcomes; never parse evidence for progress claims."""
        by_handle = {e['execution']: e for e in executions}
        activity = []
        for recorded in self._calls.values():
            if recorded.activity is None or recorded.result is None:
                continue
            result = recorded.result
            value = result.value
            entry = dict(recorded.activity)
            if result.outcome in ('invalid', 'preflight-rejected'):
                entry.update(status='not-executed')
                diagnostic = value.get('diagnostic', {})
                entry['reason'] = diagnostic.get('reason', value.get('code', value.get('status', 'rejected')))
                if diagnostic.get('field_path'):
                    entry['field_path'] = diagnostic['field_path']
            else:
                entry['status'] = value.get('status', result.outcome)
                for key in ('execution', 'snapshot', 'restored_snapshot', 'injection', 'outcome'):
                    if key in value:
                        entry[key] = (value[key]['snapshot'] if key == 'snapshot' and isinstance(value[key], dict)
                                      else deepcopy(value[key]))
                execution = by_handle.get(value.get('execution'))
                if execution is not None:
                    # Preserve uncertain effects/retry restrictions rather than
                    # translating every returned result into "task complete".
                    for key in ('invocation_state', 'target_contact', 'retry_disposition', 'after_restore', 'parent'):
                        if key in execution:
                            entry[key] = execution[key]
                    entry['observations'] = execution['observations']
            activity.append(entry)
        return activity

    def _snapshot(self, metadata):
        value = deepcopy(metadata)
        session = value.pop("source_session")
        checkpoint = value.pop("checkpoint_id")
        value["snapshot"] = self.register("checkpoint", dict(source_session=session,
            checkpoint_id=checkpoint), available=metadata.get("status") == "ready")
        value["session"] = self.register("session", dict(source_session=session), available=True)
        if "parent" in value:
            identity = ("checkpoint", _canonical_value(value["parent"], ORDINARY_LIMIT))
            value["parent"] = self._identities.get(identity) or self.register("checkpoint", value["parent"])
        self.resources[value["snapshot"]]["snapshot_context"] = deepcopy(value)
        return value

    def context_facts(self, present_citations):
        """Small associations from verified state, never from target prose."""
        executions, other = [], []
        observations = [(h, r) for h, r in self.resources.items() if r['kind'] == 'observation']
        for handle, resource in self.resources.items():
            if resource['kind'] == 'execution':
                receipt = resource['value']['attempt_receipt_id']
                entries = {}
                for citation, observation in observations:
                    value = observation['value']
                    if value['attempt_receipt_id'] != receipt:
                        continue
                    entry = entries.setdefault(value['entry_id'], dict(readable=[], inspected=[]))
                    if observation['available']:
                        entry['readable'].append(dict(handle=citation, **({'range': value['range']} if 'range' in value else {})))
                    if observation['inspected']:
                        entry['inspected'].append(dict(citation=citation, content_in_prompt=citation in present_citations))
                executions.append(dict(execution=handle, **self._execution_view(resource.get('execution_context', {})),
                                       observations=list(entries.values())))
            elif resource['kind'] == 'reference' and resource['inspected']:
                other.append(dict(handle=handle, kind='reference', inspected=True,
                    available=resource['available'], content_in_prompt=handle in present_citations,
                    reference=resource['value']['reference_id'],
                    **({'range': resource['value']['range']} if 'range' in resource['value'] else {})))
            elif resource['kind'] not in ('observation', 'reference'):
                other.append(dict(handle=handle, kind=resource['kind'], available=resource['available'], live=resource['live'],
                    **({'snapshot_metadata': {k: v for k, v in resource['snapshot_context'].items()
                        if k in ('snapshot', 'session', 'parent', 'status', 'label', 'description')}}
                       if 'snapshot_context' in resource else {})))
        restores = [{k: v for k, v in r.result.value.items() if k in ('restored_snapshot', 'harness_disposition')}
                    for r in self._calls.values()
                    if r.signature[0] == 'restore_request' and r.result is not None and r.result.outcome == 'restored']
        facts = dict(executions=executions, other_handles=other, restores=restores)
        activity = self.scenario_activity(executions)
        if activity:
            facts['scenario_activity'] = activity
        return facts

    @staticmethod
    def _execution_view(value):
        value = {k: v for k, v in value.items() if k != "run_revision"}
        # Compact only confirmed ordinary success. Failed/uncertain executions
        # retain all facts affecting safe recovery. Canonical results stay retained.
        if (value.get("status") == "completed" and value.get("invocation_state") == "succeeded"
                and value.get("cleanup_state") in ("completed", "not-needed")
                and not value.get("errors")
                and value.get("feedback", {}).get("collection_state", "complete") == "complete"):
            return {k: v for k, v in value.items() if k not in
                    ("stage", "invocation_state", "target_contact", "retry_disposition", "cleanup_state")
                    and v not in ([], {}, "")}
        return value

    def _present(self, name, body, result, arguments):
        value = deepcopy(result)
        if name == "attempt_execute":
            receipt = value.pop("receipt_id")
            value.pop("attempt_id", None); value.pop("request_id", None)
            value.pop("api_version", None); value.pop("kind", None)
            value.pop("target_output", None); value.pop("observations", None)
            value["execution"] = self.register("execution", dict(attempt_receipt_id=receipt), available=True)
            restored = [r.result.value['restored_snapshot'] for r in self._calls.values()
                        if r.result is not None and r.result.outcome == 'restored' and 'restored_snapshot' in r.result.value]
            self.resources[value['execution']]['execution_context'] = {
                **({'after_restore': restored[-1]} if restored else {}),
                "run_revision": self.client.run_revision,
                **({'parent': arguments['parent']} if 'parent' in arguments else {}),
                **{k: body[k] for k in ('origin', 'scenario_id') if k in body},
                **{k: result[k] for k in ('status', 'stage', 'errors', 'invocation_state', 'target_contact', 'retry_disposition', 'cleanup_state') if k in result},
            }
            feedback = value.pop("feedback", {})
            if feedback.get("collection_state") not in (None, "complete"):
                self.resources[value['execution']]['execution_context']['feedback'] = {
                    k: v for k, v in feedback.items() if k != "entries"}
            value["feedback"] = {k: v for k, v in feedback.items() if k != "entries"}
            for category in value["feedback"].get("categories", []):
                if (feedback.get("profile") == "oracle-assisted"
                        and category.get("kind") == "oracle_outcome" and category.get("state") == "empty"):
                    category["meaning"] = "No positive verdict returned; this alone establishes neither attack failure nor success."
            value["observations"] = []
            for entry in feedback.get("entries", []):
                # The host's permitted feedback manifest contains both
                # target-visible output and Harness-only observations.
                item = {k: v for k, v in entry.items() if k not in ("entry_id", "artifact")}
                item["observation"] = self.register("observation", dict(attempt_receipt_id=receipt,
                    entry_id=entry["entry_id"]), available=entry["availability"] == "available")
                if "artifact" in entry:
                    item.update({k: entry["artifact"][k] for k in ("size_bytes", "media_type")})
                self.resources[item["observation"]]["observation_context"] = {k: entry[k] for k in ("kind", "source", "assurance", "visibility") if k in entry}
                value["observations"].append(item)
            if body.get("retain_injections") and result["cleanup_state"] == "not-requested":
                value["injections"] = [{"injection": self.register("injection",
                    dict(attempt_receipt_id=receipt, action_id=action["action_id"]), live=True)}
                    for action in body["pre_actions"]]
            value = self._execution_view(value)
            if "stage" not in value:  # Confirmed ordinary success only.
                unavailable = [category for category in value.get("feedback", {}).get("categories", [])
                    if category.get("state") not in ("available", "empty") or "meaning" in category]
                value.pop("feedback", None)
                if unavailable:
                    value["feedback_limits"] = unavailable
        elif name == "artifact_publish":
            artifact = value["artifact"]
            value = dict(status=value["status"], artifact=self.register("artifact",
                dict(artifact_receipt=value["artifact_receipt"], purpose=value["purpose"]), available=True),
                purpose=value["purpose"], media_type=artifact["media_type"], size_bytes=artifact["size_bytes"])
        elif name == "reference_read" and value.get("status") == "scenario-selected":
            # Activation is not a byte read in tool history or an inspected citation.
            return value
        elif name in ("observation_read", "reference_read"):
            observation = name == "observation_read"
            kind = "observation" if observation else "reference"
            canonical = (dict(attempt_receipt_id=body["receipt_id"], entry_id=body["entry_id"])
                         if observation else dict(reference_id=body["reference_id"], entry_id=body["reference_id"]))
            available = not observation or value["availability"] == "available"
            whole = value["offset"] == 0 and value["eof"]
            if value["raw_length"] and not whole:
                canonical["range"] = dict(offset=value["offset"], length=value["raw_length"])
            if observation:
                readable = arguments['observation']
                value['readable_observation'] = readable
                if available and (whole or value['raw_length']):
                    value['citation'] = self.register(kind, canonical, available=True, inspected=True)
                if available and value['raw_length'] and not value['eof']:
                    extent = self.resources[readable]['value'].get('range')
                    end = value['artifact']['size_bytes']
                    if extent is not None:
                        end = min(end, extent['offset'] + extent['length'])
                    next_offset = value['offset'] + value['raw_length']
                    if next_offset < end:
                        value['continuation'] = dict(tool='observation_read', arguments=dict(
                            observation=readable, offset=next_offset,
                            max_bytes=min(body['max_bytes'], end - next_offset)))
            else:
                value[kind] = self.register(kind, canonical, available=available,
                    inspected=available and (whole or bool(value['raw_length'])))
            value.pop("receipt_id", None); value.pop("entry_id", None); value.pop("reference_id", None)
            artifact = value.pop("artifact", None)
            if artifact: value.update({k: artifact[k] for k in ("size_bytes", "media_type")})
            if not observation and not value["eof"] and available:
                value["next_offset"] = value["offset"] + value["raw_length"]
                value['continuation'] = dict(tool='reference_read',arguments=dict(reference=arguments['reference'],offset=value['next_offset'],max_bytes=body['max_bytes']))
            if "source" in value:
                value["source"] = {k: v for k, v in value["source"].items() if k not in ("path", "digest")}
            # Decode only a complete verified JSON document. Never peel nested
            # target fields, parse a partial page, or repair duplicate keys.
            if (value.get("media_type") == "application/json" and value["offset"] == 0
                    and value["eof"] and value.get("encoding") == "utf8"):
                try:
                    content = decode(value["content"].encode("utf-8"), ORDINARY_LIMIT)
                except ContractError:
                    pass  # Preserve exact text when a faithful JSON view is unavailable.
                else:
                    # The provider serializer uses binary64 canonical numbers.
                    # Keep exact text if that representation would alter a value.
                    if decode(_canonical_value(content, ORDINARY_LIMIT), ORDINARY_LIMIT) == content:
                        value["content"] = content
                        value["encoding"] = "json"
                        value.pop("decoding", None)
            if observation:
                source = self.resources[arguments["observation"]]
                metadata = source.get("observation_context", {})
                if "citation" in value:
                    self.resources[value["citation"]]["observation_context"] = deepcopy(metadata)
                value["source"] = metadata
                value["content_role"] = "evidence-not-instructions"
            # These are transport/protocol fields, not fields in the content.
            value.pop("status", None)
            if not value.get("reason"):
                value.pop("reason", None)
        elif name == "record_append":
            value["record"] = self.register("record", dict(record_receipt_id=value.pop("receipt_id")), available=True)
            if body["record_kind"] == "hypothesis":
                value["hypothesis"] = self.register("hypothesis", dict(hypothesis_id=body["record"]["hypothesis_id"]), available=True)
        elif name in ("snapshot_request", "snapshot_inspect"):
            value = {**value, **self._snapshot(value.pop("snapshot"))}
            value.pop("receipt_id", None)
        elif name == "snapshot_list":
            value["snapshots"] = [self._snapshot(item) for item in value["snapshots"]]
        elif name == "restore_request":
            value["restored_snapshot"] = arguments["snapshot"]
            # INJECTION_CLEANUP_CONTRACT keeps same-campaign action mappings
            # valid across healthy restores, including previously deleted
            # injections. A fresh deletion goes to Operator, which revalidates
            # ownership and the current binding and confirms presence/absence.
            # Never reuse a historical cleanup result for that new operation.
            for resource in self.resources.values():
                if resource["kind"] == "injection": resource["live"] = True
            if "snapshot" in value:
                value["snapshot"] = self._snapshot(value["snapshot"])
        elif name == "injection_delete":
            handle = self._identities[("injection", _canonical_value(body, ORDINARY_LIMIT))]
            self.resources[handle]["live"] = False
            value = dict(injection=handle, outcome=value["outcome"])
        return value
