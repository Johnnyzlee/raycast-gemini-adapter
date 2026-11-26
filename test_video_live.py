"""Manual, paid integration tests. Synthetic/public input only; isolated state."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor,as_completed
from adapter import Adapter,State,Handler,ROOT,configured_key
from video_tools import VideoTools

KEY=None;BASE=None;STATE=None

def chat(messages,model='gemini-4-neon',tools=None,conversation_id=None):
 body={'model':model,'messages':messages,'stream':True,'max_tokens':4096,'reasoning_effort':'low'}
 if tools:body['tools']=tools
 if conversation_id:body['conversation_id']=conversation_id
 req=Request(BASE+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
 msg={'role':'assistant','content':''};calls={};done=False;finish=None
 with urlopen(req,timeout=650) as r:
  for line in r:
   if not line.startswith(b'data:'):continue
   data=line[5:].strip()
   if data==b'[DONE]':done=True;break
   chunk=json.loads(data)
   assert all(k in chunk for k in ('id','object','created','model','choices')),'invalid SSE'
   if chunk.get('error'):raise AssertionError(chunk['error']['message'])
   for c in chunk['choices']:
    d=c.get('delta') or {};msg['content']+=d.get('content','') or ''
    for tc in d.get('tool_calls',[]):
     i=tc.get('index',0);calls.setdefault(i,{'id':'','type':'function','function':{'name':'','arguments':''}})
     if tc.get('id'):calls[i]['id']=tc['id']
     for k in ('name','arguments'):calls[i]['function'][k]+=tc.get('function',{}).get(k,'') or ''
    finish=c.get('finish_reason') or finish
 assert done and finish in ('stop','tool_calls'),'unfinished stream'
 if calls:msg['tool_calls']=[calls[i] for i in sorted(calls)]
 return msg


def metadata(messages,model='gemini-4-neon',conversation_id=None):
 fields={'key_hash':hashlib.sha256(KEY.encode()).hexdigest(),'model':model}
 if conversation_id:fields['conversation_id']=conversation_id
 from adapter import digest
 h,t,ok,meta=STATE.restore(messages,digest(fields),True)
 assert ok,'native history not restored'
 return h,meta


def call_and_record(h,prompt,model='gemini-4-neon',tools=None):
 h.append({'role':'user','content':prompt});m=chat(h,model,tools);h.append(m)
 return m,metadata(h,model)


def video_basic(model):
 h=[];p=str(ROOT/'test-fixtures/video-evidence.mp4')
 m,(native,meta)=call_and_record(h,'用原生视频工具分析 '+p+'，用中文给出颜色变化、屏幕数字，以及听到的声音（没有语音就说明没有语音）。给出约略时间戳，不要搜索。',model)
 assert all(x in m['content'] for x in ('红','蓝','绿','17','25','7391')),m['content'][:2500]
 video=[e for e in meta['events'] if e['tool']=='视频原生分析' and e['status']=='success']
 assert video and video[-1]['model']==model and video[-1]['video_input_verified']
 assert any(u['kind']=='video' and u['raw'].get('total_input_tokens',0)>0 for u in meta['usage'])
 result={'first':m['content'],'events':video,'usage':meta['usage']}
 if model=='gemini-4-neon':
  follow,(n2,p2)=call_and_record(h,'根据刚才已分析的画面，Alpha 和 Beta 相加是多少？请引用刚才视频来源，不要重新分析视频或使用其他工具。')
  assert '42' in follow['content'] and '沿用历史' in follow['content'],follow['content']
  assert not any(e['task']==p2['task'] and e['tool']=='视频原生分析' for e in p2['events'])
  clip,(n3,p3)=call_and_record(h,'请用视频工具只分析原视频 00:04 到 00:08 的片段，用中文说明背景颜色；注意不分析其他时间段。')
  funcs=[p['functionResponse'] for n in n3 for p in n['parts'] if p.get('functionResponse',{}).get('name')=='gemini_analyze_video']
  proc=funcs[-1]['response']['processing']
  assert proc['start_offset']=='4.0s' and proc['end_offset']=='8.0s',proc
  assert '蓝' in clip['content']
  switch,(n4,p4)=call_and_record(h,'根据已经分析过的视频，屏幕中的 Alpha 是多少？引用已有来源，不要重新分析。','gemini-4-carbon')
  assert '17' in switch['content'] and '沿用历史' in switch['content'],switch['content']
  result.update(followup=follow['content'],clip=clip['content'],switch=switch['content'])
 return result


def video_url(kind):
 url={'youtube':'https://www.youtube.com/watch?v=aqz-KE-bpKQ','direct':'https://storage.googleapis.com/cloud-samples-data/generative-ai/video/describe_video_content.mp4'}[kind]
 h=[];m,(native,meta)=call_and_record(h,'用原生视频工具仅分析 '+url+' 的 00:00 到 00:08，简短描述实际可见画面和可听声音，注明约略时间戳。不要搜索或读网页。')
 events=[e for e in meta['events'] if e['tool']=='视频原生分析' and e['status']=='success']
 assert events and events[-1]['input_kind']==kind,(m,events)
 assert any(u['kind']=='video' and u['raw'].get('total_input_tokens',0)>0 for u in meta['usage'])
 assert url in m['content'],m
 return {'answer':m['content'],'events':events,'usage':meta['usage']}


def mixed_search():
 tools=[{'type':'function','function':{'name':'compat_lookup','description':'Read-only synthetic lookup.','parameters':{'type':'object','properties':{}}}}]
 h=[];m,(native,meta)=call_and_record(h,'必须分两步完成：第一步实际用 Google 搜索查 Python 官方下载页当前最新版本号；取得实际搜索结果后，第二步才调用 compat_lookup。禁止在搜索完成之前调用 compat_lookup，也不要同时调用。最终答案带官方来源。',tools=tools)
 assert m.get('tool_calls'),m
 (ROOT/'local-evidence').mkdir(exist_ok=True)
 (ROOT/'local-evidence/search-diagnostic.json').write_text(json.dumps({'native':[{'role':n['role'],'parts':[{k:v for k,v in p.items() if k not in ('thoughtSignature','inlineData')} for p in n['parts']]} for n in native],'metadata':meta},ensure_ascii=False,indent=2))
 assert any(e['tool']=='Google 搜索' and e.get('suggestions_html') for e in meta['events']),'no actual search evidence before external call'
 before={k:r['url'] for k,r in meta['records'].items() if r['kind']=='search'}
 for c in m['tool_calls']:h.append({'role':'tool','tool_call_id':c['id'],'content':'{"status":"ok","value":37}'})
 final=chat(h,tools=tools);h.append(final);_,p2=metadata(h)
 assert 'Google 搜索建议' in final['content'],final['content']
 if before:assert any(url in final['content'] for url in before.values()),final['content']
 else:before={k:r['url'] for k,r in p2['records'].items() if r['kind']=='search'}
 assert before, 'Google did not supply citation sources even after tool continuation'
 assert 'Google 搜索' in final['content'] and 'Raycast compat_lookup' in final['content']
 follow,(n3,p3)=call_and_record(h,'沿用刚才 Python 官网来源；再实际读取 https://www.iana.org/help/example-domains ，给出两个网站各自用途，附对应来源，不要再次搜索 Python。')
 assert '沿用历史' in follow['content'] and '网页读取' in follow['content'],follow['content']
 assert any(k in p3['records'] for k in before)
 return {'final':final['content'],'followup':follow['content'],'source_ids':list(before)}


def tool_pair(kind):
 h=[]
 if kind=='document-python':prompt='读取 '+str(ROOT/'test-fixtures/verification.pdf')+' 并在云端 Python 实际计算文件中的 Alpha+Beta。请附文件来源和执行依据。'
 elif kind=='maps-web':prompt='用 Google Maps 查询香港太空馆地址，再实际读取 https://www.iana.org/help/example-domains ，分别简述并附对应来源。'
 elif kind=='image-document':prompt='读取 '+str(ROOT/'test-fixtures/shapes.png')+' 和 '+str(ROOT/'test-fixtures/verification.docx')+'，给出图片颜色和文档校验码，注明两个文件名。'
 m,(native,meta)=call_and_record(h,prompt)
 success=[e['tool'] for e in meta['events'] if e['status']=='success']
 required={'document-python':['文档读取','云端 Python'],'maps-web':['Google Maps','网页读取'],'image-document':['图片读取','文档读取']}[kind]
 assert all(t in success for t in required),(success,m)
 if kind=='document-python':assert '42' in m['content'] and 'verification.pdf' in m['content']
 if kind=='image-document':assert 'CEDAR-4826' in m['content'] and 'shapes.png' in m['content']
 return {'answer':m['content'],'tools':success}


def video_agentic_mixed():
 h=[];video=str(ROOT/'test-fixtures/video-evidence.mp4');doc=str(ROOT/'test-fixtures/verification.docx')
 m,(native,meta)=call_and_record(h,'明确使用 agentic 模式分析 '+video+'，报告听到的声音和屏幕内容；另外读取 '+doc+'，报告其中校验码。分别标明依据；无法确认的内容直说。')
 events=[e for e in meta['events'] if e['status']=='success']
 assert any(e['tool']=='视频原生分析' and e['mode']=='agentic' for e in events),(m,events)
 assert any(e['tool']=='文档读取' for e in events),(m,events)
 assert 'CEDAR-4826' in m['content'],m
 return {'answer':m['content'],'events':events,'usage':meta['usage']}


def run(name,fn):
 start=time.monotonic()
 try:r={'test':name,'passed':True,'result':fn()}
 except Exception as e:r={'test':name,'passed':False,'error':str(e).replace(KEY,'[REDACTED]')[:3500]}
 r['seconds']=round(time.monotonic()-start,1)
 print(json.dumps({k:v for k,v in r.items() if k!='result'},ensure_ascii=False),flush=True)
 return r

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--only',nargs='*');parser.add_argument('--settings');parser.add_argument('--output',default='local-evidence/live-results.json');args=parser.parse_args()
 from configuration import load_settings
 settings=load_settings(args.settings);KEY=configured_key(settings);settings.update(show_usage_cost=True,strict_file_authorization=True,allowed_roots=[str(ROOT/'test-fixtures')])
 jobs=[('video-'+m,lambda m=m:video_basic('gemini-4-'+m)) for m in ('neon','carbon','hydrogen')]
 jobs += [(k,lambda k=k:video_url(k)) for k in ('youtube','direct')]
 jobs += [('search-raycast-followup',mixed_search),('agentic-video-document',video_agentic_mixed)]
 jobs += [(k,lambda k=k:tool_pair(k)) for k in ('document-python','maps-web','image-document')]
 if args.only:
  unknown=set(args.only)-{n for n,f in jobs}
  if unknown:parser.error('Unknown test names: '+', '.join(sorted(unknown)))
  jobs=[(n,f) for n,f in jobs if n in args.only]
 results=[]
 with tempfile.TemporaryDirectory(prefix='gemini-video-integration-') as tmp:
  STATE=State(tmp)
  class TestHandler(Handler):
   adapter=Adapter(settings,STATE)
   key_getter=staticmethod(lambda:KEY)
  server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler);settings['port']=server.server_port;BASE='http://127.0.0.1:'+str(server.server_port)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with ThreadPoolExecutor(max_workers=1) as pool:
    for f in as_completed([pool.submit(run,n,fn) for n,fn in jobs]):
     results.append(f.result());(ROOT/args.output).parent.mkdir(parents=True,exist_ok=True);(ROOT/args.output).write_text(json.dumps(results,ensure_ascii=False,indent=2))
  finally:
   server.shutdown();server.server_close();thread.join()
   print(json.dumps({'cleanup':VideoTools(settings,STATE,KEY).cleanup(True)}),flush=True);STATE.db.close()
 print('Passed:',sum(r['passed'] for r in results),'/',len(results),flush=True)
 raise SystemExit(0 if all(r['passed'] for r in results) else 1)
