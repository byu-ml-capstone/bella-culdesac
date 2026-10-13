from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db, hash_token, utc_now
from models import AppSession, TeamMember

password_hash = PasswordHash.recommended()
SESSION_COOKIE = "culdesac_session"


def create_session(db: Session, member: TeamMember) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(
        AppSession(
            member_id=member.id,
            token_hash=hash_token(raw_token),
            expires_at=utc_now() + timedelta(hours=24),
        )
    )
    db.commit()
    return raw_token


def current_member(request: Request, db: Session = Depends(get_db)) -> TeamMember:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    session = db.scalar(
        select(AppSession).where(
            AppSession.token_hash == hash_token(token),
            AppSession.revoked_at.is_(None),
            AppSession.expires_at > utc_now(),
        )
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    member = db.get(TeamMember, session.member_id)
    if not member or member.membership_status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="member is unavailable")
    return member


def require_team_lead(member: TeamMember = Depends(current_member)) -> TeamMember:
    if member.role != "Team Lead":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Team Lead permission required")
    return member


def require_editor(member: TeamMember = Depends(current_member)) -> TeamMember:
    if member.role not in {"Team Lead", "Team Member"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="project edit permission required")
    return member
