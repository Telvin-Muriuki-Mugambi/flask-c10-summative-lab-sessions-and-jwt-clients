import pytest

from app import create_app, db
from models import Note, User


@pytest.fixture()
def client():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def signup(client, username):
    response = client.post(
        "/signup",
        json={
            "username": username,
            "password": "secure-password",
            "password_confirmation": "secure-password",
        },
    )
    assert response.status_code == 201
    data = response.get_json()
    return data["token"], data["user"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_login_and_current_user(client):
    token, user = signup(client, "alice")
    assert user == {"id": 1, "username": "alice"}

    login_response = client.post(
        "/login",
        json={"username": "alice", "password": "secure-password"},
    )
    assert login_response.status_code == 200
    assert login_response.get_json()["user"] == user

    me_response = client.get("/me", headers=auth_headers(token))
    assert me_response.status_code == 200
    assert me_response.get_json() == user

    stored_user = db.session.get(User, user["id"])
    assert stored_user.password_hash != "secure-password"


def test_authentication_and_signup_validation(client):
    assert client.get("/me").status_code == 401
    assert client.post("/signup", json={}).get_json()["errors"]
    assert client.post(
        "/signup",
        json={
            "username": "alice",
            "password": "secure-password",
            "password_confirmation": "different-password",
        },
    ).status_code == 400
    assert client.post(
        "/signup",
        json={
            "username": "alice",
            "password": "secure-password",
            "password_confirmation": "secure-password",
        },
    ).status_code == 201
    assert client.post(
        "/signup",
        json={
            "username": "alice",
            "password": "secure-password",
            "password_confirmation": "secure-password",
        },
    ).status_code == 409
    assert client.post(
        "/login",
        json={"username": "alice", "password": "incorrect-password"},
    ).status_code == 401
    assert client.post(
        "/login",
        json={"username": "alice", "password": "x" * 73},
    ).status_code == 401


def test_note_crud_is_limited_to_owner(client):
    alice_token, _alice = signup(client, "alice")
    bob_token, _bob = signup(client, "bob")
    alice_headers = auth_headers(alice_token)
    bob_headers = auth_headers(bob_token)

    create_response = client.post(
        "/notes",
        headers=alice_headers,
        json={"title": "Private note", "content": "Alice's content"},
    )
    assert create_response.status_code == 201
    note = create_response.get_json()
    note_id = note["id"]
    assert note["user_id"] == 1

    assert client.get(f"/notes/{note_id}", headers=bob_headers).status_code == 404
    assert client.patch(
        f"/notes/{note_id}",
        headers=bob_headers,
        json={"title": "Stolen"},
    ).status_code == 404
    assert client.delete(f"/notes/{note_id}", headers=bob_headers).status_code == 404
    assert client.get("/notes", headers=bob_headers).get_json()["total"] == 0

    update_response = client.patch(
        f"/notes/{note_id}",
        headers=alice_headers,
        json={"title": "Updated title"},
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["title"] == "Updated title"

    assert client.delete(f"/notes/{note_id}", headers=alice_headers).status_code == 200
    assert client.get(f"/notes/{note_id}", headers=alice_headers).status_code == 404


def test_notes_are_paginated_and_invalid_pagination_is_rejected(client):
    token, user = signup(client, "alice")
    with client.application.app_context():
        db.session.add_all(
            [
                Note(title=f"Note {number}", content="Content", user_id=user["id"])
                for number in range(3)
            ]
        )
        db.session.commit()

    response = client.get("/notes?page=2&per_page=2", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.get_json()["total"] == 3
    assert len(response.get_json()["items"]) == 1
    assert response.get_json()["pages"] == 2
    assert client.get("/notes?page=0", headers=auth_headers(token)).status_code == 400
    assert client.get("/notes?per_page=101", headers=auth_headers(token)).status_code == 400
