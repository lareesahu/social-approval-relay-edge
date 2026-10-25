#!/usr/bin/env python3
"""Cloud relay for the local social-approval server.

The laptop has no inbound port, so the public side lives here: a Render web service holds one
outbound WebSocket from a connector running next to the local server, and forwards every HTTP
request through it. The domain therefore points at the laptop's own files — approvals still land
in decisions.json on her disk, nothing is duplicated in the cloud.

Auth: every request needs the shared secret (?k=... or the sa_key cookie set from it). The
connector must present the same secret on /agent.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
import urllib.parse

from aiohttp import WSMsgType, web

SECRET = os.environ.get('RELAY_SECRET') or ''
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(os.path.dirname(HERE), 'media')      # committed with this service
MEDIA_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
               '.mp4': 'video/mp4', '.webm': 'video/webm'}
REQUEST_TIMEOUT = 45.0
PENDING: dict[str, asyncio.Future] = {}
AGENT: dict[str, object | None] = {'ws': None, 'since': None, 'count': 0}


def ok_secret(value: str | None) -> bool:
    return bool(SECRET) and bool(value) and secrets.compare_digest(str(value), SECRET)


def landing(request: web.Request) -> web.Response:
    return web.Response(
        text='relay online — waiting for the local connector\n' if AGENT['ws'] is None
        else 'relay online — connector attached\n',
        content_type='text/plain')


async def health(request: web.Request) -> web.Response:
    return web.json_response({'ok': True, 'connector': AGENT['ws'] is not None,
                              'since': AGENT['since'], 'forwarded': AGENT['count']})


async def agent(request: web.Request) -> web.WebSocketResponse:
    if not ok_secret(request.query.get('k')):
        return web.Response(status=401, text='unauthorized')
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=32 * 1024 * 1024)
    await ws.prepare(request)
    AGENT['ws'] = ws
    AGENT['since'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    print('[relay] connector attached', flush=True)
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            fut = PENDING.pop(str(data.get('id')), None)
            if fut and not fut.done():
                fut.set_result(data)
    finally:
        AGENT['ws'] = None
        print('[relay] connector detached', flush=True)
    return ws


async def proxy(request: web.Request) -> web.Response:
    key = request.query.get('k') or request.cookies.get('sa_key')
    if not ok_secret(key):
        return web.Response(status=401, text='unauthorized — open the link with ?k=<key>')
    ws = AGENT['ws']
    if ws is None:
        return web.Response(status=503, text='the laptop connector is not attached yet — retry in a moment')

    body = await request.read()
    rid = secrets.token_hex(8)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    PENDING[rid] = fut
    payload = {
        'id': rid,
        'method': request.method,
        'path': request.path_qs,
        'headers': {k: v for k, v in request.headers.items()
                    if k.lower() not in ('host', 'cookie', 'content-length')},
        'body': body.decode('utf-8', 'replace'),
    }
    try:
        await ws.send_str(json.dumps(payload))
        data = await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
    except (asyncio.TimeoutError, ConnectionResetError):
        PENDING.pop(rid, None)
        return web.Response(status=504, text='the laptop did not answer in time')
    finally:
        PENDING.pop(rid, None)

    AGENT['count'] = int(AGENT['count'] or 0) + 1
    headers = {k: v for k, v in (data.get('headers') or {}).items()
               if k.lower() not in ('content-length', 'transfer-encoding', 'connection')}
    body = str(data.get('body') or '')
    if data.get('encoding') == 'base64':
        raw = base64.b64decode(body) if body else b''
    else:
        raw = body.encode('utf-8')
        headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp = web.Response(status=int(data.get('status') or 200), body=raw, headers=headers)
    if key and request.query.get('k'):
        resp.set_cookie('sa_key', key, max_age=90 * 24 * 3600, httponly=True, samesite='Lax')
    return resp


async def media(request: web.Request) -> web.StreamResponse:
    """Serve the rendered post designs straight from this service.

    They never change once rendered, so they must not travel through the laptop connector: a
    1080x1350 JPEG per swipe would queue behind the WebSocket and time out. Static files keep the
    feed instant and take the laptop out of the path for images.
    """
    if not ok_secret(request.query.get('k') or request.cookies.get('sa_key')):
        return web.Response(status=401, text='missing key')
    name = os.path.basename(request.match_info.get('name', ''))
    path = os.path.join(MEDIA_DIR, name)
    ext = os.path.splitext(name)[1].lower()
    if not name or ext not in MEDIA_TYPES or not os.path.isfile(path):
        return web.Response(status=404, text='no such design')
    return web.FileResponse(path, headers={'Content-Type': MEDIA_TYPES[ext],
                                           'Cache-Control': 'public, max-age=604800, immutable',
                                           'X-Robots-Tag': 'noindex, nofollow'})


def boot() -> web.Application:
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_route('*', '/', proxy)
    app.router.add_get('/health', health)
    app.router.add_get('/media/{name}', media)
    app.router.add_get('/agent', agent)
    app.router.add_route('*', '/{tail:.*}', proxy)
    return app


def main() -> None:
    if not SECRET:
        raise SystemExit('RELAY_SECRET must be set')
    app = boot()
    web.run_app(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))


if __name__ == '__main__':
    main()
