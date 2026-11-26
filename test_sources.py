import copy
import tempfile
import unittest
from pathlib import Path
from adapter import Adapter,State
from test_adapter import FakeAPI,response

class SourceFlowTests(unittest.TestCase):
 def test_search_raycast_final_keeps_sources(self):
  with tempfile.TemporaryDirectory() as tmp:
   state=State(Path(tmp)/'state')
   api=FakeAPI([response([{'toolCall':{'toolType':'GOOGLE_SEARCH_WEB'}},{'text':'Found result.'},{'functionCall':{'name':'lookup','args':{},'id':'external'},'thoughtSignature':'sig'}],{'groundingChunks':[{'web':{'title':'Example','uri':'https://example.com/fact'}}],'searchEntryPoint':{'renderedContent':'<a href="https://www.google.com/search?q=test">test</a>'}}),response([{'text':'Final answer.'}])])
   a=Adapter({'allowed_roots':[tmp],'timezone':'Asia/Hong_Kong'},state,lambda _:api)
   b={'model':'gemini-4-neon','messages':[{'role':'user','content':'Search then lookup'}],'tools':[{'type':'function','function':{'name':'lookup'}}]}
   chunks=list(a.run(b,'key'))
   text=''.join(c.get('delta',{}).get('content','') for c in chunks)
   calls=next(c['delta']['tool_calls'] for c in chunks if c.get('delta',{}).get('tool_calls'))
   b['messages'] += [{'role':'assistant','content':text,'tool_calls':calls},{'role':'tool','tool_call_id':'external','content':'{"value":37}'}]
   out=''.join(c.get('delta',{}).get('content','') for c in a.run(b,'key'))
   self.assertIn('https://example.com/fact',out)
   self.assertIn('Google 搜索',out)
   self.assertIn('Google 搜索建议',out)
   state.db.close()

if __name__=='__main__':unittest.main()

from provenance import Ledger,sid
import time

class LedgerTests(unittest.TestCase):
 def test_exact_support_dedupe_and_invalid_reference(self):
  l=Ledger();g={'groundingChunks':[{'web':{'title':'A','uri':'https://example.com/a'}},{'web':{'title':'A','uri':'https://example.com/a'}}], 'groundingSupports':[{'segment':{'text':'Fact A.'},'groundingChunkIndices':[0,1]}]}
  out=l.native([],g,{},'Fact A. Unrelated conclusion.')
  ident=sid('url','https://example.com/a')
  self.assertEqual(out.count('[1]'),1);self.assertNotIn(ident,out)
  self.assertTrue(out.startswith('Fact A. ['))
  self.assertEqual(len(l.data['records']),1)
  self.assertIn('无效',l.render_refs('[S000000000000]'))
 def test_followup_old_new_and_irrelevant_sources(self):
  l=Ledger();a=l.source('search','A','https://example.com/a');b=l.source('search','B','https://example.com/b')
  l.event('Google 搜索','success',[a,b]);saved=l.save()
  follow=Ledger(saved);follow.render_refs('Use ['+a+']')
  footer=follow.footer();self.assertIn('来源：',footer);self.assertNotIn('本次工具',footer);self.assertNotIn('example.com/b',footer)
  c=follow.source('web','C','https://example.com/c');follow.event('网页读取','success',[c])
  self.assertIn('example.com/a',follow.footer());self.assertIn('example.com/c',follow.footer())
 def test_failure_is_not_success(self):
  l=Ledger();l.native([],{}, {'urlMetadata':[{'retrievedUrl':'https://example.com/private','urlRetrievalStatus':'URL_RETRIEVAL_STATUS_ERROR'}]},'')
  self.assertNotIn('https://example.com/private',l.footer());self.assertIn('失败',l.footer())
  l.event('网页读取','success');self.assertIn('部分成功',l.footer())
 def test_metadata_legacy_expiry_and_account_boundaries(self):
  with tempfile.TemporaryDirectory() as tmp:
   state=State(tmp);visible=[{'role':'user','content':'q'},{'role':'assistant','content':'A'}]
   ledger=Ledger();i=ledger.source('web','A','https://example.com/a');ledger.event('网页读取','success',[i])
   state.remember(visible,[{'role':'model','parts':[{'text':'A'}]}],'account',ledger.save())
   self.assertIn(i,state.restore(visible,'account',True)[3]['records'])
   self.assertFalse(state.restore(visible,'other',True)[2])
   self.assertFalse(state.restore([{'role':'user','content':'different'}],'account',True)[2])
   state.db.execute('UPDATE histories SET updated=?',(time.time()-4*86400,));state.db.commit()
   self.assertFalse(state.restore(visible,'account',True)[2])
   state.remember(visible,[],'old')
   self.assertEqual(state.restore(visible,'old',True)[3],{})
   state.db.close()
