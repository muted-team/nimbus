"""User avatar contract and safe URL resolution; synthetic responses only."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules import remote

class OwnerAvatarTests(unittest.TestCase):
    def test_account_preserves_avatar_from_existing_server(self):
        with patch.object(remote,'_get',return_value={'name':'fixture','avatar_url':'/avatar/42'}):
            self.assertTrue(remote.account('synthetic-key')['avatar_url'].startswith('api/license/avatar?v='))
    def test_avatar_resolver_accepts_https_and_rejects_other_urls(self):
        self.assertEqual(remote._owner_avatar_url('https://cdn.example/avatar.png'),'https://cdn.example/avatar.png')
        for value in ('//foreign.example/avatar','javascript:alert(1)','data:image/svg+xml,bad','/not-an-avatar',None):
            self.assertIsNone(remote._owner_avatar_url(value))

    def test_avatar_download_uses_proxy_without_sending_license_key(self):
        import types
        response=types.SimpleNamespace(status_code=200,content=b'fixture-image',headers={'Content-Type':'image/jpeg'})
        with (patch.object(remote,'_get',return_value={'avatar_url':'/avatar/42'}),
              patch.object(remote,'key',return_value='synthetic-key'),
              patch.object(remote,'_routes',return_value=['socks5h://fixture.invalid:9696']),
              patch.object(remote.requests,'get',return_value=response)as request):
            data,ctype=remote.owner_avatar()
        self.assertEqual((data,ctype),(b'fixture-image','image/jpeg'))
        self.assertEqual(request.call_args.kwargs['proxy'],'socks5h://fixture.invalid:9696')
        self.assertNotIn('headers',request.call_args.kwargs)

if __name__=='__main__':unittest.main()
