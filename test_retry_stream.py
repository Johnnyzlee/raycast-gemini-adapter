import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from adapter import Adapter,State,AdapterError
from test_adapter import response

URL='https://www.youtube.com/watch?v=aqz-KE-bpKQ'
ARGS={'source':URL,'task':'summarize','start':'0','end':'4'}
class RetryAPI:
 def __init__(self):self.requests=[];self.fail=True;self.ended=False
 def generate(self,model,payload):
  self.requests.append(copy.deepcopy(payload))
  if any(p.get('functionResponse',{}).get('name')=='gemini_analyze_video' for m in payload['contents'] for p in m['parts']):
   if self.fail: self.fail=False;raise TimeoutError('synthetic final timeout')
   yield response([{'text':'Summary complete.'}])
  else:yield response([{'functionCall':{'name':'gemini_analyze_video','id':'video-call','args':copy.deepcopy(ARGS)},'thoughtSignature':'original-signature'}])

def video_ok(args,visible,ledger,model,cancelled,deadline):
 i=ledger.source('video','Synthetic',URL,original_source=URL,identity='synthetic');ledger.event('视频原生分析','success',[i])
 return {'status':'analyzed','answer':'00:02 red card','source_id':i},{'total_input_tokens':100,'total_output_tokens':10,'total_tokens':110}
class RuntimeFixture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)/'state';self.state=State(self.directory);self.addCleanup(lambda:self.state.db.close())
  self.settings={'allowed_roots':[self.tmp.name],'timezone':'Asia/Hong_Kong','show_usage_cost':True}
  self.body={'model':'gemini-4-neon','conversation_id':'test-chat','messages':[{'role':'user','content':'Summarize '+URL}]}

class RetryStreamTests(RuntimeFixture):
 def test_completed_video_survives_final_timeout(self):
  api=RetryAPI();a=Adapter(self.settings,self.state,lambda _:api)
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with self.assertRaises(TimeoutError):list(a.run(self.body,'key'))
   self.state.db.close();self.state=State(self.directory)
   out=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
  self.assertEqual(video.call_count,1)
  text=''.join(x.get('delta',{}).get('content','') for x in out);self.assertIn(URL,text)
  self.assertEqual(out[-1]['usage']['total_tokens'],12) # only this attempt's generation
 def test_first_text_precedes_upstream_completion(self):
  class Streaming:
   ended=False
   def generate(s,model,payload):
    yield {'candidates':[{'content':{'parts':[{'text':'第一段🙂'}]}}]}
    yield response([{'text':'第二段'}]);s.ended=True
  api=Streaming();a=Adapter(self.settings,self.state,lambda _:api);g=a.run(self.body,'key');first=next(g)
  self.assertEqual(first['delta']['content'],'第一段🙂');self.assertFalse(api.ended)
  remaining=list(g);self.assertEqual(''.join(c.get('delta',{}).get('content','') for c in [first]+remaining).split('\n\n>')[0],'第一段🙂第二段')

from provenance import Ledger,ReferenceStream
from video_tools import Cancelled,VideoError
import time,re

