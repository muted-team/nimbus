"""Synthetic cookie import and optional-2FA regressions; no external network."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import accounts, client_session, cloud, paths, signin

COOKIES = json.dumps([
    {'name': 'sid_guard', 'value': 'synthetic-auth', 'domain': '.tiktok.com',
     'path': '/', 'expirationDate': 2147483647, 'secure': True},
    {'name': 'msToken', 'value': 'synthetic-one', 'domain': '.tiktok.com', 'path': '/'},
    {'name': 'msToken', 'value': 'synthetic-two', 'domain': 'tiktok.com', 'path': '/'}])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(paths.use_root(self.root))

    def test_password_only_preserves_password_that_looks_like_totp(self):
        self.assertEqual(accounts._parse_account_line('@user:ABCD2345EFGH2345'),
                         {'username': 'user', 'password': 'ABCD2345EFGH2345'})
        self.assertEqual(accounts.add_accounts_bulk('user:pass')['added'], ['user'])
        accounts.add_account({'username': 'single', 'password': 'pass'})
        with patch('modules.avatars.versions', return_value={}), patch('modules.profiles.summaries', return_value={}):
            accounts.update_account('single', {'totp_secret': ''})

    def test_cookie_normalization_keeps_domains_and_expiry(self):
        data = json.loads(client_session.normalize_cookie_import(COOKIES))
        self.assertEqual(data['schema'], client_session.COOKIE_SCHEMA)
        self.assertEqual(len(data['cookies']), 3)
        self.assertEqual(data['cookies'][0]['expires'], 2147483647)
        self.assertEqual([c['domain'] for c in data['cookies'][1:]], ['.tiktok.com', 'tiktok.com'])

    def test_cookie_validation_rejects_foreign_empty_expired_and_header_injection(self):
        cases = [[], [{'name': 'sid_guard', 'value': 'x', 'domain': 'tiktok.com.evil'}],
                 [{'name': 'sid_guard', 'value': 'x', 'domain': '.tiktok.com', 'expirationDate': 1}],
                 [{'name': 'sid_guard', 'value': 'x\r\nOther: y', 'domain': '.tiktok.com'}]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                client_session.normalize_cookie_import(json.dumps(rows))

    def test_verified_import_has_no_password_or_cookie_in_account_response(self):
        verified = {'username': 'real.user', 'state': 'synthetic-token'}
        with patch.object(cloud, 'import_cookies', return_value=verified):
            out = accounts.add_accounts_bulk(COOKIES)
        self.assertEqual(out, {'added': ['real.user'], 'errors': []})
        self.assertEqual(accounts.load_account('real.user'), {'username': 'real.user'})
        self.assertEqual(client_session.state_file('real.user').read_text(), 'synthetic-token')
        self.assertNotIn('synthetic-auth', json.dumps(out))

    def test_failed_cookie_import_keeps_existing_files(self):
        account_path = self.root / 'accounts.json'
        account_path.write_text('{"accounts": [{"username":"real.user","password":"old"}]}')
        before = account_path.read_bytes()
        with patch.object(cloud, 'import_cookies', side_effect=ValueError('Сессия не подтверждена')):
            with self.assertRaises(ValueError):
                accounts.add_accounts_bulk(COOKIES)
        self.assertEqual(account_path.read_bytes(), before)

    def test_cookie_only_login_checks_session_without_password_post(self):
        (self.root / 'accounts.json').write_text('{"accounts":[{"username":"real.user"}]}')
        with (patch.object(cloud, 'session_check', return_value={'alive': True, 'username': 'real.user'}),
                patch.object(cloud, 'login', side_effect=AssertionError('must not send password')),
                patch.object(client_session, 'sticky_proxy', return_value='http://synthetic.invalid')):
            self.assertTrue(signin.attempt_via_server({'username': 'real.user'}, 'http://synthetic.invalid', 'real.user'))

    def test_cloud_import_rebinds_token_to_verified_owner_and_rejects_mismatch(self):
        from modules import proxy_pool
        class Held:
            url = 'http://synthetic.invalid'
            released = False
            def release(self): self.released = True
        held = Held()
        replies = [{'state': 'alias-token'},
                   {'data': {'alive': True, 'message': 'success', 'username': 'real.user', 'uid': '42'}, 'state': 'alias-new'},
                   {'state': 'owner-token'},
                   {'data': {'alive': True, 'message': 'success', 'username': 'real.user', 'uid': '42'}, 'state': 'owner-new'}]
        with patch.object(proxy_pool, 'lease', return_value=held), \
                patch.object(cloud.remote, 'request', side_effect=replies) as request:
            out = cloud.import_cookies(COOKIES)
        self.assertEqual((out['username'], out['state']), ('real.user', 'owner-new'))
        self.assertTrue(held.released)
        self.assertEqual(request.call_args_list[2].kwargs['json']['username'], 'real.user')
        self.assertFalse(client_session.state_file('real.user').exists())
        replies[-1]['data']['uid'] = '43'
        with patch.object(proxy_pool, 'lease', return_value=held), \
                patch.object(cloud.remote, 'request', side_effect=replies), self.assertRaises(ValueError):
            cloud.import_cookies(COOKIES)

    def test_cookie_import_preserves_credentials_and_rejects_late_state_save(self):
        account_path = self.root / 'accounts.json'
        account_path.write_text('{"accounts":[{"username":"real.user","password":"old","totp_secret":"old-code"}]}')
        path = client_session.state_file('real.user')
        path.write_text('previous-token')
        verified = {'username': 'real.user', 'state': 'new-token', 'generation': client_session.state_generation(path), 'previous_state': path.read_bytes()}
        with patch.object(cloud, 'import_cookies', return_value=verified):
            result = accounts.add_accounts_bulk(COOKIES)
        self.assertEqual(accounts.load_account('real.user')['password'], 'old')
        self.assertEqual(accounts.load_account('real.user')['totp_secret'], 'old-code')
        self.assertEqual(result['updated'][0]['replaced'], ['session'])
        with patch.object(cloud, 'import_cookies', return_value=verified), self.assertRaises(ValueError):
            accounts.add_accounts_bulk(COOKIES)
        self.assertEqual(path.read_text(), 'new-token')

    def test_failed_registry_write_rolls_back_cookie_state(self):
        verified = {'username': 'real.user', 'state': 'synthetic-token'}
        with patch.object(cloud, 'import_cookies', return_value=verified), \
                patch.object(accounts, '_write_json', side_effect=OSError('fixture disk failure')), self.assertRaises(OSError):
            accounts.add_accounts_bulk(COOKIES)
        self.assertFalse(client_session.state_file('real.user').exists())

    def test_clear_during_owner_discovery_does_not_restore_session(self):
        from modules import proxy_pool
        held = type('Held', (), {'url': 'http://synthetic.invalid', 'release': lambda self: None})()
        responses = iter([{'state': 'alias-token'},
                          {'data': {'alive': True, 'message': 'success', 'username': 'real.user', 'uid': '42'}, 'state': 'a'},
                          {'state': 'owner-token'},
                          {'data': {'alive': True, 'message': 'success', 'username': 'real.user', 'uid': '42'}, 'state': 'b'}])
        def respond(*args, **kwargs):
            result = next(responses)
            if args[1] == '/v1/session/check' and kwargs['json']['username'] != 'real.user':
                client_session.clear_session('real.user')
            return result
        with patch.object(proxy_pool, 'lease', return_value=held), patch.object(cloud.remote, 'request', side_effect=respond), self.assertRaises(ValueError):
            accounts.add_accounts_bulk(COOKIES)
        self.assertFalse(client_session.state_file('real.user').exists())
        self.assertFalse((self.root / 'accounts.json').exists())

    def test_saved_sticky_route_matches_the_route_used_for_verification(self):
        from modules import proxy_pool
        held = type('Held', (), {'url': 'socks5://fixture-country-US:fixture@proxy.noshadow.pro:9696', 'release': lambda self: None})()
        checks = []
        def respond(method, path, **kwargs):
            if path == '/v1/accounts/import': return {'state': 'fixture-import'}
            checks.append(kwargs['json']['proxy'])
            return {'data': {'alive': True, 'message': 'success', 'username': 'real.user', 'uid': '42'}, 'state': 'fixture-verified'}
        with patch.object(proxy_pool, 'lease', return_value=held), patch.object(cloud.remote, 'request', side_effect=respond):
            accounts.add_accounts_bulk(COOKIES)
        self.assertEqual(checks[0], checks[1])
        self.assertEqual(client_session.sticky_proxy(held.url, 'real.user'), checks[0])


if __name__ == '__main__':
    unittest.main()
