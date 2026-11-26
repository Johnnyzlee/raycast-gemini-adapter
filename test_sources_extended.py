import base64,copy,tempfile,time,unittest
from pathlib import Path
from adapter import Adapter,State,merge_grounding,convert_messages,FileTools,digest
from provenance import Ledger
from test_adapter import FakeAPI,response

class ExtendedSources(unittest.TestCase):
 def test_stream_metadata_preserves_index_mapping(self):
  a={'groundingChunks':[{'web':{'uri':'https://a.test','title':'A'}}],'groundingSupports':[{'segment':{'text':'A'},'groundingChunkIndices':[0]}]}
  b={'groundingChunks':[{'web':{'uri':'https://b.test','title':'B'}}],'groundingSupports':[{'segment':{'text':'B'},'groundingChunkIndices':[0]}]}
  merged=merge_grounding(a,b);self.assertEqual(merged['groundingSupports'][1]['groundingChunkIndices'],[1]);self.assertEqual(merge_grounding(merged,b),merged)
  l=Ledger();out=l.native([],merged,{},'A B');self.assertIn('https://a.test',out);self.assertIn('https://b.test',out)
 def test_native_handoff_suggestions_without_invented_urls(self):
  l=Ledger();html='<style>a{color:red}</style><a href="https://www.google.com/search?q=test">test</a>'
  l.native([{'toolCall':{'toolType':'GOOGLE_SEARCH_WEB'}},{'toolResponse':{'toolType':'GOOGLE_SEARCH_WEB','response':{'search_suggestions':html}}}],{}, {},'')
  p=l.save(True);self.assertEqual(p['events'][0]['suggestions_html'],html);self.assertFalse(p['records'])
  self.assertIn('Google 搜索建议',Ledger(p,True).footer());self.assertIn('部分成功',Ledger(p,True).footer())
 def test_url_dedup_maps_labels_and_video_ranges(self):
  l=Ledger();a=l.source('search','Title','https://a.test');b=l.source('web','实际读取网页','https://a.test')
  self.assertEqual(a,b);self.assertEqual(l.data['records'][b]['title'],'Title')
  l.native([],{'groundingChunks':[{'web':{'uri':'https://maps.google.com/a','title':'Place'}}],'webSearchQueries':['Place']},{},'',tool_hint='Google Maps')
  self.assertEqual(l.data['events'][-1]['tool'],'Google Maps')
  x=l.source('video','Video','https://a.test/v',identity='range1',range={'start':1});y=l.source('video','Video','https://a.test/v',identity='range2',range={'start':2})
  self.assertNotEqual(x,y);self.assertEqual(l.data['records'][x]['range'],{'start':1})
 def test_source_expiry_linked_history_and_attachments(self):
  l=Ledger();i=l.source('search','A','https://a.test');l.event('Google 搜索','success',[i]);p=l.save()
  follow=Ledger(p);self.assertIn('https://a.test',follow.render_refs('['+i+'](https://fake.test)'));self.assertIn('沿用历史',follow.footer())
  p['events'][0]['at']=time.time()-4*86400;self.assertFalse(Ledger(p).data['records'])
  with tempfile.TemporaryDirectory() as tmp:
   convert_messages([{'role':'user','content':[{'type':'file','file':{'filename':'test.pdf','file_data':base64.b64encode(b'fixture').decode()}}]}],FileTools({'allowed_roots':[tmp]}),ledger=l)
  self.assertTrue(any(r['title']=='test.pdf' for r in l.data['records'].values()))
 def test_external_parallel_local_and_cross_model_sources(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'test.txt';path.write_text('safe fixture');state=State(tmp)
   self.addCleanup(state.db.close)
   api=FakeAPI([response([{'functionCall':{'name':'gemini_open_document','id':'local','args':{'path':str(path)}}},{'functionCall':{'name':'lookup','id':'ext','args':{}}}]),response([{'text':'Done.'}]),response([{'text':'Switch.'}]),response([{'text':'Separate.'}])])
   a=Adapter({'allowed_roots':[tmp],'timezone':'Asia/Hong_Kong','strict_file_authorization':True},state,lambda _:api)
   b={'model':'gemini-4-neon','conversation_id':'chat-A','messages':[{'role':'user','content':str(path)}],'tools':[{'type':'function','function':{'name':'lookup'}}]}
   chunks=list(a.run(b,'key'));calls=next(x['delta']['tool_calls'] for x in chunks if x.get('delta',{}).get('tool_calls'))
   b['messages'] += [{'role':'assistant','content':'','tool_calls':calls},{'role':'tool','tool_call_id':'ext','content':'{"status":"failed","error":"fixture"}'}]
   out=''.join(x.get('delta',{}).get('content','') for x in a.run(b,'key'))
   self.assertIn('test.txt',out);self.assertIn('Raycast lookup（失败）',out)
   b['messages'] += [{'role':'assistant','content':out},{'role':'user','content':'continue'}];b['model']='gemini-4-carbon';list(a.run(b,'key'))
   self.assertIn('test.txt',api.requests[-1]['systemInstruction']['parts'][0]['text'])
   b['conversation_id']='chat-B';b['messages']=[{'role':'user','content':'hello'}];list(a.run(b,'key'))
   self.assertNotIn('test.txt',api.requests[-1]['systemInstruction']['parts'][0]['text'])
 def test_historical_grounding_is_not_new_tool_execution(self):
  l=Ledger();i=l.source('search','A','https://a.test');l.event('Google 搜索','success',[i])
  follow=Ledger(l.save());follow.native([],{'groundingChunks':[{'web':{'title':'A','uri':'https://a.test'}}]}, {},'Use existing source.')
  self.assertIn('沿用历史',follow.footer());self.assertNotIn('本次工具',follow.footer())