class RecoveryCases(RuntimeFixture):
 def fail_once(self,body=None,key='key',api=None):
  api=api or RetryAPI()
  with self.assertRaises(TimeoutError) as error:list(Adapter(self.settings,self.state,lambda _:api).run(body or self.body,key))
  return api,str(error.exception)
 def test_checkpoint_has_signed_history_sources_unique_usage(self):
  with patch('adapter.VideoTools.execute',side_effect=video_ok):
   api,_=self.fail_once();out=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
  resumed=api.requests[-1]['contents'];self.assertTrue(any(p.get('thoughtSignature')=='original-signature' for m in resumed for p in m['parts']))
  native,tail,found,meta=self.state.restore(self.body['messages']+[{'role':'assistant','content':''.join(c.get('delta',{}).get('content','') for c in out)}],__import__('adapter').digest({'key_hash':__import__('hashlib').sha256(b'key').hexdigest(),'model':self.body['model'],'conversation_id':'test-chat'}),True)
  self.assertTrue(found);self.assertEqual(sum(e['kind']=='video' for e in meta['usage']),1)
  self.assertEqual(len({e['id'] for e in meta['usage']}),len(meta['usage']))
  text=''.join(c.get('delta',{}).get('content','') for c in out)
  self.assertIn('恢复前已发生用量 122 tokens',text);self.assertIn('本次恢复新调用 12 tokens',text);self.assertIn('未返回用量',text)
 def test_changed_request_model_settings_session_or_credentials_no_reuse(self):
  for change in ('video','question','range','mode','model','session','key','settings','force'):
   with self.subTest(change=change):
    self.state.db.execute('DELETE FROM recovery_checkpoints');self.state.db.commit()
    body=copy.deepcopy(self.body);key='key';settings=copy.deepcopy(self.settings)
    with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
     self.fail_once()
     if change=='video':body['messages'][0]['content']+=' https://example.com/new.mp4'
     if change=='question':body['messages'][0]['content']+=' explain chart'
     if change=='range':body['messages'][0]['content']+=' 05:00 to 05:20'
     if change=='mode':body['messages'][0]['content']+=' high detail agentic'
     if change=='model':body['model']='gemini-4-carbon'
     if change=='session':body['conversation_id']='different-chat'
     if change=='key':key='different-key'
     if change=='settings':settings['video_max_bytes']=100000
     if change=='force':body['force_video_reanalysis']=True
     api=RetryAPI();api.fail=False
     list(Adapter(settings,self.state,lambda _:api).run(body,key))
     self.assertEqual(video.call_count,2)
 def test_expired_checkpoint_not_used(self):
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   api,_=self.fail_once();self.state.db.execute('UPDATE recovery_checkpoints SET updated=?',(time.time()-4*86400,));self.state.db.commit()
   list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'));self.assertEqual(video.call_count,2)
 def test_without_session_needs_explicit_receipt_and_receipt_is_account_bound(self):
  body=copy.deepcopy(self.body);body.pop('conversation_id')
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   api,message=self.fail_once(body);token=re.search('继续恢复 ([a-f0-9]{32})',message)[1]
   resume={**body,'messages':[{'role':'user','content':'继续恢复 '+token}]}
   with self.assertRaises(AdapterError):list(Adapter(self.settings,self.state,lambda _:api).run(resume,'wrong-key'))
   list(Adapter(self.settings,self.state,lambda _:api).run(resume,'key'));self.assertEqual(video.call_count,1)
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   api,_=self.fail_once(body)
   list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'));self.assertEqual(video.call_count,2)
 def test_failed_and_cancelled_video_not_cached(self):
  for exc in (VideoError('failed analysis'),Cancelled('cancelled')):
   with self.subTest(exc=type(exc).__name__):
    with patch('adapter.VideoTools.execute',side_effect=exc):
     try:list(Adapter(self.settings,self.state,lambda _:RetryAPI()).run(self.body,'key'))
     except (Cancelled,TimeoutError):pass
    self.assertEqual(self.state.db.execute('SELECT count(*) FROM recovery_checkpoints').fetchone()[0],0)
 def test_local_video_changed_invalidates_checkpoint(self):
  path=Path(self.tmp.name)/'synthetic.mp4';path.write_bytes(b'first')
  body=copy.deepcopy(self.body);body['messages'][0]['content']='read '+str(path)
  def local_result(*a):
   result,u=video_ok(*a);a[2].data['records'][result['source_id']].update(original_source=str(path),content_hash='firsthash');return result,u
  with patch('adapter.VideoTools.execute',side_effect=local_result) as video:
   api,_=self.fail_once(body)
   with patch('adapter.VideoTools.local',return_value=(path,{'hash':'changedhash'})):
    list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'))
   self.assertEqual(video.call_count,2)
 def test_checkpoint_written_before_following_local_tool_and_resumes_remaining(self):
  class Multi(RetryAPI):
   def generate(s,model,payload):
    if not any(p.get('functionResponse') for m in payload['contents'] for p in m['parts']):
     yield response([{'functionCall':{'name':'gemini_analyze_video','id':'v','args':ARGS}}, {'functionCall':{'name':'gemini_view_image','id':'i','args':{'path':'/fake.png'}}}])
    else:yield response([{'text':'Done.'}])
  def cancel_after(*a):
   self.assertEqual(self.state.db.execute('SELECT count(*) FROM recovery_checkpoints').fetchone()[0],1)
   raise Cancelled('cancel subsequent tool')
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with patch('adapter.FileTools.read',side_effect=cancel_after),self.assertRaises(Cancelled):list(Adapter(self.settings,self.state,lambda _:Multi()).run(self.body,'key'))
   with patch('adapter.FileTools.read',return_value=('synthetic.png',[{'text':'test image'}])):
    out=list(Adapter(self.settings,self.state,lambda _:Multi()).run(self.body,'key'))
   self.assertEqual(video.call_count,1);self.assertEqual(out[-1]['finish_reason'],'stop')
 def test_followup_reuses_summary_but_new_segment_calls_video(self):
  api=RetryAPI();api.fail=False
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   first=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   answer=''.join(x.get('delta',{}).get('content','') for x in first)
   body=copy.deepcopy(self.body);body['messages'] += [{'role':'assistant','content':answer},{'role':'user','content':'explain the existing summary'}]
   list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'));self.assertEqual(video.call_count,1)
   class Segment(RetryAPI):
    def generate(s,model,payload):
     if not s.requests:
      s.requests.append(payload);yield response([{'functionCall':{'name':'gemini_analyze_video','args':{**ARGS,'start':'5','end':'8'}}}])
     else:yield response([{'text':'New segment.'}])
   body['messages'][-1]['content']='重新查看 00:05 到 00:08'
   list(Adapter(self.settings,self.state,lambda _:Segment()).run(body,'key'));self.assertEqual(video.call_count,2)

