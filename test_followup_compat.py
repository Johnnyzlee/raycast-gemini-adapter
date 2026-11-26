"""Regression tests for client reserialization, chained tools and model changes."""
import copy
import json
import time
import unittest
from adapter import State, canonical, digest
import test_adapter
from test_adapter import response


class FollowupTests(unittest.TestCase):
    setUp = test_adapter.Tests.setUp
    adapter = test_adapter.Tests.adapter
    body = test_adapter.Tests.body
    def finish_call(self, b, chunks, result='{"value":37}'):
        calls = next(c['delta']['tool_calls'] for c in chunks if c.get('delta', {}).get('tool_calls'))
        b['messages'].append({'role':'assistant', 'content':None, 'tool_calls':calls})
        b['messages'] += [{'role':'tool', 'tool_call_id':c['id'], 'content':result} for c in calls]

    def test_empty_tool_arrays_keep_signed_history(self):
        for extra in ([], None):
            with self.subTest(extra=extra):
                signed = {'text':'normal', 'thoughtSignature':'signature'}
                a, api = self.adapter([response([signed]), response([{'text':'continued'}])])
                b = self.body(str(extra)); list(a.run(b, 'fake'))
                b['messages'] += [{'role':'assistant','content':'normal','tool_calls':extra}, {'role':'user','content':'continue'}]
                list(a.run(b, 'fake'))
                self.assertEqual(api.requests[-1]['contents'][1]['parts'], [signed])

    def test_reformatted_tool_intro_and_null_arguments(self):
        fn = {'functionCall':{'name':'lookup','args':{},'id':'lookup-1'},'thoughtSignature':'signed'}
        a, api = self.adapter([response([{'text':'Checking [source](<https://example.com>)'}, fn]), response([{'text':'37'}])])
        b = self.body(); b['tools']=[{'type':'function','function':{'name':'lookup'}}]
        self.finish_call(b, list(a.run(b,'fake')))
        b['messages'][-2]['content']='Checking source'
        b['messages'][-2]['tool_calls'][0]['function']['arguments']=None
        list(a.run(b,'fake'))
        self.assertIn(fn, api.requests[-1]['contents'][1]['parts'])

    def test_markdown_and_empty_calls_normal_reply(self):
        text='Source [A](<https://example.com>)'
        a, api = self.adapter([response([{'text':text,'thoughtSignature':'sig'}]),response([{'text':'yes'}])])
        b=self.body();list(a.run(b,'fake'))
        b['messages'] += [{'role':'assistant','content':text.replace('<','').replace('>',''),'tool_calls':[]},{'role':'user','content':'continue'}]
        list(a.run(b,'fake'))
        self.assertEqual(api.requests[-1]['contents'][1]['parts'][0]['thoughtSignature'],'sig')

    def test_model_switch_carries_tool_result_without_old_signature(self):
        fn={'functionCall':{'name':'lookup','args':{},'id':'lookup-switch'},'thoughtSignature':'old-model'}
        a, api=self.adapter([response([fn]),response([{'text':'37'}]),response([{'text':'38'}])])
        b=self.body(); b['tools']=[{'type':'function','function':{'name':'lookup'}}]
        self.finish_call(b,list(a.run(b,'fake')))
        b['model']='gemini-4-carbon';list(a.run(b,'fake'))
        raw=json.dumps(api.requests[-1]['contents'])
        self.assertNotIn('thoughtSignature',raw)
        self.assertIn('37',raw)
        self.assertFalse(any('functionCall' in p or 'functionResponse' in p for m in api.requests[-1]['contents'] for p in m['parts']))
        b['messages'] += [{'role':'assistant','content':'37'},{'role':'user','content':'plus one'}]
        list(a.run(b,'fake'))
        self.assertIn('37',json.dumps(api.requests[-1]['contents']))

    def test_model_switch_keeps_document_and_python_separation(self):
        p=self.root/'check.pdf'; p.write_bytes(b'%PDF verification')
        fn={'functionCall':{'name':'gemini_open_document','args':{'path':str(p)},'id':'doc'},'thoughtSignature':'old'}
        a,api=self.adapter([response([fn]),response([{'text':'document loaded'}]),response([{'text':'continued'}])])
        b=self.body(); chunks=list(a.run(b,'fake'))
        visible_answer=''.join(c.get('delta',{}).get('content','') for c in chunks)
        # Visible footer is part of the client transcript.
        b['messages'] += [{'role':'assistant','content':visible_answer}, {'role':'user','content':'continue'}]
        b['model']='gemini-4-hydrogen';list(a.run(b,'fake'))
        parts=[p for m in api.requests[-1]['contents'] for p in m['parts']]
        self.assertTrue(any(p.get('inlineData',{}).get('mimeType')=='application/pdf' for p in parts))
        self.assertNotIn({'codeExecution':{}},api.requests[-1]['tools'])

    def test_mixed_parallel_tools_then_another_external_round(self):
        p=self.root/'data.txt';p.write_text('code TEST-37')
        local={'functionCall':{'name':'gemini_open_document','args':{'path':str(p)},'id':'local'}}
        ext={'functionCall':{'name':'lookup','args':{'q':'a'},'id':'external'},'thoughtSignature':'s1'}
        nxt={'functionCall':{'name':'lookup','args':{'q':'b'},'id':'external2'},'thoughtSignature':'s2'}
        a,api=self.adapter([response([local,ext]),response([nxt]),response([{'text':'done'}])])
        b=self.body();b['tools']=[{'type':'function','function':{'name':'lookup'}}]
        self.finish_call(b,list(a.run(b,'fake')), '{"error":"temporary failure"}')
        self.finish_call(b,list(a.run(b,'fake')), '[{"value":37}]')
        list(a.run(b,'fake'))
        first_results=api.requests[1]['contents'][-1]['parts']
        self.assertEqual(sum('functionResponse' in p for p in first_results),2)
        self.assertIn('TEST-37',json.dumps(api.requests[-1]['contents']))
        self.assertIn('temporary failure',json.dumps(api.requests[-1]['contents']))
        self.assertEqual(api.requests[-1]['contents'][-1]['parts'][0]['functionResponse']['id'],'external2')

    def test_pending_alias_persists_and_is_scoped(self):
        visible=[{'role':'user','content':'q'},{'role':'assistant','content':'intro','tool_calls':[{'id':'id1','type':'function','function':{'name':'lookup','arguments':'{}'}}]}]
        native=[{'role':'model','parts':[{'functionCall':{'id':'id1','name':'lookup','args':{}},'thoughtSignature':'secret'}]}]
        self.state.remember(visible,native,'account-model')
        reopened=State(self.root/'state');self.addCleanup(reopened.db.close)
        altered=copy.deepcopy(visible);altered[-1]['content']='formatted intro'
        self.assertTrue(reopened.restore(altered,'account-model')[2])
        self.assertFalse(reopened.restore(altered,'other-account')[2])
        altered[-1]['tool_calls'][0]['id']='id2'
        self.assertFalse(reopened.restore(altered,'account-model')[2])

    def test_pre_upgrade_history_is_readable(self):
        visible=[{'role':'user','content':'q'},{'role':'assistant','content':'[A](<https://example.com>)'}]
        native=[{'role':'model','parts':[{'text':'answer','thoughtSignature':'sig'}]}]
        self.state.db.execute('INSERT INTO histories VALUES (?,?,?)',('scope:'+digest(canonical(visible,True)),json.dumps(native),time.time()))
        self.state.db.commit()
        self.assertEqual(self.state.restore(visible,'scope')[0],native)


if __name__=='__main__':
    unittest.main()
