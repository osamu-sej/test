from fastapi.testclient import TestClient

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app


client = TestClient(app)


def test_todo_lifecycle():
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []

    response = client.post("/todos", json={"title": "Write docs"})
    assert response.status_code == 201
    todo = response.json()
    assert todo["title"] == "Write docs"
    assert todo["completed"] is False
    todo_id = todo["id"]

    response = client.patch(f"/todos/{todo_id}/toggle")
    assert response.status_code == 200
    assert response.json() == {"id": todo_id, "completed": True}

    response = client.get("/todos")
    assert response.status_code == 200
    todos = response.json()
    assert len(todos) == 1
    assert todos[0]["completed"] is True

    response = client.delete(f"/todos/{todo_id}")
    assert response.status_code == 204

    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []
