"""Portable settings shared by the service, installer and manual test runner."""
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent


def load_settings(path=None):
    settings=json.loads((ROOT/'settings.example.json').read_text())
    local=Path(path).expanduser() if path else ROOT/'settings.json'
    if path or local.exists():settings.update(json.loads(local.read_text()))
    if type(settings['port']) is not int or not 1024<=settings['port']<=65535:
        raise ValueError('port must be an integer from 1024 to 65535')
    ZoneInfo(settings['timezone'])
    for field in ('provider_id','service_label'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',settings[field]):raise ValueError('Invalid '+field)
    if not isinstance(settings['allowed_roots'],list) or not settings['allowed_roots']:
        raise ValueError('allowed_roots must contain at least one directory')
    for root in settings['allowed_roots']:
        if not Path(root).expanduser().is_absolute():raise ValueError('allowed_roots requires absolute paths or ~/ paths')
    for field in ('state_dir','providers_file'):
        if not Path(settings[field]).expanduser().is_absolute():raise ValueError(field+' requires an absolute path or ~/ path')
    for field in ('video_max_bytes','video_max_duration','request_timeout_seconds'):
        if type(settings[field]) is not int or settings[field]<=0:raise ValueError(field+' must be a positive integer')
    return settings
