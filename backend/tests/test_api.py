import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_intelligence_endpoint():
    response = client.get("/api/intelligence?symbol=XAUUSD&timeframe=5M")
    assert response.status_code == 200
    data = response.json()
    
    assert data["symbol"] == "XAUUSD"
    assert data["timeframe"] == "5M"
    assert "overall_bias" in data
    assert "directional_pressure" in data
    assert "fundamentals" in data
    assert "correlations" in data
    assert "data_status" in data
