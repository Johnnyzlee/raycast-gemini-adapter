import copy,json,re,threading,time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_retry_stream import RuntimeFixture,RetryAPI,video_ok,ARGS
from test_adapter import FakeAPI,response
from adapter import Adapter,AdapterError
from provenance import Ledger

class AuditTests(RuntimeFixture):
 def test_negative_reanalysis_instruction_still_reuses(self):
  for suffix in ('不要重新分析','不重新分析','不需要重新分析','无须重新分析','不要再次重新分析','do not reanalyze'):
   with self.subTest(suffix=suffix):
    body=copy.deepcopy(self.body);body['messages'][0]['content']+=' '+suffix;api=RetryAPI()
    with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
     with self.assertRaises(TimeoutError):list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'))
     list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'));self.assertEqual(video.call_count,1)
 def test_long_session_ids_do_not_share_receipts(self):
  body=copy.deepcopy(self.body);body['conversation_id']='x'*256+'A';api=RetryAPI()
  with patch('adapter.VideoTools.execute',side_effect=video_ok):
   with self.assertRaises(TimeoutError) as e:list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'))
   token=re.search(r'继续恢复 ([a-f0-9]{32})',str(e.exception))[1]
   other={**body,'conversation_id':'x'*256+'B','messages':[{'role':'user','content':'继续恢复 '+token}]}
   with self.assertRaises(AdapterError):list(Adapter(self.settings,self.state,lambda _:api).run(other,'key'))
 def test_unrelated_old_video_does_not_block_current_result(self):
  def with_old(*args):
   l=args[2];i=l.source('video','Old',identity='old',original_source=self.tmp.name+'/deleted.mp4',content_hash='old')
   l.event('视频原生分析','success',[i]);return video_ok(*args)
  api=RetryAPI()
  with patch('adapter.VideoTools.execute',side_effect=with_old) as video:
   with self.assertRaises(TimeoutError):list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'));self.assertEqual(video.call_count,1)
 def test_recovered_failure_is_not_labelled_success(self):
  l=Ledger();l.event('Google Maps','failed',recovered=True);l.event('视频原生分析','success',recovered=True)
  text=l.footer();self.assertIn('Google Maps（失败）',text)
  self.assertNotIn('沿用成功结果',text)
 def test_json_discards_tool_round_preamble(self):
  api=FakeAPI([response([{'text':'{"status":"working"}'},{'functionCall':{'name':'gemini_analyze_video','id':'v','args':ARGS}}]),response([{'text':'{"answer":17}'}])])
  with patch('adapter.VideoTools.execute',side_effect=video_ok):out=list(Adapter(self.settings,self.state,lambda _:api).run({**self.body,'response_format':{'type':'json_object'}},'key'))
  self.assertEqual(json.loads(''.join(x.get('delta',{}).get('content','') for x in out)),{'answer':17})
 def test_concurrent_identical_requests_analyze_once(self):
  started=threading.Event();release=threading.Event();twice=threading.Event();count=0;guard=threading.Lock()
  def blocked(*args):
   nonlocal count
   with guard:count+=1;n=count
   started.set()
   if n==2:twice.set()
   release.wait(2);return video_ok(*args)
  def api_factory(_):api=RetryAPI();api.fail=False;return api
  a=Adapter(self.settings,self.state,api_factory)
  with patch('adapter.VideoTools.execute',side_effect=blocked),ThreadPoolExecutor(2) as pool:
   first=pool.submit(lambda:list(a.run(self.body,'key')));self.assertTrue(started.wait(1))
   second=pool.submit(lambda:list(a.run(self.body,'key')))
   twice.wait(.15);release.set();first.result(timeout=3);second.result(timeout=3)
  self.assertEqual(count,1)
 def test_failed_subcall_usage_is_not_omitted(self):
  class MapsAPI:
   n=0
   def generate(s,model,payload):
    if payload['tools']==[{'googleMaps':{}}]:raise TimeoutError('synthetic maps failure')
    s.n+=1
    yield response([{'functionCall':{'name':'gemini_google_maps','id':'m','args':{'query':'test'}}}] if s.n==1 else [{'text':'Maps failed.'}])
  api=MapsAPI();out=list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
  self.assertIn('1 个调用未返回用量',''.join(x.get('delta',{}).get('content','') for x in out))

 def test_invalid_final_json_keeps_usage_and_stable_checkpoint(self):
  body={**self.body,'response_format':{'type':'json_object'}}
  api=FakeAPI([response([{'functionCall':{'name':'gemini_analyze_video','id':'v','args':ARGS}}]),response([{'text':'not valid json'}])])
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with self.assertRaises(AdapterError):list(Adapter(self.settings,self.state,lambda _:api).run(body,'key'))
   saved=json.loads(self.state.db.execute('SELECT data FROM recovery_checkpoints').fetchone()[0])
   self.assertEqual(sum(e['normalized']['total_tokens'] for e in saved['ledger']['usage']),134)
   self.assertNotIn('not valid json',json.dumps(saved['history']))
   good=FakeAPI([response([{'text':'{"ok":true}'}])]);list(Adapter(self.settings,self.state,lambda _:good).run(body,'key'));self.assertEqual(video.call_count,1)
 def test_successful_maps_after_video_is_not_repeated_on_later_cancel(self):
  from video_tools import Cancelled
  calls=[{'functionCall':{'name':'gemini_analyze_video','id':'v','args':ARGS}}, {'functionCall':{'name':'gemini_google_maps','id':'m','args':{'query':'test'}}}, {'functionCall':{'name':'gemini_view_image','id':'i','args':{'path':'/synthetic.png'}}}]
  maps=response([{'toolCall':{'toolType':'GOOGLE_MAPS'}},{'text':'Place'}],{'groundingChunks':[{'maps':{'title':'Place','uri':'https://maps.google.com/?q=test'}}]})
  api=FakeAPI([response(calls),maps])
  with patch('adapter.VideoTools.execute',side_effect=video_ok) as video:
   with patch('adapter.FileTools.read',side_effect=Cancelled('cancel image')),self.assertRaises(Cancelled):list(Adapter(self.settings,self.state,lambda _:api).run(self.body,'key'))
   resumed=FakeAPI([response([{'text':'Done'}])])
   with patch('adapter.FileTools.read',return_value=('synthetic.png',[{'text':'image'}])):list(Adapter(self.settings,self.state,lambda _:resumed).run(self.body,'key'))
   self.assertEqual(video.call_count,1);self.assertEqual(len(resumed.requests),1)
 def test_waiting_duplicate_can_be_cancelled(self):
  from adapter import request_scope,retry_identity,digest
  from video_tools import Cancelled
  scope=request_scope(self.body,'key')[2];identity=retry_identity(self.body,self.settings,scope)
  lock=self.state.request_locks[int(digest(identity),16)%64];lock.acquire();self.addCleanup(lock.release)
  cancelled=threading.Event();cancelled.set();api=FakeAPI([]);a=Adapter(self.settings,self.state,lambda _:api)
  with self.assertRaises(Cancelled):list(a.run(self.body,'key',cancelled))
  self.assertEqual(api.requests,[]);self.assertEqual(a.active_requests,0)

