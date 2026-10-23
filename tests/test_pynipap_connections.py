"""Verify that client requests release real HTTP keep-alive connections."""
from queue import Empty, Queue
from threading import Thread
import unittest
from unittest.mock import patch
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import pynipap
from pynipap import pynipap as client


class KeepAliveHandler(SimpleXMLRPCRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        if self.server.reject_requests:
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(503)
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            super().do_POST()

    def finish(self):
        try:
            super().finish()
        finally:
            self.server.closed_connections.put(True)


class ConnectionCleanupTest(unittest.TestCase):
    def setUp(self):
        self.server = SimpleXMLRPCServer(
            ('127.0.0.1', 0), requestHandler=KeepAliveHandler,
            logRequests=False, allow_none=True)
        self.server.closed_connections = Queue()
        self.server.reject_requests = False
        self.server.register_function(lambda auth: 'test-version', 'version')
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        uri = f'http://127.0.0.1:{self.server.server_address[1]}'
        uri_patch = patch.object(pynipap, 'xmlrpc_uri', uri)
        uri_patch.start()
        self.addCleanup(uri_patch.stop)
        auth_patch = patch.object(client.AuthOptions, '_AuthOptions__shared_state', {})
        auth_patch.start()
        self.addCleanup(auth_patch.stop)
        client.AuthOptions({'authoritative_source': 'connection-test'})

        # Retain the wrappers: cleanup must happen before garbage collection.
        self.connections = []
        connection_class = client.XMLRPCConnection

        def connection():
            wrapper = connection_class()
            self.connections.append(wrapper)
            self.addCleanup(wrapper.connection.__exit__, None, None, None)
            return wrapper

        factory_patch = patch.object(client, 'XMLRPCConnection', side_effect=connection)
        factory_patch.start()
        self.addCleanup(factory_patch.stop)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def assert_connection_closed(self):
        try:
            self.server.closed_connections.get(timeout=2)
        except Empty:
            self.fail('The server is still waiting on an unclosed client connection')

    def test_success_closes_each_connection_before_next_request(self):
        for _ in range(5):
            self.assertEqual(client.nipapd_version(), 'test-version')
            self.assert_connection_closed()

    def test_fault_closes_connection_and_preserves_exception_mapping(self):
        def fail(auth):
            raise xmlrpc.client.Fault(1200, 'invalid request')

        self.server.register_function(fail, 'version')
        with self.assertRaisesRegex(client.NipapValueError, 'invalid request'):
            client.nipapd_version()
        self.assert_connection_closed()

    def test_http_error_closes_connection_and_preserves_error(self):
        self.server.reject_requests = True
        with self.assertRaises(xmlrpc.client.ProtocolError) as raised:
            client.nipapd_version()
        self.assertEqual(raised.exception.errcode, 503)
        self.assert_connection_closed()


if __name__ == '__main__':
    unittest.main()
