import asyncio
import hashlib
import hmac
import httpx
from backend.delta_client import DeltaClient


def test_signed_body_matches_exact_transmitted_bytes(monkeypatch):
    monkeypatch.setenv('DELTA_TESTNET_URL','https://cdn-ind.testnet.deltaex.org')
    monkeypatch.setenv('DELTA_API_KEY','test-key')
    monkeypatch.setenv('DELTA_API_SECRET','test-secret')
    original=httpx.AsyncClient
    captured=[]
    def handler(request):
        captured.append(request)
        message=request.method+request.headers['timestamp']+request.url.path+request.content.decode()
        expected=hmac.new(b'test-secret',message.encode(),hashlib.sha256).hexdigest()
        assert request.headers['signature']==expected
        assert request.headers['content-type']=='application/json'
        return httpx.Response(200,json={'success':True,'result':{'id':1}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    result=asyncio.run(DeltaClient().create_order({'product_id':84,'size':1,'reduce_only':True}))
    assert result['id']==1 and len(captured)==1
    assert captured[0].content==b'{"product_id":84,"size":1,"reduce_only":true}'
