"""Token-only estimates from the official 2026-11-26 Standard USD price list."""
import datetime
import uuid

PRICE_SOURCE='https://aistudio.google.com/docs/pricing'


def normalize(raw, interaction=False):
    if interaction:
        inp=raw.get('total_input_tokens',0);out=raw.get('total_output_tokens',0)+raw.get('total_thought_tokens',0)
        total=raw.get('total_tokens',inp+out);tool=raw.get('total_tool_use_tokens',0);cached=raw.get('total_cached_tokens')
    else:
        inp=raw.get('promptTokenCount',0);out=raw.get('candidatesTokenCount',0)+raw.get('thoughtsTokenCount',0)
        total=raw.get('totalTokenCount',inp+out);tool=raw.get('toolUsePromptTokenCount',0);cached=raw.get('cachedContentTokenCount')
    remainder=total-inp-out
    if remainder==tool:inp+=tool
    return {'prompt_tokens':inp,'completion_tokens':out,'total_tokens':total,'cached_tokens':cached,
            'unreconciled_tokens':total-inp-out,'reported':bool(raw)}


def record(ledger,model,raw,interaction=False,kind='generation'):
    u=normalize(raw,interaction)
    ledger.data['usage'].append({'id':uuid.uuid4().hex,'model':model,'kind':kind,'raw':raw,'normalized':u})
    return u


def rates(model,date):
    if not datetime.date(2026,11,26)<=date<=datetime.date(2026,12,26):return None
    if model=='gemini-4-carbon':return (2,10,.1) if date<datetime.date(2026,12,1) else (4,20,.2)
    return {'gemini-4-neon':(3,15,.15),'gemini-4-hydrogen':(1.5,7.5,.075)}.get(model)


def footer(ledger,date):
    entries={e['id']:e for e in ledger.data['usage']}.values()
    if not entries:return ''
    inp=out=total=0;lo=hi=0;unknown=[];estimated=0;unreported=0
    for e in entries:
        n=e['normalized'];inp+=n['prompt_tokens'];out+=n['completion_tokens'];total+=n['total_tokens']
        if not n['reported']:unreported+=1
        r=rates(e['model'],date)
        if not r or not n['reported'] or n['unreconciled_tokens']:
            unknown.append('价格或 token 明细不完整');continue
        estimated+=1
        ci,co,cc=r;i=n['prompt_tokens'];o=n['completion_tokens'];c=n['cached_tokens']
        if c is None:
            lo+=(i*cc+o*co)/1e6;hi+=(i*ci+o*co)/1e6;unknown.append('缓存量未返回，显示区间')
        else:
            c=max(0,min(c,i));amount=((i-c)*ci+c*cc+o*co)/1e6;lo+=amount;hi+=amount
    estimate=('US$%.6f'%hi if abs(hi-lo)<1e-9 else 'US$%.6f–%.6f'%(lo,hi))
    if not estimated:estimate='无法估算（价格或用量未知）'
    if any('不完整' in x for x in unknown):estimate+='（只含可估算调用）'
    suffix='；'+'；'.join(dict.fromkeys(unknown)) if unknown else ''
    if unreported:suffix+='；%d 个调用未返回用量，不按零费用处理'%unreported
    if any('_failed' in e['kind'] and e['normalized']['reported'] for e in entries):suffix+='；失败调用仅计已返回用量，未返回部分未知'
    recovered=set(ledger.data.get('recovered_usage_ids',[]))
    split=''
    if recovered:
        old=sum(e['normalized']['total_tokens'] for e in entries if e['id'] in recovered)
        new=sum(e['normalized']['total_tokens'] for e in entries if e['id'] not in recovered)
        split='\n\n> 恢复前已发生用量 %d tokens；本次恢复新调用 %d tokens。读取检查点不产生 API token；失败调用缺失的用量仍未知。'%(old,new)
    return split+('\n\n> 本任务已返回的 API 用量（含适配器子调用）：输入 %d，输出含思考 %d，总计 %d tokens。Tokens 估算 %s；搜索/Maps 等工具收费及未返回的计费项未知、未计入，不是真实账单%s。价格核对：2026-11-26。'%(inp,out,total,estimate,suffix))
