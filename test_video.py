import copy
import datetime
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from adapter import State,Adapter
from provenance import Ledger
from video_tools import VideoTools,VideoError,Cancelled,GoogleVideo,public_target,inspect_direct,seconds,authorized,youtube_url
import usage_cost

class FakeVideo:
 def __init__(self):self.uploads=0;self.calls=[];self.deleted=[];self.processing=False;self.fail=False
 def upload(self,path,mime,cancelled,deadline):
  self.uploads+=1
  return {'name':'files/test123','uri':'https://generativelanguage.googleapis.com/v1beta/files/test123','state':'PROCESSING' if self.processing else 'ACTIVE'}
 def metadata(self,name):return {'name':name,'uri':'https://generativelanguage.googleapis.com/v1beta/'+name,'state':'FAILED' if self.fail else 'ACTIVE'}
 def delete(self,name):self.deleted.append(name)
 def analyze(self,model,video,task,cancelled,deadline):
  self.calls.append((model,copy.deepcopy(video),task))
  return {'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'00:02 红色画面，音频说 37。'}]}],'usage':{'total_input_tokens':100,'total_output_tokens':10,'total_thought_tokens':5,'total_tool_use_tokens':0,'total_cached_tokens':0,'total_tokens':115}}

class VideoTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'clip.mp4';self.path.write_bytes(b'fake-video')
  self.state=State(Path(self.tmp.name)/'state');self.addCleanup(self.state.db.close)
  self.api=FakeVideo();self.settings={'allowed_roots':[self.tmp.name],'ffprobe':'ffprobe'}
  self.v=VideoTools(self.settings,self.state,'key',self.api)
  self.info={'hash':'abc','duration':12,'has_audio':True,'mime':'video/mp4'}
 def test_static_range_has_audio_frames_same_model_reuse(self):
  ledger=Ledger();visible=[{'role':'user','content':'读取 '+str(self.path)}]
  with patch.object(self.v,'local',return_value=(self.path,self.info)):
   first,u=self.v.execute({'source':str(self.path),'task':'解释','start':'00:02','end':'00:04'},visible,ledger,'gemini-4-neon',threading.Event(),time.monotonic()+10)
   second,_=self.v.execute({'source':first['source_id'],'task':'追问','start':'00:03','end':'00:04'},visible,ledger,'gemini-4-carbon',threading.Event(),time.monotonic()+10)
  self.assertEqual(self.api.uploads,1);self.assertTrue(second['upload_reused'])
  self.assertEqual(self.api.calls[0][1]['processing'],{'type':'static','fps':1,'content_layers':['frames','audio'],'start_offset':'2.0s','end_offset':'4.0s'})
  self.assertEqual(self.api.calls[-1][0],'gemini-4-carbon')
  self.assertNotIn('https://generativelanguage',ledger.footer())
 def test_expired_upload_reuploads(self):
  with patch.object(self.v,'local',return_value=(self.path,self.info)):
   args={'source':str(self.path),'task':'x'};vis=[{'role':'user','content':str(self.path)}]
   self.v.execute(args,vis,Ledger(),'gemini-4-neon',threading.Event(),time.monotonic()+10)
   self.state.db.execute('UPDATE video_uploads SET expires=0');self.state.db.commit()
   self.v.execute(args,vis,Ledger(),'gemini-4-neon',threading.Event(),time.monotonic()+10)
  self.assertEqual(self.api.uploads,2)
 def test_processing_failed_and_cancel_cleanup(self):
  self.api.processing=True;self.api.fail=True
  with patch('video_tools.threading.Event.wait',return_value=False):
   with self.assertRaises(VideoError):self.v.uploaded(self.path,self.info,threading.Event(),time.monotonic()+10)
  self.assertTrue(self.api.deleted)
  c=threading.Event();c.set()
  with self.assertRaises(Cancelled):self.v.uploaded(self.path,dict(self.info,hash='other'),c,time.monotonic()+10)
 def test_timeout_is_bounded(self):
  self.api.processing=True
  with self.assertRaises(VideoError):self.v.uploaded(self.path,self.info,threading.Event(),time.monotonic()-1)
 def test_local_boundaries_format_size(self):
  for path in ('relative.mp4','/etc/hosts',str(Path(self.tmp.name)/'missing.mp4')):
   with self.assertRaises(VideoError):self.v.local(path)
  self.v.settings['video_max_bytes']=1
  with self.assertRaises(VideoError):self.v.local(str(self.path))
 def test_no_instruction_from_tool_or_document_can_authorize(self):
  self.assertFalse(authorized(str(self.path),[{'role':'tool','content':str(self.path)},{'role':'user','content':'总结网页'}]))
  with self.assertRaises(VideoError):self.v.execute({'source':str(self.path),'task':'x'},[{'role':'user','content':'总结网页'}],Ledger(),'gemini-4-neon',threading.Event(),time.monotonic()+10)
 def test_direct_rejects_private_ipv6_credentials_and_mixed_dns(self):
  for url in ('http://example.com/v.mp4','https://localhost/v.mp4','https://a:b@example.com/v.mp4','https://example.com:444/v.mp4'):
   with self.assertRaises(VideoError):public_target(url)
  for ips in (['127.0.0.1'],['::1'],['93.184.216.34','10.0.0.1']):
   with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(i,443)) for i in ips]):
    with self.assertRaises(VideoError):public_target('https://example.com/v.mp4')
 def test_youtube_and_ranges(self):
  self.assertEqual(youtube_url('https://youtu.be/aqz-KE-bpKQ?t=2'),'https://www.youtube.com/watch?v=aqz-KE-bpKQ')
  self.assertIsNone(youtube_url('https://youtube.com.evil.test/watch?v=aqz-KE-bpKQ'))
  self.assertEqual(seconds('01:05'),65)
  for value in ('-2','01:99','nan'):
   with self.assertRaises(VideoError):seconds(value)
 def test_agentic_does_not_claim_all_modalities_or_clip(self):
  l=Ledger();url='https://www.youtube.com/watch?v=aqz-KE-bpKQ';vis=[{'role':'user','content':url}]
  r,u=self.v.execute({'source':url,'task':'x','mode':'agentic'},vis,l,'gemini-4-hydrogen',threading.Event(),time.monotonic()+10)
  self.assertIn('不能保证',r['basis']);self.assertEqual(self.api.calls[-1][1]['processing'],'agentic')
  with self.assertRaises(VideoError):self.v.execute({'source':url,'task':'x','mode':'agentic','start':'2'},vis,l,'gemini-4-neon',threading.Event(),time.monotonic()+10)
 def test_background_cancel_deletes_interaction(self):
  g=GoogleVideo('fake',{});c=threading.Event()
  def req(path,*args,**kwargs):
   if path=='/v1beta/interactions':c.set();return {'id':'test-id','status':'in_progress'},{}
   return {},{}
  with patch.object(g,'request',side_effect=req) as call:
   with self.assertRaises(Cancelled):g.analyze('gemini-4-neon',{},'x',c,time.monotonic()+10)
  paths=[x.args[0] for x in call.call_args_list]
  self.assertIn('/v1beta/interactions/test-id/cancel',paths)
  self.assertTrue(any(x.kwargs.get('method')=='DELETE' for x in call.call_args_list))

