"""Provider response interpretation; unrelated metadata is not a contract gate."""
from copy import deepcopy
from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.validation import ORDINARY_LIMIT
from operator_contracts.startup import require


def disposition(codec, response):
    try:
        if codec == 'openai-chat-text-tools-v1':
            choice = response['choices'][0]
            reason = choice['finish_reason']
            if choice['message'].get('refusal') is not None:
                return 'refusal'
            calls = choice['message'].get('tool_calls') or []
        elif codec == 'openai-responses-text-tools-v1':
            reason = response['status']
            if (response.get('incomplete_details') or {}).get('reason') == 'content_filter':
                return 'filtered'
            calls = [v for v in response['output'] if v.get('type') == 'function_call']
            if any(p.get('type') == 'refusal' for v in response['output'] for p in v.get('content', [])):
                return 'refusal'
        elif codec == 'anthropic-messages-text-tools-v1':
            reason = response['stop_reason']
            if (response.get('stop_details') or {}).get('type') == 'refusal':
                return 'refusal'
            calls = [v for v in response['content'] if v.get('type') == 'tool_use']
        elif codec == 'bedrock-converse-text-tools-v1':
            reason = response['stopReason']
            calls = [v for v in response['output']['message']['content'] if 'toolUse' in v]
        elif codec == 'gemini-text-tools-v1':
            if response.get('promptFeedback', {}).get('blockReason'):
                return 'filtered'
            candidate = response['candidates'][0]
            reason = candidate['finishReason']
            calls = [v for v in candidate.get('content', {}).get('parts', []) if 'functionCall' in v]
        else:
            raise ContractError('Unsupported model conversation format.')
        for key in ('prompt_filter_results', 'content_filters', 'choices'):
            for annotation in response.get(key, []):
                if annotation.get('blocked') is True or any(isinstance(v,dict) and v.get('filtered') is True
                        for v in annotation.get('content_filter_results', {}).values()):
                    return 'filtered'
        if reason in ('content_filter','content_filtered','guardrail_intervened','SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT','SPII','IMAGE_SAFETY','ESCALATION'):
            return 'filtered'
        if reason in ('length','max_tokens','MAX_TOKENS','incomplete','failed','cancelled','pause_turn','malformed_model_output','malformed_tool_use','model_context_window_exceeded','MALFORMED_FUNCTION_CALL','LANGUAGE','OTHER','UNEXPECTED_TOOL_CALL','TOO_MANY_TOOL_CALLS','MISSING_THOUGHT_SIGNATURE','MALFORMED_RESPONSE'):
            return 'truncated'
        if reason == 'refusal':
            return 'refusal'
        if reason in ('tool_calls','tool_use'):
            require(bool(calls))
            return 'tool-calls'
        if reason in ('completed','STOP'):
            return 'tool-calls' if calls else 'text'
        if reason in ('stop','end_turn','stop_sequence'):
            require(not calls)
            return 'text'
        raise ContractError('Unsupported provider completion state; no tools were dispatched.')
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ContractError('Provider response lacks fields needed to interpret its completion; no tools were dispatched.') from None


def continuation(codec, response, calls, results):
    """Preserve native content, including opaque reasoning and future annotations."""
    if codec == 'openai-chat-text-tools-v1':
        assistant = deepcopy(response['choices'][0]['message'])
        return _canonical_value([assistant] + [dict(role='tool',tool_call_id=c.call_id,content=r.content)
            for c,r in zip(calls,results)], ORDINARY_LIMIT)
    if codec == 'openai-responses-text-tools-v1':
        return _canonical_value(deepcopy(response['output']) + [dict(type='function_call_output',call_id=c.call_id,output=r.content)
            for c,r in zip(calls,results)], ORDINARY_LIMIT)
    if codec == 'anthropic-messages-text-tools-v1':
        segment=[dict(role='assistant',content=deepcopy(response['content']))]
        if results:segment.append(dict(role='user',content=[dict(type='tool_result',tool_use_id=c.call_id,content=r.content) for c,r in zip(calls,results)]))
    elif codec == 'bedrock-converse-text-tools-v1':
        segment=[deepcopy(response['output']['message'])]
        if results:segment.append(dict(role='user',content=[dict(toolResult=dict(toolUseId=c.call_id,content=[dict(text=r.content)])) for c,r in zip(calls,results)]))
    elif codec == 'gemini-text-tools-v1':
        assistant=deepcopy(response['candidates'][0]['content'])
        segment=[assistant]
        parts=[]
        for c,r in zip(calls,results):
            original=assistant['parts'][c.correlation]['functionCall']
            value=dict(name=original['name'],response=dict(output=r.content))
            if 'id' in original:value['id']=original['id']
            parts.append(dict(functionResponse=value))
        if parts:segment.append(dict(role='user',parts=parts))
    else:
        raise ContractError('Unsupported model conversation format.')
    return _canonical_value(segment, ORDINARY_LIMIT)