class StreamingCases(RuntimeFixture):
 def test_refs_every_split_and_unicode_links(self):
  ledger=Ledger();ident=ledger.source('web','Verified','https://example.com/real')
  text='中文🙂 ['+ident+'](https://forged.test/f(x)) and [普通链接](https://example.com/a(b)) 完毕'
  want='中文🙂 [1](<https://example.com/real>) and [普通链接](https://example.com/a(b)) 完毕'
  for n in range(len(text)+1):
   s=ReferenceStream(ledger);got=s.feed(text[:n])+s.feed(text[n:])+s.finish();self.assertEqual(got,want,n)
  s=ReferenceStream(ledger);self.assertEqual(''.join(s.feed(c) for c in text)+s.finish(),want)
 def test_late_metadata_footer_and_unknown_ref_no_forged_link(self):
  class Late:
   ended=False
   def generate(s,*args):
    yield {'candidates':[{'content':{'parts':[{'text':'Fact 🙂 [S000000000000](https://forged.test)'}]}}]}
    yield response([],{'groundingChunks':[{'web':{'title':'Verified','uri':'https://example.com/fact'}}], 'groundingSupports':[{'segment':{'text':'Fact 🙂'},'groundingChunkIndices':[0]}]});s.ended=True
  api=Late();g=Adapter(self.settings,self.state,lambda _:api).run(self.body,'key');first=next(g);self.assertFalse(api.ended)
  text=first['delta']['content']+''.join(x.get('delta',{}).get('content','') for x in g)
  self.assertNotIn('forged.test',text);self.assertIn('https://example.com/fact',text);self.assertEqual(text.count('Fact 🙂'),1)
 def test_partial_failure_and_cancel_never_saved_as_success(self):
  for failure in (TimeoutError('cut off'),Cancelled('cancel')):
   class Partial:
    def generate(s,*args):
     yield {'candidates':[{'content':{'parts':[{'text':'Visible partial🙂'}]}}]}
     raise failure
   g=Adapter(self.settings,self.state,lambda _:Partial()).run(self.body,'key');self.assertEqual(next(g)['delta']['content'],'Visible partial🙂')
   with self.assertRaises(type(failure)):list(g)
   self.assertEqual(self.state.db.execute('SELECT count(*) FROM histories').fetchone()[0],0)
 def test_json_is_not_rewritten_or_footnoted(self):
  class JSONAPI:
   def generate(s,*args):
    yield {'candidates':[{'content':{'parts':[{'text':'{"text":"中文 [S000000'}]}}]}
    yield response([{'text':'000000]", "value":42}'}])
  body={**self.body,'response_format':{'type':'json_object'}}
  chunks=list(Adapter(self.settings,self.state,lambda _:JSONAPI()).run(body,'key'))
  text=''.join(c.get('delta',{}).get('content','') for c in chunks)
  self.assertEqual(json.loads(text),{'text':'中文 [S000000000000]','value':42});self.assertEqual(chunks[-1]['finish_reason'],'stop')
 def test_incomplete_source_and_oversized_url_are_bounded(self):
  l=Ledger();ident=l.source('web','A','https://example.com/a')
  s=ReferenceStream(l);out=s.feed('Before ['+ident+'](https://'+'x'*9000);self.assertLess(len(s.buffer),8193)
  out+=s.feed(') after')+s.finish();self.assertIn('https://example.com/a',out);self.assertTrue(out.endswith(' after'))
  s=ReferenceStream(l);self.assertEqual(s.feed('ok [S123')+s.finish(),'ok （来源标识不完整）')