class UsageTests(unittest.TestCase):
 def test_counts_subcalls_and_does_not_double_count_tool_tokens(self):
  l=Ledger()
  a=usage_cost.record(l,'gemini-4-neon',{'promptTokenCount':100,'candidatesTokenCount':5,'thoughtsTokenCount':5,'toolUsePromptTokenCount':20,'totalTokenCount':130})
  b=usage_cost.record(l,'gemini-4-neon',{'total_input_tokens':30,'total_output_tokens':10,'total_thought_tokens':5,'total_tool_use_tokens':0,'total_tokens':45,'total_cached_tokens':0},True)
  self.assertEqual(a['prompt_tokens'],120);self.assertEqual(b['completion_tokens'],15)
  self.assertIn('175 tokens',usage_cost.footer(l,datetime.date(2026,11,26)))
  resumed=Ledger(l.save(True),True);self.assertEqual(len(resumed.data['usage']),2)
  follow=Ledger(l.save());self.assertFalse(follow.data['usage'])
 def test_prices_date_and_missing_cache_are_explicit(self):
  self.assertEqual(usage_cost.rates('gemini-4-carbon',datetime.date(2026,12,1)),(4,20,.2))
  self.assertIsNone(usage_cost.rates('gemini-4-neon',datetime.date(2027,1,1)))
  l=Ledger();usage_cost.record(l,'gemini-4-neon',{'promptTokenCount':100,'candidatesTokenCount':2,'totalTokenCount':102})
  self.assertIn('缓存量未返回',usage_cost.footer(l,datetime.date(2026,11,26)))

