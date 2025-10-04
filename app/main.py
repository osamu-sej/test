from fastapi import FastAPI, HTTPException

from .models import TodoCreate, TodoResponse, ToggleResponse

app = FastAPI(title="FastAPI TODO")


todos: list[TodoResponse] = []
_next_id = 1


def _get_next_id() -> int:
    global _next_id
    current = _next_id
    _next_id += 1
    return current


def _find_todo(todo_id: int) -> TodoResponse:
    for todo in todos:
        if todo.id == todo_id:
            return todo
    raise HTTPException(status_code=404, detail="Todo not found")


@app.get("/todos", response_model=list[TodoResponse])
def list_todos() -> list[TodoResponse]:
    return todos


@app.post("/todos", response_model=TodoResponse, status_code=201)
def create_todo(payload: TodoCreate) -> TodoResponse:
    todo = TodoResponse(id=_get_next_id(), title=payload.title, completed=False)
    todos.append(todo)
    return todo


@app.patch("/todos/{todo_id}/toggle", response_model=ToggleResponse)
def toggle_todo(todo_id: int) -> ToggleResponse:
    todo = _find_todo(todo_id)
    todo.completed = not todo.completed
    return ToggleResponse(id=todo.id, completed=todo.completed)


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> None:
    todo = _find_todo(todo_id)
    todos.remove(todo)