from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from adapter import Handler

class HTTPStreamingTests(RuntimeFixture):
 def serve(self,api):
  class TestHandler(Handler):pass
  TestHandler.adapter=Adapter(self.settings,self.state,lambda _:api);TestHandler.key_getter=staticmethod(lambda:'key')
  server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  return 'http://127.0.0.1:'+str(server.server_port)+'/chat/completions',TestHandler
 def post(self,url,body):
  return urlopen(Request(url,json.dumps(body).encode(),headers={'Authorization':'Bearer key','Content-Type':'application/json'}),timeout=5)
 def test_real_sse_first_chunk_while_upstream_is_blocked(self):
  release=threading.Event()
  self.addCleanup(release.set)
  class Gated:
   ended=False
   def generate(s,*args):
    yield {'candidates':[{'content':{'parts':[{'text':'First🙂'}]}}]}
    release.wait(2)
    yield response([{'text':' second'}]);s.ended=True
  api=Gated();url,_=self.serve(api)
  with self.post(url,{**self.body,'stream':True}) as r:
   line=r.readline().decode();first=json.loads(line.removeprefix('data: '));self.assertEqual(first['choices'][0]['delta']['content'],'First🙂')
   self.assertFalse(api.ended);self.assertFalse(release.is_set());release.set()
   records=[json.loads(x[6:]) for x in r.read().decode().splitlines() if x.startswith('data: {')]
  self.assertEqual(records[-1]['choices'][0]['finish_reason'],'stop')
  self.assertEqual(''.join(x['choices'][0].get('delta',{}).get('content','') for x in [first]+records).split('\n\n>')[0],'First🙂 second')
 def test_real_sse_partial_error_has_error_and_done(self):
  class Broken:
   def generate(s,*args):
    yield {'candidates':[{'content':{'parts':[{'text':'Keep this.'}]}}]}
    raise TimeoutError('simulated interruption')
  url,_=self.serve(Broken())
  with self.post(url,{**self.body,'stream':True}) as r:data=r.read().decode()
  records=[json.loads(x[6:]) for x in data.splitlines() if x.startswith('data: {')]
  self.assertEqual(records[0]['choices'][0]['delta']['content'],'Keep this.');self.assertIn('未完成',records[-1]['choices'][0]['delta']['content']);self.assertIn('error',records[-1]);self.assertTrue(data.endswith('data: [DONE]\n\n'))
  self.assertEqual(self.state.db.execute('SELECT count(*) FROM histories').fetchone()[0],0)
 def test_real_http_video_timeout_reload_retry_no_reanalysis(self):
  api=RetryAPI();url,handler=self.serve(api)
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with self.post(url,{**self.body,'stream':True}) as r:self.assertIn('继续恢复',r.read().decode())
   self.assertEqual(handler.adapter.active_requests,0);self.state.db.close();self.state=State(self.directory)
   handler.adapter=Adapter(self.settings,self.state,lambda _:api)
   with self.post(url,{**self.body,'stream':True}) as r:text=r.read().decode()
   self.assertEqual(video.call_count,1);self.assertIn('恢复已完成工具',text);self.assertIn(URL,text);self.assertTrue(text.endswith('data: [DONE]\n\n'))
 def test_real_http_nonstream_json(self):
  from test_adapter import FakeAPI
  url,_=self.serve(FakeAPI([response([{'text':'{"value":42}'}])]))
  with self.post(url,{**self.body,'stream':False,'response_format':{'type':'json_object'}}) as r:data=json.load(r)
  self.assertEqual(json.loads(data['choices'][0]['message']['content']),{'value':42});self.assertEqual(data['choices'][0]['finish_reason'],'stop')
 def test_cancel_event_and_length_termination(self):
  cancel=threading.Event()
  class CancelAPI:
   def generate(s,*args):
    yield {'candidates':[{'content':{'parts':[{'text':'Already visible'}]}}]}
    cancel.set();yield response([{'text':'Do not emit'}])
  g=Adapter(self.settings,self.state,lambda _:CancelAPI()).run(self.body,'key',cancel);self.assertEqual(next(g)['delta']['content'],'Already visible')
  with self.assertRaises(Cancelled):list(g)
  from test_adapter import FakeAPI
  final=response([{'text':'Limited'}]);final['candidates'][0]['finishReason']='MAX_TOKENS'
  out=list(Adapter(self.settings,self.state,lambda _:FakeAPI([final])).run(self.body,'key'));self.assertEqual(out[-1]['finish_reason'],'length')

