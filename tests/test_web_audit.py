"""Audit authorization, rendering and query tests; no database required."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from nipapwww import audit, auth


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask('audit-test', template_folder=str(
            Path(audit.__file__).parent / 'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='test-only',
                               AUDIT_ADMINS='admin@local', AUDIT_DB_DSN='test')
        self.app.register_blueprint(audit.bp)
        self.app.register_blueprint(auth.bp)
        self.app.add_url_rule('/ng/prefix', endpoint='ng.prefix', view_func=lambda: '')
        self.app.add_url_rule('/ng/vrf', endpoint='ng.vrf', view_func=lambda: '')
        self.app.add_url_rule('/prefix', endpoint='prefix.list', view_func=lambda: '')
        self.app.add_url_rule('/version', endpoint='version.show_version', view_func=lambda: '')
        self.client = self.app.test_client()

    def login_session(self, identity, user='admin', readonly=False):
        with self.client.session_transaction() as session:
            session['user'] = user
            session['authenticated_identity'] = identity
            session['readonly'] = readonly

    def test_anonymous_and_unlisted_accounts_cannot_query(self):
        with patch.object(audit, 'read_entries') as read:
            for identity in (None, 'operator@local', 'admin@ldap'):
                self.login_session(identity)
                for endpoint in ('/audit/', '/audit/entries'):
                    response = self.client.get(endpoint)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertIn(b'Please contact your NIPAP administrator to request access.', response.data)
                    if endpoint == '/audit/entries':
                        self.assertIn('error', response.get_json())
            read.assert_not_called()

    def test_readonly_does_not_grant_access(self):
        self.login_session('reader@local', user='reader', readonly=True)
        self.assertEqual(self.client.get('/audit/entries').status_code, 403)

    def test_allowlist_is_disabled_by_default_and_revoked_per_request(self):
        self.login_session('admin@local')
        self.app.config.pop('AUDIT_ADMINS')
        self.assertEqual(self.client.get('/audit/entries').status_code, 403)

    def test_login_stores_verified_identity_not_delegated_name(self):
        account = SimpleNamespace(authenticate=lambda: True, username='admin',
                                  authenticated_as='service', auth_backend='local',
                                  full_name='Test', readonly=False)
        with patch.object(auth, 'AuthFactory') as factory:
            factory.return_value.get_auth.return_value = account
            self.assertEqual(self.client.post('/auth/login', data={
                'username': 'service', 'password': 'test'}).status_code, 302)
        self.assertEqual(self.client.get('/audit/entries').status_code, 403)

    def test_render_escapes_history_and_disables_angular_interpolation(self):
        self.login_session('admin@local')
        entry = dict(id=1, timestamp='2026-09-12T12:00:00+00:00',
                     username='<script>alert(1)</script>', full_name=None,
                     authenticated_as='admin', authoritative_source='test',
                     prefix_id=9, prefix='192.0.2.0/24', vrf_id=0,
                     vrf_name='default', vrf_rt=None, pool_id=None,
                     description='<img src=x onerror=alert(1)> {{7*7}}')
        with patch.object(audit, 'read_entries', return_value=([entry], 1, {'page_size': 50, 'total_entries': 101, 'total_pages': 3})):
            response = self.client.get('/audit/?username=admin')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('<script>alert(1)', html)
        self.assertIn('&lt;img', html)
        self.assertIn('ng-non-bindable', html)
        self.assertIn('{{7*7}}', html)
        self.assertIn('before=1', html)
        self.assertIn('/audit/prefix/9', html)

    def test_invalid_filters_are_400_without_connecting(self):
        self.login_session('admin@local')
        with patch.object(audit.psycopg2, 'connect') as connect:
            for query in ('prefix=invalid', 'vrf_id=-1', 'before=no',
                          'prefix_id=999999999999', 'from=2026-02-30',
                          'to=9999-12-31', 'from=2026-09-12&to=2026-09-11'):
                for endpoint in ('/audit/', '/audit/entries'):
                    self.assertEqual(self.client.get(endpoint + '?' + query).status_code, 400)
            connect.assert_not_called()

    def test_filters_are_parameterized_and_page_bounded(self):
        username = "x' OR TRUE --"
        query, params = audit.build_query(dict(username=username, prefix='192.0.2.1/24',
                                             vrf_id='0', before='51',
                                             **{'from': '2026-09-11', 'to': '2026-09-12'}))
        self.assertNotIn(username, query)
        self.assertEqual(params['username'], username)
        self.assertEqual(params['prefix'], '192.0.2.0/24')
        self.assertEqual(params['vrf_id'], 0)
        self.assertEqual(params['limit'], 51)
        self.assertEqual(params['to'].day, 13)

    def test_prefix_link_checks_access_and_handles_deleted_prefixes(self):
        with patch.object(audit.pynipap.Prefix, 'list') as lookup:
            self.assertEqual(self.client.get('/audit/prefix/9').status_code, 403)
            lookup.assert_not_called()
            self.login_session('admin@local')
            lookup.return_value = [object()]
            response = self.client.get('/audit/prefix/9')
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/ng/prefix#/prefix/edit/9'))
            lookup.assert_called_with({'id': 9})
            lookup.return_value = []
            response = self.client.get('/audit/prefix/9')
            self.assertEqual(response.status_code, 404)
            self.assertIn(b'Prefix no longer exists', response.data)
            self.assertIn(b'prefix_id=9', response.data)

    def test_vrf_link_checks_access_and_handles_deleted_vrfs(self):
        with patch.object(audit.pynipap.VRF, 'list') as lookup:
            self.assertEqual(self.client.get('/audit/vrf/0').status_code, 403)
            lookup.assert_not_called()
            self.login_session('admin@local')
            lookup.return_value = [object()]
            response = self.client.get('/audit/vrf/0')
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/ng/vrf#/vrf/edit/0'))
            lookup.return_value = []
            response = self.client.get('/audit/vrf/1')
            self.assertEqual(response.status_code, 404)
            self.assertIn(b'VRF no longer exists', response.data)
            self.assertIn(b'vrf_id=1', response.data)

    def test_multiple_vrf_ids_are_validated_and_parameterized(self):
        query, params = audit.build_query({'vrf_id': '0, 2, 5, 02', 'username': 'admin, markus'})
        self.assertEqual(params['vrf_ids'], [0, 2, 5])
        self.assertIn('vrf_id = ANY(%(vrf_ids)s) AND username = ANY(%(usernames)s)', query)
        query, params = audit.build_query({'vrf_id': '0, 0'})
        self.assertEqual(params['vrf_id'], 0)
        self.assertIn('vrf_id = %(vrf_id)s', query)
        for value in (', ,', '0, -1', '0, 2147483648', '0, 1.5', '0, 1 OR TRUE',
                      ','.join(str(i) for i in range(51)), '0' * 4097):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.build_query({'vrf_id': value})

    def test_multiple_users_are_exact_and_parameterized(self):
        query, params = audit.build_query({'username': " admin, markus, admin, x' OR TRUE --, user* "})
        self.assertIn('username = ANY(%(usernames)s)', query)
        self.assertEqual(params['usernames'], ['admin', 'markus', "x' OR TRUE --", 'user*'])
        self.assertNotIn("x' OR TRUE --", query)
        query, params = audit.build_query({'username': ' admin, admin '})
        self.assertIn('username = %(username)s', query)
        self.assertEqual(params['username'], 'admin')
        for value in (', ,', 'a' * 256, ','.join(str(i) for i in range(51)), 'a' * 4097):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.build_query({'username': value})

    def test_page_size_and_count_keep_filters_but_not_cursor(self):
        for size in audit.PAGE_SIZES:
            query, params = audit.build_query({'page_size': str(size)})
            self.assertEqual(params['limit'], size + 1)
        for size in ('0', '-1', '10000', 'all', '1.5'):
            with self.subTest(size=size), self.assertRaises(ValueError):
                audit.build_query({'page_size': size})
        query, params = audit.build_query({'username': 'admin, markus', 'vrf_id': '0,2',
                                         'before': '123', 'page_size': '100'}, count=True)
        self.assertIn('COUNT(*) AS total', query)
        self.assertIn('username = ANY(%(usernames)s)', query)
        self.assertIn('vrf_id = ANY(%(vrf_ids)s)', query)
        self.assertNotIn('before', query)
        self.assertNotIn('LIMIT', query)

    def test_query_is_readonly_paginated_and_connection_closed(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {'total': 101}
        cursor.fetchall.return_value = [dict(id=i, timestamp=datetime.now(timezone.utc))
                                        for i in range(101, 50, -1)]
        with self.app.app_context(), patch.object(audit.psycopg2, 'connect', return_value=connection):
            rows, before, totals = audit.read_entries({})
        self.assertEqual(len(rows), 50)
        self.assertEqual(before, 52)
        connection.set_session.assert_called_once_with(readonly=True, isolation_level='REPEATABLE READ')
        self.assertEqual(totals, {'page_size': 50, 'total_entries': 101, 'total_pages': 3})
        connection.close.assert_called_once()

    def test_database_failure_is_generic_and_closes_connection(self):
        self.login_session('admin@local')
        connection = MagicMock()
        connection.cursor.side_effect = audit.psycopg2.OperationalError('secret-password')
        with patch.object(audit.psycopg2, 'connect', return_value=connection):
            response = self.client.get('/audit/entries')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'secret-password', response.data)
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