import test_retry_stream as retry_helpers
from urllib.error import HTTPError
class RequestShapeTests(RuntimeFixture):
 serve=retry_helpers.HTTPStreamingTests.serve
 post=retry_helpers.HTTPStreamingTests.post
 def test_malformed_requests_return_json_400_without_generation(self):
  api=FakeAPI([]);url,_=self.serve(api)
  for body in ([],{'messages':[]},{'messages':['bad']},{**self.body,'stream':'yes'},{**self.body,'metadata':[]},{**self.body,'response_format':[]}):
   with self.subTest(body=type(body).__name__),self.assertRaises(HTTPError) as e:self.post(url,body)
   self.assertEqual(e.exception.code,400);self.assertIn('error',json.loads(e.exception.read()))
  self.assertEqual(api.requests,[])
 def test_null_optional_fields_remain_compatible(self):
  api=FakeAPI([response([{'text':'OK'}])]);url,_=self.serve(api)
  with self.post(url,{**self.body,'stream':None,'metadata':None,'response_format':None,'tools':None}) as r:data=json.load(r)
  self.assertEqual(data['choices'][0]['finish_reason'],'stop');self.assertTrue(data['choices'][0]['message']['content'].startswith('OK'))

class FailedUsageDisplayTests(RuntimeFixture):
 def test_returned_partial_failure_usage_keeps_unknown_remainder(self):
  import usage_cost,datetime
  ledger=Ledger();usage_cost.record(ledger,'gemini-4-neon',{'promptTokenCount':10,'candidatesTokenCount':1,'totalTokenCount':11},kind='maps_failed')
  self.assertIn('未返回部分未知',usage_cost.footer(ledger,datetime.date(2026,11,26)))