class DuplicateAnalysisCases(RuntimeFixture):
 def test_repeated_function_request_after_recovery_uses_exact_analysis_result(self):
  for changed in (False,True):
   with self.subTest(changed=changed):
    self.state.db.execute('DELETE FROM recovery_checkpoints');self.state.db.commit()
    api=RetryAPI()
    with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
     with self.assertRaises(TimeoutError):list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
     from test_adapter import FakeAPI
     args={**ARGS,'task':'different detail'} if changed else ARGS
     repeat=FakeAPI([response([{'functionCall':{'name':'gemini_analyze_video','id':'repeat','args':args}}]),response([{'text':'Final.'}])])
     result=list(Adapter(self.settings,self.state,lambda _:repeat).run(self.body,'key'))
     self.assertEqual(video.call_count,2 if changed else 1)
     self.assertEqual(result[-1]['usage']['total_tokens'],134 if changed else 24)

class ExpiryTests(RuntimeFixture):
 def test_fresh_write_does_not_extend_original_expiry(self):
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   api=RetryAPI()
   with self.assertRaises(TimeoutError):list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   key,raw=self.state.db.execute('SELECT key,data FROM recovery_checkpoints').fetchone();data=json.loads(raw);data['expires']=time.time()-1
   self.state.db.execute('UPDATE recovery_checkpoints SET data=?,updated=? WHERE key=?',(json.dumps(data),time.time(),key));self.state.db.commit()
   list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'));self.assertEqual(video.call_count,2)

class PartialUsageTests(RuntimeFixture):
 def test_failed_generation_keeps_returned_usage_once(self):
  class PartialUsage(RetryAPI):
   def generate(s,model,payload):
    if any(p.get('functionResponse') for m in payload['contents'] for p in m['parts']) and s.fail:
     s.fail=False
     yield {'usageMetadata':{'promptTokenCount':20,'candidatesTokenCount':3,'totalTokenCount':23},'candidates':[{'content':{'parts':[{'text':'partial'}]}}]}
     raise TimeoutError('after usage')
    yield from super().generate(model,payload)
  api=PartialUsage()
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with self.assertRaises(TimeoutError):list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   raw=self.state.db.execute('SELECT data FROM recovery_checkpoints').fetchone()[0]
   entries=json.loads(raw)['ledger']['usage'];failed=[e for e in entries if e['kind']=='generation_failed']
   self.assertEqual(len(failed),1);self.assertEqual(failed[0]['normalized']['total_tokens'],23)
   out=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'));self.assertEqual(video.call_count,1)
   self.assertIn('恢复前已发生用量 145 tokens',''.join(x.get('delta',{}).get('content','') for x in out))

class DeliveryRetryTests(RuntimeFixture):
 def test_answer_generated_but_client_lost_it_can_retry_without_video(self):
  api=RetryAPI();api.fail=False
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   retry=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   self.assertEqual(video.call_count,1);self.assertEqual(retry[-1]['usage']['total_tokens'],12)
   self.assertIn('恢复前已发生用量 134 tokens',''.join(x.get('delta',{}).get('content','') for x in retry))
