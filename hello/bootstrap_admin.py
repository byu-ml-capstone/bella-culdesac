from __future__ import annotations

import os

from sqlalchemy import select

from auth import password_hash
from database import SessionLocal, initialize_database
from models import TeamMember


def main() -> None:
    initialize_database()
    values = {
        "name": os.environ.get("BOOTSTRAP_ADMIN_NAME"),
        "email": os.environ.get("BOOTSTRAP_ADMIN_EMAIL"),
        "username": os.environ.get("BOOTSTRAP_ADMIN_USERNAME"),
        "password": os.environ.get("BOOTSTRAP_ADMIN_PASSWORD"),
    }
    if not all(values.values()):
        raise SystemExit("BOOTSTRAP_ADMIN_NAME/EMAIL/USERNAME/PASSWORD are required")
    with SessionLocal() as db:
        if db.scalar(select(TeamMember).where(TeamMember.role == "Team Lead", TeamMember.membership_status == "active")):
            raise SystemExit("an active Team Lead already exists")
        member = TeamMember(
            name=values["name"],
            email=values["email"],
            username=values["username"],
            password_hash=password_hash.hash(values["password"]),
            role="Team Lead",
        )
        db.add(member)
        db.commit()
        print(f"created Team Lead username={member.username}")


if __name__ == "__main__":
    main()
