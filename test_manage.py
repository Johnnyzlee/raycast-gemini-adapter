import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
import manage
from adapter import configured_key,AdapterError
from configuration import load_settings

class ManageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.settings=load_settings(manage.ROOT/'settings.example.json');self.settings.update(providers_file=str(self.root/'providers.yaml'),state_dir=str(self.root/'state'),service_label='local.gemini.test',launchagents_dir=str(self.root/'agents'),port=28767)
  self.settings_path=self.root/'settings.json';self.settings_path.write_text(json.dumps(self.settings))
  self.provider=self.root/'providers.yaml';self.text=(manage.ROOT/'examples/providers.with-deepseek.example.yaml').read_text().replace('YOUR_GOOGLE_API_KEY','local-test-key')
  self.provider.write_text(self.text);self.addCleanup(manage.configure);manage.configure(self.settings_path)
 def test_configuration_and_placeholder(self):
  self.assertEqual(configured_key(self.settings),'local-test-key')
  self.provider.write_text(self.text.replace('local-test-key','YOUR_GOOGLE_API_KEY'))
  with self.assertRaises(AdapterError):configured_key(self.settings)
  self.settings_path.write_text(json.dumps(dict(self.settings,port=80)))
  with self.assertRaises(ValueError):load_settings(self.settings_path)
 def test_dry_run_no_mutations(self):
  before=set(self.root.rglob('*'))
  with patch.object(manage,'launch') as launch:manage.install(True);launch.assert_not_called()
  self.assertEqual(set(self.root.rglob('*')),before);self.assertEqual(self.provider.read_text(),self.text)
 def test_install_rollback_retains_later_other_provider_edits(self):
  with patch.object(manage,'launch'),patch.object(manage,'health',return_value=True):manage.install()
  current=yaml.safe_load(self.provider.read_text());self.assertEqual(current['providers'][0]['base_url'],manage.BASE)
  changed=self.provider.read_text().replace('name: DeepSeek\n','name: Renamed DeepSeek\n');self.provider.write_text(changed)
  with patch.object(manage,'launch'):manage.rollback()
  self.assertEqual(self.provider.read_text(),self.text.replace('name: DeepSeek\n','name: Renamed DeepSeek\n'))
  self.assertFalse(manage.PLIST.exists());self.assertFalse(manage.INSTALL.exists())
 def test_failed_start_and_concurrent_edit_leave_providers_intact(self):
  with patch.object(manage,'launch'),patch.object(manage,'health',return_value=False),patch.object(manage.time,'sleep'):
   with self.assertRaises(ValueError):manage.install()
  self.assertEqual(self.provider.read_text(),self.text);self.assertFalse(manage.PLIST.exists())
  def health():self.provider.write_text(self.text+'# concurrent edit\n');return True
  with patch.object(manage,'launch'),patch.object(manage,'health',side_effect=health):
   with self.assertRaises(ValueError):manage.install()
  self.assertTrue(self.provider.read_text().endswith('# concurrent edit\n'));self.assertFalse(manage.PLIST.exists())
 def test_existing_service_and_foreign_checkout_not_overwritten(self):
  import plistlib
  manage.PLIST.parent.mkdir();manage.PLIST.write_bytes(plistlib.dumps({'ProgramArguments':['python','/other/adapter.py']}))
  with self.assertRaises(ValueError):manage.install()
  with self.assertRaises(ValueError):manage.owned_service()
 def test_rollback_refuses_changed_target_endpoint(self):
  with patch.object(manage,'launch'),patch.object(manage,'health',return_value=True):manage.install()
  text=self.provider.read_text().replace(manage.BASE,'https://other.example');self.provider.write_text(text)
  with self.assertRaises(ValueError):manage.rollback()
  self.assertEqual(self.provider.read_text(),text);self.assertTrue(manage.PLIST.exists())

 def test_clear_history_removes_recovery_without_changing_provider(self):
  from adapter import State
  state=State(Path(self.settings['state_dir']))
  state.remember_checkpoint('request','scope',{'expires':9999999999,'history':[]})
  state.db.close()
  with patch('sys.argv',['manage.py','clear-history','--settings',str(self.settings_path)]):manage.main()
  state=State(Path(self.settings['state_dir']))
  try:self.assertEqual(state.db.execute('SELECT COUNT(*) FROM recovery_checkpoints').fetchone()[0],0)
  finally:state.db.close()
  self.assertEqual(self.provider.read_text(),self.text)
