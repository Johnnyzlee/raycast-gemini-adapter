import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from adapter import Adapter, AdapterError, FileTools, State, convert_messages, parts_from_bytes, source_links, merge_user_contents, stream_error
from manage import edit_endpoint, ORIGINAL_BASE


def response(parts, grounding=None):
    return {'candidates': [{'content': {'role': 'model', 'parts': parts}, 'finishReason': 'STOP',
                            'groundingMetadata': grounding or {}}],
            'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 2, 'totalTokenCount': 12}}


class FakeAPI:
    def __init__(self, responses):
        self.responses, self.requests = iter(responses), []

    def generate(self, model, body):
        self.requests.append(copy.deepcopy(body))
        yield next(self.responses)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = {'allowed_roots': [str(self.root)], 'timezone': 'Asia/Hong_Kong'}
        self.files = FileTools(self.settings)
        self.state = State(self.root / 'state')
        self.addCleanup(self.state.db.close)

    def adapter(self, replies):
        api = FakeAPI(replies)
        return Adapter(self.settings, self.state, lambda key: api), api

    def body(self, text='hello'):
        return {'model': 'gemini-4-neon', 'messages': [{'role': 'user', 'content': text}]}

    def test_file_boundaries_and_symlink(self):
        with self.assertRaises(AdapterError):
            self.files.read('relative.pdf')
        p = self.root / '.config'; p.mkdir(); (p / 'key.json').write_text('{}')
        with self.assertRaises(AdapterError):
            self.files.read(str(p / 'key.json'))
        (self.root / 'escape.pdf').symlink_to('/etc/hosts')
        with self.assertRaises(AdapterError):
            self.files.read(str(self.root / 'escape.pdf'))

    def test_native_pdf_and_office_bytes(self):
        for name in ('test.pdf', 'test.docx', 'test.pptx', 'test.xlsx'):
            part = parts_from_bytes(b'fixture', name)[0]
            self.assertEqual(base64.b64decode(part['inlineData']['data']), b'fixture')
            self.assertNotIn('text', part)

    def test_inline_images_and_files(self):
        encoded = base64.b64encode(b'pngbytes').decode()
        m = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + encoded}}]}]
        self.assertEqual(convert_messages(m, self.files)[0]['parts'][0]['inlineData']['mimeType'], 'image/png')
        m[0]['content'] = [{'type': 'file', 'file': {'filename': 'test.pdf', 'file_data': encoded}}]
        self.assertEqual(convert_messages(m, self.files)[0]['parts'][0]['inlineData']['mimeType'], 'application/pdf')

    def test_unknown_blocks_not_silently_dropped(self):
        with self.assertRaises(AdapterError):
            convert_messages([{'role': 'user', 'content': [{'type': 'unsupported'}]}], self.files)

    def test_remote_image_is_not_fetched(self):
        with self.assertRaises(AdapterError):
            convert_messages([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'http://127.0.0.1/private'}}]}], self.files)

    def test_native_history_survives_followup(self):
        signed = {'text': 'OK', 'thoughtSignature': 'actual-signature'}
        a, api = self.adapter([response([signed]), response([{'text': 'Again'}])])
        b = self.body(); out = list(a.run(b, 'fake'))
        b['messages'] += [{'role': 'assistant', 'content': 'OK'}, {'role': 'user', 'content': 'continue'}]
        list(a.run(b, 'fake'))
        self.assertEqual(api.requests[1]['contents'][1]['parts'], [signed])

    def test_external_tool_roundtrip_and_schema(self):
        fn = {'functionCall': {'name': 'finder', 'args': {'query': 'x'}, 'id': 'call_1'}, 'thoughtSignature': 'sig'}
        a, api = self.adapter([response([fn]), response([{'text': 'done'}])])
        b = self.body(); b['tools'] = [{'type': 'function', 'function': {'name': 'finder', 'parameters': {'type': 'object'}}}]
        out = list(a.run(b, 'fake'))
        call = next(c['delta']['tool_calls'] for c in out if c.get('delta', {}).get('tool_calls'))[0]
        call.pop('index')
        b['messages'] += [{'role': 'assistant', 'content': '', 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'path'}]
        list(a.run(b, 'fake'))
        self.assertEqual(api.requests[1]['contents'][1]['parts'], [fn])
        self.assertEqual(api.requests[1]['contents'][2]['parts'][0]['functionResponse']['id'], 'call_1')
        self.assertIn('parametersJsonSchema', api.requests[0]['tools'][-1]['functionDeclarations'][-1])

    def test_location_tool_only_content_variants(self):
        for variant in ('null', 'omitted', 'empty_blocks', 'stream_index'):
            with self.subTest(variant=variant):
                fn = {'functionCall': {'name': 'location-get-current-location', 'args': {}, 'id': 'call_' + variant}, 'thoughtSignature': 'native-signature'}
                a, api = self.adapter([response([fn]), response([{'text': 'Test City'}])])
                b = self.body('where am I ' + variant)
                b['tools'] = [{'type': 'function', 'function': {'name': 'location-get-current-location', 'parameters': {'type': 'object', 'properties': {}}}}]
                out = list(a.run(b, 'fake'))
                call = next(c['delta']['tool_calls'] for c in out if c.get('delta', {}).get('tool_calls'))[0]
                if variant != 'stream_index':
                    call.pop('index')
                msg = {'role': 'assistant', 'tool_calls': [call]}
                if variant == 'null':
                    msg['content'] = None
                elif variant == 'empty_blocks':
                    msg['content'] = []
                elif variant == 'stream_index':
                    msg['content'] = ''
                b['messages'] += [msg, {'role': 'tool', 'tool_call_id': fn['functionCall']['id'], 'content': '{"city":"Test City"}'}]
                result = list(a.run(b, 'fake'))
                self.assertEqual(api.requests[1]['contents'][1]['parts'], [fn])
                self.assertEqual(result[-1]['finish_reason'], 'stop')

    def test_local_file_is_native_in_followup(self):
        p = self.root / 'figure.pdf'; p.write_bytes(b'%PDF fixture')
        fn = {'functionCall': {'name': 'gemini_open_document', 'args': {'path': str(p)}, 'id': 'f1'}, 'thoughtSignature': 'sig'}
        a, api = self.adapter([response([fn]), response([{'text': 'read'}])])
        list(a.run(self.body('read file'), 'fake'))
        parts = api.requests[1]['contents'][-1]['parts']
        self.assertEqual(parts[-1]['inlineData']['mimeType'], 'application/pdf')
        self.assertNotIn({'codeExecution': {}}, api.requests[1]['tools'])

    def test_document_python_uses_separate_call(self):
        fn = {'functionCall': {'name': 'gemini_run_python', 'args': {'task': '17+25'}, 'id': 'p1'}}
        executed = response([{'executableCode': {'code': 'print(17+25)'}}, {'codeExecutionResult': {'outcome': 'OUTCOME_OK', 'output': '42'}}])
        a, api = self.adapter([response([fn]), executed, response([{'text': '42'}])])
        list(a.run(self.body(), 'fake'))
        self.assertEqual(api.requests[1]['tools'], [{'codeExecution': {}}])
        self.assertIn('executions', api.requests[2]['contents'][-1]['parts'][0]['functionResponse']['response'])

    def test_maps_is_separate_and_requires_evidence(self):
        fn = {'functionCall': {'name': 'gemini_google_maps', 'args': {'query': 'museum'}, 'id': 'm1'}}
        g = {'groundingChunks': [{'maps': {'title': 'Museum', 'uri': 'https://maps.google.com/example'}}]}
        maps = response([{'toolCall': {'toolType': 'GOOGLE_MAPS'}}, {'text': 'place'}], g)
        a, api = self.adapter([response([fn]), maps, response([{'text': 'done'}])])
        out = list(a.run(self.body(), 'fake'))
        self.assertEqual(api.requests[1]['tools'], [{'googleMaps': {}}])
        self.assertNotIn({'googleMaps': {}}, api.requests[0]['tools'])
        self.assertIn('Google Maps', ''.join(c.get('delta', {}).get('content', '') for c in out))

    def test_maps_without_evidence_is_error(self):
        fn = {'functionCall': {'name': 'gemini_google_maps', 'args': {'query': 'museum'}, 'id': 'm1'}}
        a, api = self.adapter([response([fn]), response([{'text': 'invented place'}]), response([{'text': 'failed'}])])
        list(a.run(self.body(), 'fake'))
        self.assertIn('error', api.requests[2]['contents'][-1]['parts'][0]['functionResponse']['response'])

    def test_carbon_effort_mapping(self):
        a, api = self.adapter([response([{'text': 'OK'}])]); b = self.body()
        b.update(model='gemini-4-carbon', reasoning_effort='xhigh')
        list(a.run(b, 'fake'))
        self.assertEqual(api.requests[0]['generationConfig']['thinkingConfig']['thinkingLevel'], 'high')

    def test_parallel_local_and_external_responses_merge(self):
        history = [{'role': 'model', 'parts': [{'functionCall': {'id': 'a'}}, {'functionCall': {'id': 'b'}}]},
                   {'role': 'user', 'parts': [{'functionResponse': {'id': 'a'}}]},
                   {'role': 'user', 'parts': [{'functionResponse': {'id': 'b'}}]}]
        merged = merge_user_contents(history)
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(merged[1]['parts']), 2)
        self.assertEqual(len(history[1]['parts']), 1)

    def test_endpoint_edit_preserves_other_providers(self):
        text = 'providers:\n  - id: gemini\n    base_url: ' + ORIGINAL_BASE + '\n    api_keys: {gemini: fake}\n  - id: deepseek\n    base_url: http://127.0.0.1:18766\n'
        updated = edit_endpoint(text, ORIGINAL_BASE, 'http://127.0.0.1:18767')
        self.assertEqual(updated.split('  - id: deepseek')[1], text.split('  - id: deepseek')[1])
        self.assertEqual(edit_endpoint(updated, 'http://127.0.0.1:18767', ORIGINAL_BASE), text)

    def test_stream_error_has_raycast_completion_envelope(self):
        error = {'message': '工具调用上下文已过期', 'type': 'adapter_error'}
        chunk = stream_error('test-id', 'gemini-4-neon', error)
        for field in ('id', 'object', 'created', 'model', 'choices'):
            self.assertIn(field, chunk)
        self.assertEqual(chunk['error'], error)
        self.assertIn('上下文已过期', chunk['choices'][0]['delta']['content'])


if __name__ == '__main__':
    unittest.main()
