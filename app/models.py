from pydantic import BaseModel


class TodoBase(BaseModel):
    title: str
    completed: bool = False


class TodoCreate(BaseModel):
    title: str


class TodoResponse(TodoBase):
    id: int


class ToggleResponse(BaseModel):
    id: int
    completed: bool
