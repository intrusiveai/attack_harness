"""Adapt archived provider samples into current relay fixtures, never runtime fallback."""
from copy import deepcopy

def relay_cases(cases):
    result=[]
    for original in cases:
        c=deepcopy(original)
        q=c.get('request',{});native=q.get('request')
        if native is not None:
            codec=q['codec_id'];field={'openai-responses-text-tools-v1':'input','gemini-text-tools-v1':'contents'}.get(codec,'messages')
            history=native.get(field,[])
            if codec=='openai-chat-text-tools-v1':history=history[1:]
            c['request']=dict(purpose='generation',conversation=history)
        if 'result' in c:
            for key in ('codec_id','profile_id','profile_digest'):c['result'].pop(key,None)
        result.append(c)
    return result
