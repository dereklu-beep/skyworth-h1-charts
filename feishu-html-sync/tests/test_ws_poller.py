#!/usr/bin/env python3
"""ws_poller: webhook.site and edge queue items are deleted/acked only after the relay accepted them."""
import base64
import json
import sys
import unittest

from helpers import Box, pkg

import ws_poller as wp


class Resp:
    def __init__(self, code=200, body=None):
        self.status_code, self._b, self.text = code, body or {}, json.dumps(body or {})

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


class FakeRequests:
    def __init__(self, relay_code=200, queue=None, ws=None):
        self.relay_code, self.queue, self.ws, self.calls = relay_code, queue or [], ws or [], []

    def get(self, url, **kw):
        self.calls.append(('GET', url))
        return Resp(200, {'items': self.queue} if '/api/queue' in url else {'data': self.ws})

    def post(self, url, **kw):
        self.calls.append(('POST', url, kw.get('json')))
        if url.endswith('/sync'):
            if self.relay_code is None:
                raise ConnectionError('relay down')
            return Resp(self.relay_code, {'ok': True})
        return Resp(200, {'ok': True})

    def delete(self, url, **kw):
        self.calls.append(('DELETE', url))
        return Resp(200)


class Poller(unittest.TestCase):
    def setUp(self):
        self.box = Box(edge_url='https://e.example', edge_admin_token='T')

    def tearDown(self):
        self.box.close()
        sys.modules.pop('requests', None)

    def use(self, fake):
        wp._requests = lambda: fake
        return fake

    def test_ws_text_and_created_at(self):
        p = pkg([{'op': 'edit', 'old': 'a', 'new': 'b'}], rep='huaxida-h1')
        self.assertEqual(wp.ws_text({'content': json.dumps({'msg_type': 'text', 'content': {'text': p}})}), p)
        self.assertEqual(wp.ws_text({'content': p}), p)
        self.assertEqual(wp.ws_text({'content_base64': base64.b64encode(p.encode()).decode()}), p)
        self.assertEqual(wp.ws_recv_ts({'created_at': '2026-10-14 09:00:01'}), '2026-10-14T09:00:01.000Z')

    def test_webhook_site_deleted_only_after_relay_accepts(self):
        ws = [{'uuid': 'u1', 'content': pkg([{'op': 'edit', 'old': 'a', 'new': 'b'}], rep='huaxida-h1'), 'created_at': '2026-10-14 09:00:01'}]
        f = self.use(FakeRequests(relay_code=None, ws=ws))
        seen = wp.Seen(self.box.j('relay', 'seen.json'))
        wp.poll_webhook_site(seen, 'TOK')
        self.assertFalse(any(c[0] == 'DELETE' for c in f.calls))
        self.assertNotIn('u1', seen)
        f.relay_code = 200
        wp.poll_webhook_site(seen, 'TOK')
        self.assertIn(('DELETE', 'https://webhook.site/token/TOK/request/u1'), f.calls)
        fwd = [c for c in f.calls if c[0] == 'POST'][-1][2]
        self.assertEqual((fwd['recv_ts'], fwd['source']), ('2026-10-14T09:00:01.000Z', 'webhook.site'))

    def test_edge_ack_only_accepted(self):
        q = [{'key': 'q:1', 'text': pkg([{'op': 'edit'}], rep='x'), 'recv_ts': 't1'},
             {'key': 'q:2', 'text': pkg([{'op': 'edit'}], rep='x'), 'recv_ts': 't2'}]
        f = self.use(FakeRequests(relay_code=200, queue=q))
        wp.poll_edge('https://e.example', 'T')
        ack = [c for c in f.calls if c[0] == 'POST' and c[1].endswith('/api/ack')]
        self.assertEqual(ack[0][2], {'keys': ['q:1', 'q:2']})
        f2 = self.use(FakeRequests(relay_code=None, queue=q))
        wp.poll_edge('https://e.example', 'T')
        self.assertFalse(any(c[1].endswith('/api/ack') for c in f2.calls if c[0] == 'POST'))


if __name__ == '__main__':
    unittest.main()
