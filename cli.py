import getpass
import json
import os
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_URL = "http://127.0.0.1:5555"


class APIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class NotesAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: Optional[str] = None

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, int]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=10) as response:
                body = response.read()
        except HTTPError as error:
            body = error.read()
            message = self._error_message(body) or f"Request failed with status {error.code}."
            raise APIError(message, error.code) from error
        except URLError as error:
            raise APIError(f"Could not connect to the API: {error.reason}") from error

        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError("The API returned an invalid JSON response.") from error

    @staticmethod
    def _error_message(body: bytes) -> Optional[str]:
        try:
            response = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        errors = response.get("errors") if isinstance(response, dict) else None
        if isinstance(errors, list) and errors:
            return " ".join(str(error) for error in errors)
        return None


class NotesCLI:
    def __init__(self, api: NotesAPI):
        self.api = api

    def run(self) -> None:
        while True:
            if self.api.token:
                if not self._authenticated_menu():
                    return
            elif not self._auth_menu():
                return

    def _auth_menu(self) -> bool:
        print("\nNotes CLI")
        print("1. Log in")
        print("2. Sign up")
        print("0. Exit")
        choice = input("Choose an option: ").strip()
        if choice == "0":
            return False
        if choice == "1":
            self._authenticate("/login")
        elif choice == "2":
            self._authenticate("/signup")
        else:
            print("Choose 1, 2, or 0.")
        return True

    def _authenticate(self, endpoint: str) -> None:
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ")
        payload = {"username": username, "password": password}
        if endpoint == "/signup":
            payload["password_confirmation"] = getpass.getpass("Confirm password: ")
        try:
            response = self.api.request("POST", endpoint, payload)
            self.api.token = response["token"]
            user = response["user"]
            print(f"Signed in as {user['username']}.")
        except (APIError, KeyError, TypeError) as error:
            print(f"Error: {error}")

    def _authenticated_menu(self) -> bool:
        print("\nNotes")
        print("1. List notes")
        print("2. Create note")
        print("3. View note")
        print("4. Update note")
        print("5. Delete note")
        print("6. Show account")
        print("7. Log out")
        print("0. Exit")
        choice = input("Choose an option: ").strip()
        actions = {
            "1": self._list_notes,
            "2": self._create_note,
            "3": self._view_note,
            "4": self._update_note,
            "5": self._delete_note,
            "6": self._show_account,
        }
        if choice == "0":
            return False
        if choice == "7":
            self.api.token = None
            print("Logged out.")
            return True
        action = actions.get(choice)
        if action is None:
            print("Choose a number from 0 to 7.")
            return True
        try:
            action()
        except APIError as error:
            print(f"Error: {error}")
            if error.status_code == 401:
                self.api.token = None
                print("Please log in again.")
        return True

    def _list_notes(self) -> None:
        page = self._positive_integer("Page [1]: ", 1)
        per_page = self._positive_integer("Notes per page [10]: ", 10)
        response = self.api.request(
            "GET", "/notes", query={"page": page, "per_page": per_page}
        )
        print(f"\n{response['total']} note(s), page {response['page']} of {response['pages']}.")
        for note in response["items"]:
            print(f"{note['id']}. {note['title']}")

    def _create_note(self) -> None:
        title = input("Title: ")
        content = input("Content: ")
        note = self.api.request(
            "POST", "/notes", {"title": title, "content": content}
        )
        print(f"Created note {note['id']}: {note['title']}")

    def _view_note(self) -> None:
        note_id = self._positive_integer("Note ID: ")
        note = self.api.request("GET", f"/notes/{note_id}")
        print(f"\n{note['title']}\n{note['content']}")

    def _update_note(self) -> None:
        note_id = self._positive_integer("Note ID: ")
        note = self.api.request("GET", f"/notes/{note_id}")
        print(f"Current title: {note['title']}")
        print(f"Current content: {note['content']}")
        title = input("New title (leave blank to keep): ")
        content = input("New content (leave blank to keep): ")
        payload = {}
        if title:
            payload["title"] = title
        if content:
            payload["content"] = content
        if not payload:
            print("No changes made.")
            return
        updated = self.api.request("PATCH", f"/notes/{note_id}", payload)
        print(f"Updated note {updated['id']}.")

    def _delete_note(self) -> None:
        note_id = self._positive_integer("Note ID: ")
        confirmation = input(f"Delete note {note_id}? [y/N]: ").strip().lower()
        if confirmation != "y":
            print("Deletion cancelled.")
            return
        self.api.request("DELETE", f"/notes/{note_id}")
        print("Note deleted.")

    def _show_account(self) -> None:
        user = self.api.request("GET", "/me")
        print(f"Signed in as {user['username']} (user {user['id']}).")

    @staticmethod
    def _positive_integer(prompt: str, default: Optional[int] = None) -> int:
        while True:
            value = input(prompt).strip()
            if not value and default is not None:
                return default
            try:
                number = int(value)
            except ValueError:
                number = 0
            if number > 0:
                return number
            print("Enter a positive integer.")


def main() -> None:
    api = NotesAPI(os.environ.get("API_URL", DEFAULT_API_URL))
    try:
        NotesCLI(api).run()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
