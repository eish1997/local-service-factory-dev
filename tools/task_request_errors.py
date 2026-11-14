"""Shared-task rejections: keep safe enums, original prompts and frozen caps."""


def continuous(state):
    return state.get('auto_complete',{}).get('mode')=='continuous' or isinstance(state.get('parent_budget'),dict)


def classify(error):
    from tools.category_image_production import classify_request_error
    kind=classify_request_error(error)
    status=getattr(error,'status_code',None)
    if kind is not None and kind!='transient':return kind,'content' if kind=='content_policy' else None
    if status==401:return 'authentication_failed',None
    if status==400:
        code=str(getattr(error,'code','') or '').lower()
        text=str(error).lower()[:8192]
        markers={
            'parameters':('invalid_parameter','invalid parameters','invalid parameter','unsupported parameter',
                          'invalid size','unsupported size','invalid quality','unsupported quality',
                          'invalid output_format','invalid json','malformed json','missing required','unknown parameter'),
            'model':('model_not_found','unsupported_model','model not found','unsupported model','model does not exist'),
            'permission':('permission_denied','permission denied','invalid_api_key','invalid api key'),
            'content':('safety_violation','content_filter','content policy','policy violation'),
        }
        for reason,values in markers.items():
            if any(marker in text or marker==code for marker in values):return 'request_rejected',reason
        return ('transient',None) if kind=='transient' else ('retryable_rejection','unknown')
    if kind is not None:return kind,None
    if status in {403,404,422,451}:return 'request_rejected','permission' if status==403 else 'parameters'
    return type(error).__name__,None


def retryable(state,result):
    error=result.get('error')
    if error in (None,'transient','balance_exhausted','authentication_failed'):return True
    if not continuous(state):return False
    if error=='retryable_rejection':return True
    # 1.4.8 stored unclassified explicit 400s as permanent rejections. Reuse
    # their existing licence/cap; returned/ambiguous results remain protected.
    return (error=='request_rejected' and result.get('http_status')==400
            and result.get('rejection_kind') in (None,'unknown'))
