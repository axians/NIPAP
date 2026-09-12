"""Startup regression tests; no database or root privileges required."""
import types
import unittest
from unittest.mock import patch

from nipap import nipapd
from nipap.errors import NipapError


class PrivilegesTest(unittest.TestCase):
    def setUp(self):
        for target, result in (
            ('pwd.getpwnam', types.SimpleNamespace(pw_uid=123)),
            ('grp.getgrnam', types.SimpleNamespace(gr_gid=456)),
            ('os.geteuid', 123), ('os.getegid', 456),
        ):
            mock = patch(target, return_value=result)
            mock.start()
            self.addCleanup(mock.stop)

    def test_service_manager_identity_preserves_groups(self):
        with patch('os.setgroups') as groups, patch('os.setuid') as uid, \
                patch('os.setgid') as gid, patch('os.umask'):
            nipapd.drop_privileges('nipap', 'nipap')
        groups.assert_not_called()
        uid.assert_not_called()
        gid.assert_not_called()

    def test_wrong_user_or_group_is_rejected(self):
        for target in ('os.geteuid', 'os.getegid'):
            with self.subTest(target=target), patch(target, return_value=999), \
                    self.assertRaises(NipapError):
                nipapd.drop_privileges('nipap', 'nipap')

    def test_root_still_drops_privileges(self):
        with patch('os.geteuid', return_value=0), \
                patch('os.setgroups') as groups, patch('os.setuid') as uid, \
                patch('os.setgid') as gid, patch('os.umask'):
            nipapd.drop_privileges('nipap', 'nipap')
        groups.assert_called_once_with([])
        gid.assert_called_once_with(456)
        uid.assert_called_once_with(123)


class StartupTest(unittest.TestCase):
    def test_sigterm_exits_successfully(self):
        with patch.object(nipapd.signal, 'signal'), self.assertRaises(SystemExit) as exc:
            nipapd.handle_sigterm(15, None)
        self.assertEqual(exc.exception.code, 0)

    def test_unreadable_tls_key_fails_before_database_setup(self):
        config = nipapd.configparser.ConfigParser()
        config['nipapd'] = dict(port='', ssl_port='1338', user='',
                               ssl_cert_file='/cert.pem', ssl_key_file='/key.pem')
        with patch.object(nipapd, 'NipapConfig', return_value=config), \
                patch('sys.argv', ['nipapd']), \
                patch.object(nipapd.ssl, 'create_default_context') as context, \
                patch('nipap.backend.Nipap') as database, \
                self.assertLogs(level='ERROR') as logs, \
                self.assertRaises(SystemExit) as exc:
            context.return_value.load_cert_chain.side_effect = PermissionError('key denied')
            nipapd.run()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn('TLS initialization failed', logs.output[0])
        database.assert_not_called()


if __name__ == '__main__':
    unittest.main()
