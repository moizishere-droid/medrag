"""Request-size and provider-failure boundaries; no paid service calls."""
import importlib
import httpx
import openai
import pytest
main=importlib.import_module("medrag.api.main")


def test_oversized_query_and_title_are_rejected_before_work(client,pipeline,sid):
    assert client.post("/chat",json={"session_id":sid,"message":"x"*4001}).status_code==422
    assert pipeline.calls==[]
    assert client.post("/sessions",json={"title":"x"*81}).status_code==422


@pytest.mark.parametrize("kind,status",[("timeout",504),("connection",503)])
def test_provider_failure_is_actionable_without_leaking_internals(client,pipeline,sid,monkeypatch,kind,status):
    request=httpx.Request("POST","https://provider.invalid/private-path")
    error=openai.APITimeoutError(request=request) if kind=="timeout" else openai.APIConnectionError(message="private upstream details",request=request)
    def broken(*args,**kwargs):raise error
    monkeypatch.setattr(main,"generate_answer_with_memory",broken)
    response=client.post("/chat",json={"session_id":sid,"message":"What is hypertension?"})
    assert response.status_code==status
    assert "Please try again" in response.json()["detail"]
    assert "private" not in response.text and "provider.invalid" not in response.text
