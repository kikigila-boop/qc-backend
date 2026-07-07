from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.user import User
from ..schemas.user import UserCreate, UserOut, UserUpdate, UserResetPassword
from ..utils.security import get_current_user, hash_password

router = APIRouter(prefix="/users", tags=["Users"])


def _require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Public (authenticated) ──────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ── Public (authenticated) — editor list for dropdowns ──────────────────────

@router.get("/editors", response_model=List[UserOut])
def list_editors(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return all active users with role editor or admin — used to populate dropdowns."""
    return (
        db.query(User)
        .filter(User.role.in_(["editor", "chef_editor", "designer", "admin"]), User.is_active == True)
        .order_by(User.name)
        .all()
    )


# ── All-active — for PIC assignment dropdowns (admin + supervisor) ────────────

@router.get("/active", response_model=List[UserOut])
def list_active_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all active users regardless of role — for PIC/assignment dropdowns."""
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Admin/supervisor only")
    return (
        db.query(User)
        .filter(User.is_active == True)
        .order_by(User.name)
        .all()
    )


# ── Admin only ──────────────────────────────────────────────────────────────

@router.get("", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    """List all users (active + inactive)."""
    return db.query(User).order_by(User.created_at.desc()).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    """Create a new user (admin only)."""
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(_require_admin),
):
    """Update user name, role, or active status (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Admin cannot deactivate themselves
    if user_id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, val)

    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: int,
    payload: UserResetPassword,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    """Reset a user's password (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(_require_admin),
):
    """Soft-delete: set is_active=False (admin only). Cannot delete own account."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
