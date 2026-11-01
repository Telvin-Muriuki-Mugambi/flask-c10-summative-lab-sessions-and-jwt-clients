import io
import json
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from cli import APIError, NotesAPI, NotesCLI


class MockResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def test_api_request_encodes_json_and_authorization():
    api = NotesAPI("http://localhost:5555/")
    api.token = "access-token"
    response_body = json.dumps({"id": 3, "title": "A note"}).encode("utf-8")

    with patch("cli.urlopen", return_value=MockResponse(response_body)) as urlopen:
        response = api.request(
            "POST",
            "/notes",
            {"title": "A note", "content": "Text"},
            query={"page": 2, "per_page": 5},
        )

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://localhost:5555/notes?page=2&per_page=5"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer access-token"
    assert json.loads(request.data) == {"title": "A note", "content": "Text"}
    assert response == {"id": 3, "title": "A note"}


def test_api_error_includes_server_message_and_status():
    error_body = json.dumps({"errors": ["Note not found."]}).encode("utf-8")
    error = HTTPError(
        "http://localhost:5555/notes/12",
        404,
        "Not Found",
        {},
        io.BytesIO(error_body),
    )
    api = NotesAPI("http://localhost:5555")

    with patch("cli.urlopen", side_effect=error):
        with pytest.raises(APIError, match="Note not found") as raised:
            api.request("GET", "/notes/12")

    assert raised.value.status_code == 404


def test_expired_token_returns_user_to_auth_menu():
    class ExpiredAPI:
        token = "expired-token"

        def request(self, *_args, **_kwargs):
            raise APIError("Access token has expired.", 401)

    api = ExpiredAPI()
    cli = NotesCLI(api)

    with patch("builtins.input", return_value="6"):
        assert cli._authenticated_menu() is True

    assert api.token is None