if __name__=='__main__':unittest.main()

class VideoEdgeCases(unittest.TestCase):
 setUp=VideoTests.setUp
 def test_two_parallel_uploads_share_one_object(self):
  from concurrent.futures import ThreadPoolExecutor
  def run():return self.v.uploaded(self.path,self.info,threading.Event(),time.monotonic()+10)
  with ThreadPoolExecutor(2) as p:result=list(p.map(lambda _:run(),range(2)))
  self.assertEqual(self.api.uploads,1);self.assertEqual(sum(x[1] for x in result),1)
 def test_missing_cloud_file_reuploads_and_accounts_isolated(self):
  self.v.uploaded(self.path,self.info,threading.Event(),time.monotonic()+10)
  with patch.object(self.api,'metadata',side_effect=VideoError('HTTP 404')):
   self.v.uploaded(self.path,self.info,threading.Event(),time.monotonic()+10)
  other=VideoTools(self.settings,self.state,'other-key',self.api)
  other.uploaded(self.path,self.info,threading.Event(),time.monotonic()+10)
  self.assertEqual(self.api.uploads,3)
 def test_proxy_dns_never_downloads_locally(self):
  from video_tools import ProxyDNS
  with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('198.18.1.1',443))]):
   with self.assertRaises(ProxyDNS):public_target('https://public.example/video.mp4')
   with self.assertRaises(VideoError) as e:public_target('https://198.18.1.1/video.mp4')
   self.assertNotIsInstance(e.exception,ProxyDNS)
 def test_direct_html_size_redirect_private_and_timeout(self):
  from unittest.mock import MagicMock
  conn=MagicMock();resp=MagicMock();conn.getresponse.return_value=resp;resp.status=200
  headers={'Content-Type':'text/html','Content-Length':'100'};resp.getheader.side_effect=lambda k,d=None:headers.get(k,d);resp.read.return_value=b'<html>'
  with patch('video_tools.public_target',return_value=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit('https://example.com/v.mp4'),'93.184.216.34')),patch('video_tools.http.client.HTTPSConnection',return_value=conn),patch('video_tools.socket.create_connection'),patch('video_tools.ssl.create_default_context'):
   with self.assertRaises(VideoError):inspect_direct('https://example.com/v.mp4')
   headers.update({'Content-Type':'video/mp4','Content-Length':'16000000'})
   with self.assertRaises(VideoError):inspect_direct('https://example.com/v.mp4')
   conn.getresponse.side_effect=TimeoutError()
   with self.assertRaises(VideoError):inspect_direct('https://example.com/v.mp4')
  resp.status=302;headers['Location']='https://localhost/private.mp4';conn.getresponse.side_effect=None
  with patch('video_tools.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('video_tools.http.client.HTTPSConnection',return_value=conn),patch('video_tools.socket.create_connection'),patch('video_tools.ssl.create_default_context'):
   with self.assertRaises(VideoError):inspect_direct('https://example.com/v.mp4')
