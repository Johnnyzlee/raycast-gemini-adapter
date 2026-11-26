import re,unittest
from provenance import Ledger,ReferenceStream,source_caption

class SourceDisplayTests(unittest.TestCase):
 def test_each_source_one_short_clickable_line_without_internal_ids(self):
  l=Ledger();a=l.source('search','新华网：官方公布的数据','https://www.news.cn/economy/data.htm');b=l.source('search','一种新的计算方法','https://unconfirmed.example/article')
  l.event('Google 搜索','success',[a,b]);body=l.render_refs('依据 ['+a+'] 与 ['+b+']。');footer=l.footer()
  self.assertIn('[1](<https://www.news.cn/economy/data.htm>)',body)
  self.assertIn('- [1] [新华网：官方公布的数据]',footer);self.assertIn('- [2] [一种新的计算方法]',footer)
  self.assertEqual(len([x for x in footer.splitlines() if x.startswith('- ')]),2)
  self.assertNotRegex(body+footer,r'S[0-9a-f]{12}');self.assertNotIn('搜索命中',footer);self.assertNotIn('未提供逐句',footer)
 def test_followup_mapping_persists_dedup_and_no_irrelevant_source(self):
  l=Ledger();a=l.source('search','A','https://example.com/a');b=l.source('search','B','https://example.com/b');l.event('Google 搜索','success',[a,b]);l.footer()
  follow=Ledger(l.save());self.assertIn('[2]',follow.render_refs('Use ['+b+']'))
  c=follow.source('web','C','https://example.com/c');follow.event('网页读取','success',[c])
  self.assertEqual(c,follow.source('web','C','https://example.com/c'))
  footer=follow.footer();self.assertIn('- [2]',footer);self.assertIn('- [3]',footer);self.assertNotIn('example.com/a',footer);self.assertNotIn(b,footer)
  self.assertIn('"display_number": 2',follow.prompt())
 def test_only_acquired_snippet_used_not_grounding_support_prose(self):
  l=Ledger();url='https://www.news.cn/article';g={'groundingChunks':[{'web':{'uri':url,'title':'news.cn'}}],'groundingSupports':[{'segment':{'text':'This assertion is model prose'},'groundingChunkIndices':[0]}]}
  l.native([],g,{},'This assertion is model prose');self.assertEqual(source_caption(next(iter(l.data['records'].values()))),'新华网')
  parts=[{'toolResponse':{'toolType':'GOOGLE_SEARCH_WEB','response':{'results':[{'url':url,'snippet':'官方公布的数据'}]}}}]
  l.native(parts,g,{},'');self.assertIn('[新华网：官方公布的数据]',l.footer())
 def test_unknown_site_fallback_and_long_title_extraction(self):
  original='blogspot.com';self.assertEqual(source_caption({'title':original,'url':'https://unknown.example'}),original)
  self.assertEqual(source_caption({'title':'已有的真实文章标题','url':'https://news.cn.evil.example/a'}),'已有的真实文章标题')
  title='国家统计局公布前三季度国民经济运行最新数据及详细分析'
  caption=source_caption({'title':title,'url':'https://www.stats.gov.cn/a'})
  self.assertTrue(caption.startswith('国家统计局：'));self.assertTrue(caption.endswith('…'));self.assertLessEqual(len(caption.split('：',1)[1]),19)
 def test_file_labels_and_expired_video_have_no_fake_links_or_internal_hints(self):
  l=Ledger();i=l.source('video','demo.mp4',identity='clip',expires=1,range={'start':0,'end':4});l.event('视频原生分析','success',[i])
  self.assertEqual(l.render_refs('['+i+']'),'[1]');self.assertIn('- [1] demo.mp4',l.footer());self.assertNotIn('https:',l.footer());self.assertNotIn('过期',l.footer())
 def test_old_state_without_numbers_and_streamed_reference(self):
  l=Ledger();i=l.source('web','A','https://example.com/a');l.event('网页读取','success',[i]);saved=l.save();saved.pop('display_numbers');saved.pop('next_display_number')
  resumed=Ledger(saved,True);stream=ReferenceStream(resumed);text='依据 ['+i+'](https://wrong.example) 中文🙂'
  got=''.join(stream.feed(c) for c in text)+stream.finish()
  self.assertEqual(got,'依据 [1](<https://example.com/a>) 中文🙂');self.assertIn('- [1]',resumed.footer())
 def test_followup_domain_only_metadata_does_not_erase_acquired_title(self):
  l=Ledger();i=l.source('search','官方公布的数据','https://www.news.cn/a');l.event('Google 搜索','success',[i])
  follow=Ledger(l.save());follow.native([],{'groundingChunks':[{'web':{'uri':'https://www.news.cn/a','title':'news.cn'}}]}, {},'')
  self.assertIn('新华网：官方公布的数据',follow.footer());self.assertEqual(follow.data['records'][i]['title'],'官方公布的数据')

 def test_known_publishers_survive_domain_only_google_redirect_metadata(self):
  for host,name in [('sohu.com','搜狐'),('sina.com.cn','新浪'),('wikipedia.org','维基百科'),('36kr.com','36氪'),('businessinsider.com','Business Insider')]:
   with self.subTest(host=host):
    record={'kind':'search','title':host,'url':'https://vertexaisearch.cloud.google.com/grounding-api-redirect/opaque'}
    self.assertEqual(source_caption(record),name)
    self.assertEqual(record['title'],host) # original evidence is preserved
    record['snippet']='官方公布的数据';self.assertEqual(source_caption(record),name+'：官方公布的数据')
 def test_unknown_publishers_and_fake_redirects_are_not_invented(self):
  unknown={'kind':'search','title':'unknown.example','url':'https://vertexaisearch.cloud.google.com/grounding-api-redirect/opaque'}
  self.assertEqual(source_caption(unknown),'unknown.example')
  fake={'kind':'search','title':'sohu.com','url':'https://vertexaisearch.cloud.google.com.evil.example/grounding-api-redirect/opaque'}
  self.assertEqual(source_caption(fake),'sohu.com')
