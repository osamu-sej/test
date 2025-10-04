# FastAPI TODO API

![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)

A minimal TODO API built with FastAPI 0.100+ and Python 3.11. The service keeps data in memory and is optimized for running instantly inside GitHub Codespaces.

## Getting started in Codespaces

1. Create a new Codespace for this repository. The included devcontainer will install dependencies automatically.
2. Run the development server:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. Codespaces forwards port **8000** automatically. If prompted, make the port public so you can access it from a browser.
4. Verify the API is working:

   ```bash
   curl -s https://<your-codespace-domain>.github.dev/todos
   ```

## Local development

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API specification

| Method | Path                 | Description                            |
| ------ | -------------------- | -------------------------------------- |
| GET    | `/todos`             | List all TODO items.                   |
| POST   | `/todos`             | Create a TODO (`{"title": str}`) with `completed=false`. |
| PATCH  | `/todos/{id}/toggle` | Toggle completion for a TODO item.     |
| DELETE | `/todos/{id}`        | Remove a TODO item.                    |

All data is stored in memory and resets when the process restarts.

## Example workflow

```bash
curl -s -X POST https://<your-codespace-domain>.github.dev/todos \
  -H "Content-Type: application/json" \
  -d '{"title": "Write docs"}'

curl -s https://<your-codespace-domain>.github.dev/todos | jq

curl -s -X PATCH https://<your-codespace-domain>.github.dev/todos/1/toggle | jq

curl -i -X DELETE https://<your-codespace-domain>.github.dev/todos/1
```

## Continuous integration

GitHub Actions runs `pytest` on every push and pull request via [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
