from fastapi.testclient import TestClient
from api import app


client = TestClient(app)

def test_apihealth():
 response = client.get("/health")
 assert response.status_code == 200, "Status code not 200"
 assert response.json() == {"message": "API Healthy and Working"}