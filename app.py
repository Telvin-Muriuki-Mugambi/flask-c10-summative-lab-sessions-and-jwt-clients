import os

from flask import Flask, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    current_user,
    jwt_required,
)
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from extensions import bcrypt, db, jwt, migrate
from models import Note, User

MAX_PER_PAGE = 100
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///app.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_ACCESS_TOKEN_EXPIRES=3600,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or not app.config["JWT_SECRET_KEY"]:
        raise RuntimeError("Set SECRET_KEY and JWT_SECRET_KEY before starting the API.")

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)

    @jwt.user_lookup_loader
    def load_user(_jwt_header, jwt_data):
        try:
            user_id = int(jwt_data["sub"])
        except (KeyError, TypeError, ValueError):
            return None
        return db.session.get(User, user_id)

    @jwt.user_lookup_error_loader
    def user_lookup_error(_jwt_header, _jwt_data):
        return jsonify(errors=["User associated with this token no longer exists."]), 401

    @jwt.unauthorized_loader
    def missing_token_error(reason):
        return jsonify(errors=[reason]), 401

    @jwt.invalid_token_loader
    def invalid_token_error(reason):
        return jsonify(errors=[reason]), 401

    @jwt.expired_token_loader
    def expired_token_error(_jwt_header, _jwt_payload):
        return jsonify(errors=["Access token has expired."]), 401

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify(errors=[error.description]), error.code

    @app.post("/signup")
    def signup():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(errors=["A JSON request body is required."]), 400

        username = payload.get("username")
        password = payload.get("password")
        password_confirmation = payload.get("password_confirmation")
        if not isinstance(username, str) or not username.strip():
            return jsonify(errors=["Username is required."]), 400
        username = username.strip()
        if len(username) > 80:
            return jsonify(errors=["Username must be 80 characters or fewer."]), 400
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            return jsonify(errors=[f"Password must be at least {MIN_PASSWORD_LENGTH} characters."]), 400
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return jsonify(errors=["Password must be 72 bytes or fewer."]), 400
        if password != password_confirmation:
            return jsonify(errors=["Password confirmation does not match."]), 400
        if User.query.filter_by(username=username).first():
            return jsonify(errors=["Username is already taken."]), 409

        user = User(
            username=username,
            password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(errors=["Username is already taken."]), 409

        token = create_access_token(identity=str(user.id))
        return jsonify(token=token, user=user.to_dict()), 201

    @app.post("/login")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(errors=["A JSON request body is required."]), 400

        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return jsonify(errors=["Username and password are required."]), 400
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return jsonify(errors=["Invalid username or password."]), 401

        user = User.query.filter_by(username=username.strip()).first()
        if user is None or not bcrypt.check_password_hash(user.password_hash, password):
            return jsonify(errors=["Invalid username or password."]), 401

        token = create_access_token(identity=str(user.id))
        return jsonify(token=token, user=user.to_dict()), 200

    @app.get("/me")
    @jwt_required()
    def me():
        return jsonify(current_user.to_dict())

    @app.get("/notes")
    @jwt_required()
    def list_notes():
        page = _positive_int(request.args.get("page", "1"))
        per_page = _positive_int(request.args.get("per_page", "10"))
        if page is None:
            return jsonify(errors=["page must be a positive integer."]), 400
        if per_page is None or per_page > MAX_PER_PAGE:
            return jsonify(errors=[f"per_page must be between 1 and {MAX_PER_PAGE}."]), 400

        pagination = (
            Note.query.filter_by(user_id=current_user.id)
            .order_by(Note.created_at.desc(), Note.id.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return jsonify(
            items=[note.to_dict() for note in pagination.items],
            page=pagination.page,
            per_page=pagination.per_page,
            total=pagination.total,
            pages=pagination.pages,
        )

    @app.post("/notes")
    @jwt_required()
    def create_note():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(errors=["A JSON request body is required."]), 400
        title = payload.get("title")
        content = payload.get("content")
        errors = _note_field_errors(title, content)
        if errors:
            return jsonify(errors=errors), 400

        note = Note(title=title.strip(), content=content, user_id=current_user.id)
        db.session.add(note)
        db.session.commit()
        return jsonify(note.to_dict()), 201

    @app.get("/notes/<int:note_id>")
    @jwt_required()
    def get_note(note_id):
        note = _owned_note(note_id)
        if note is None:
            return jsonify(errors=["Note not found."]), 404
        return jsonify(note.to_dict())

    @app.patch("/notes/<int:note_id>")
    @jwt_required()
    def update_note(note_id):
        note = _owned_note(note_id)
        if note is None:
            return jsonify(errors=["Note not found."]), 404

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify(errors=["A non-empty JSON request body is required."]), 400
        unknown_fields = set(payload) - {"title", "content"}
        if unknown_fields:
            return jsonify(errors=["Only title and content can be updated."]), 400
        if "title" in payload:
            title = payload["title"]
            if not isinstance(title, str) or not title.strip():
                return jsonify(errors=["Title must be a non-empty string."]), 400
            if len(title.strip()) > 200:
                return jsonify(errors=["Title must be 200 characters or fewer."]), 400
            note.title = title.strip()
        if "content" in payload:
            if not isinstance(payload["content"], str):
                return jsonify(errors=["Content must be a string."]), 400
            note.content = payload["content"]

        db.session.commit()
        return jsonify(note.to_dict())

    @app.delete("/notes/<int:note_id>")
    @jwt_required()
    def delete_note(note_id):
        note = _owned_note(note_id)
        if note is None:
            return jsonify(errors=["Note not found."]), 404
        db.session.delete(note)
        db.session.commit()
        return jsonify(message="Note deleted.")

    return app


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _note_field_errors(title, content):
    errors = []
    if not isinstance(title, str) or not title.strip():
        errors.append("Title must be a non-empty string.")
    elif len(title.strip()) > 200:
        errors.append("Title must be 200 characters or fewer.")
    if not isinstance(content, str):
        errors.append("Content must be a string.")
    return errors


def _owned_note(note_id):
    return Note.query.filter_by(id=note_id, user_id=current_user.id).first()


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555)
