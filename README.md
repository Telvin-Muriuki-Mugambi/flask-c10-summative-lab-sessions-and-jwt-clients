# Notes API

A JWT-authenticated Flask API for user-owned notes. It supports account
registration and login, current-user lookup, note CRUD, and per-user pagination.
The `client-with-jwt` React application is configured to proxy API requests to
port `5555`.

## Requirements

- Python 3.8.13 or newer
- Pipenv

## Install and configure

```bash
pipenv install --dev
cp .env.example .env
```

Replace both example secret values in `.env` with independent, randomly
generated secrets before running the API. Do not commit `.env`.

## Database setup

Apply the checked-in initial migration to create the database:

```bash
pipenv run flask --app app db upgrade
```

For later model changes, create a migration and apply it:

```bash
pipenv run flask --app app db migrate -m "Describe schema change"
pipenv run flask --app app db upgrade
```

To add sample data, set `SEED_USERNAME` and `SEED_PASSWORD` in your environment
and run:

```bash
pipenv run python seed.py
```

The seed command creates the user and two notes if they do not already exist.
It does not include a built-in password.

## Run

```bash
pipenv run flask --app app run --host 0.0.0.0 --port 5555
```

The API uses `DATABASE_URL` when set and otherwise stores its SQLite database
in `instance/app.db`. Start the frontend separately from
`client-with-jwt` with `npm install && npm start`.

## Interactive CLI

With the API running, launch the terminal client in another shell:

```bash
pipenv run python cli.py
```

The CLI supports signing up or logging in, then listing, viewing, creating,
updating, and deleting the signed-in user's notes. It uses the existing JWT
API (not Flask cookie sessions), keeps the access token in memory only, and
prompts for passwords without echoing them. Logging out discards the local
token; access tokens otherwise expire after one hour. Set `API_URL` to use a
different API address; the default is `http://127.0.0.1:5555`.

## Authentication

Send JSON to the authentication endpoints. Successful registration and login
return an access token and the public user object:

```json
{
  "token": "<JWT>",
  "user": {
    "id": 1,
    "username": "alice"
  }
}
```

For protected routes, send the access token in the `Authorization` header
using the Bearer authentication scheme. Passwords are stored as bcrypt hashes.
Access tokens expire after one hour. Protected note queries always use the
authenticated user's ID; another user's note is reported as not found.

## Endpoints

All API responses use JSON. Error responses use an `errors` array.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/signup` | No | Register with `username`, `password`, and `password_confirmation`; returns `201` with token and user. |
| `POST` | `/login` | No | Authenticate with `username` and `password`; returns token and user. |
| `GET` | `/me` | Bearer JWT | Return the authenticated user's `id` and `username`. |
| `GET` | `/notes?page=1&per_page=10` | Bearer JWT | List only the current user's notes with pagination metadata. `per_page` is limited to 100. |
| `POST` | `/notes` | Bearer JWT | Create a note with `title` and `content`; ownership is assigned by the API. |
| `GET` | `/notes/<id>` | Bearer JWT | Return one of the current user's notes. |
| `PATCH` | `/notes/<id>` | Bearer JWT | Update a note's `title` and/or `content`. |
| `DELETE` | `/notes/<id>` | Bearer JWT | Delete one of the current user's notes. |

`GET /notes` returns an object with `items`, `page`, `per_page`, `total`, and
`pages`. Note responses include `id`, `title`, `content`, `user_id`,
`created_at`, and `updated_at`.

## Tests

```bash
pipenv run pytest
```
