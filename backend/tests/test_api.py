from fastapi.testclient import TestClient
from backend.main import app


def test_controls_and_websocket(tmp_path,monkeypatch):
    monkeypatch.setenv('ALGOLENS_DB',str(tmp_path/'api.db'))
    monkeypatch.setenv('ALGOLENS_MODE','demo')
    with TestClient(app) as client:
        assert client.get('/api/health').status_code==200
        assert client.post('/api/strategy/start').status_code==409
        response=client.put('/api/risk/config',json={'confirmed':True})
        assert response.status_code==200
        assert client.post('/api/strategy/start').json()['status']=='RUNNING'
        assert client.post('/api/strategy/start').json()['status']=='RUNNING'
        assert client.put('/api/strategy/config',json={}).status_code==409
        assert client.post('/api/strategy/stop').json()['status']=='STOPPED'
        assert client.put('/api/strategy/config',json={'fast_period':100,'slow_period':20}).status_code==422
        assert client.get('/api/orders/missing').status_code==404
        assert client.get('/api/orders?page=0').status_code==422
        assert client.post('/api/strategy/start',headers={'origin':'https://evil.example'}).status_code==403
        with client.websocket_connect('/ws/trading',headers={'origin':'http://localhost:3000'}) as ws:
            assert ws.receive_json()['type']=='snapshot_required'
        snapshot=client.get('/api/snapshot').json()
        assert snapshot['mode']=='demo'
        assert snapshot['account']['equity']>0
