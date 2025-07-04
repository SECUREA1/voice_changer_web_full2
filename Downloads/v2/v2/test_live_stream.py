import os
import sys
import types
import base64

# stub heavy modules
sys.modules['rpc_health'] = types.SimpleNamespace(check_all=lambda: {})
sys.modules['blockchain'] = types.SimpleNamespace(
    mint_nft=lambda *a, **kw: None,
    process_payment=lambda *a, **kw: None,
    payment_breakdown=lambda *a, **kw: {},
)

os.environ['APP_DB_PATH'] = '/tmp/test_audio.db'

import db

db.init_db()

import main
from flask_socketio import SocketIOTestClient

app = main.app
socketio = main.socketio

with app.test_client() as client:
    client.post('/signup', data={'username':'host','password':'pw','wallet':'0xhost'})
    client.post('/signup', data={'username':'listener','password':'pw','wallet':'0xlist'})

    client.post('/login', data={'username':'host','password':'pw','wallet':'0xhost'})
    host = socketio.test_client(app, flask_test_client=client)
    host.emit('start_live')
    host.get_received()

    client.post('/login', data={'username':'listener','password':'pw','wallet':'0xlist'})
    listener = socketio.test_client(app, flask_test_client=client)
    listener.emit('tune_in', {'host':'host'})
    listener.get_received()

    b64 = base64.b64encode(b'1234').decode()
    host.emit('voice_chunk', {'host':'host','chunk': b64, 'mime':'audio/webm'})
    events = listener.get_received()

    assert any(e['name']=='voice_chunk' for e in events), 'listener did not receive audio'

    host.emit('stop_live')
    host.disconnect()
    listener.disconnect()

print('test passed')
