import os

from app import app, bcrypt, db
from models import Note, User


def seed_database():
    username = os.environ.get("SEED_USERNAME")
    password = os.environ.get("SEED_PASSWORD")
    if not username or not password:
        raise RuntimeError("Set SEED_USERNAME and SEED_PASSWORD to create the seed user.")
    username = username.strip()
    if not username or len(username) > 80:
        raise ValueError("SEED_USERNAME must contain between 1 and 80 characters.")
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise ValueError("SEED_PASSWORD must be between 8 characters and 72 UTF-8 bytes.")

    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
            )
            db.session.add(user)
            db.session.flush()
        if not user.notes:
            db.session.add_all(
                [
                    Note(title="Welcome", content="This is your first note.", user_id=user.id),
                    Note(title="Next steps", content="Create, update, and organize your notes.", user_id=user.id),
                ]
            )
        db.session.commit()


if __name__ == "__main__":
    seed_database()
