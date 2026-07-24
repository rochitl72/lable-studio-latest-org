"""Projects, labels, and project membership.

A *project* is the top-level container: it owns images, label classes, and
dataset versions. This router handles creating/listing/deleting projects and
their label classes, plus the membership endpoints an admin uses to decide who
may work on a project.

Access rules enforced here:
  * Listing projects returns only the ones the caller belongs to (admins see
    all). Membership is checked through `app.services.membership`.
  * Creating/deleting projects and labels, and editing membership, are
    admin-only (`require_admin`).

Every mutation writes an entry to the audit log via `app.services.activity`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import current_user, require_admin
from app.db.database import get_db
from app.models import (
    Action, DatasetVersion, Label, Project, ProjectMember, User,
)
from app.services import activity, membership

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    task_type: str = "detection"


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    task_type: str

    class Config:
        from_attributes = True


class LabelCreate(BaseModel):
    name: str
    color: str = "#ffffff"
    shortcut: str = ""
    keypoint_names: list[str] | None = None
    skeleton_edges: list[list[int]] | None = None


class LabelOut(BaseModel):
    id: int
    name: str
    color: str
    shortcut: str
    keypoint_names: list[str] | None = None
    skeleton_edges: list[list[int]] | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Admins see every project; a plain user sees only their memberships."""
    stmt = select(Project).order_by(Project.created_at.desc())
    if not user.is_admin:
        member_of = await membership.member_project_ids(db, user)
        if not member_of:
            return []
        stmt = stmt.where(Project.id.in_(member_of))
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = Project(**payload.model_dump(), created_by=user.id)
    db.add(project)
    await db.flush()
    version = DatasetVersion(
        project_id=project.id, name="v1 — working", version_number=1,
        created_by=user.id,
    )
    db.add(version)
    await db.flush()
    project.active_version_id = version.id
    await activity.record(
        db, user, Action.PROJECT_CREATE,
        project_id=project.id, details={"name": project.name},
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await membership.assert_member(db, project_id, user)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await activity.record(
        db, user, Action.PROJECT_DELETE,
        project_id=project.id, details={"name": project.name},
    )
    await db.delete(project)
    await db.commit()
    return {"ok": True}


# ─── Labels ──────────────────────────────────────────────────────
@router.get("/{project_id}/labels", response_model=list[LabelOut])
async def list_labels(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await membership.assert_member(db, project_id, user)
    res = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.id)
    )
    return res.scalars().all()


@router.post("/{project_id}/labels", response_model=LabelOut)
async def create_label(
    project_id: int,
    payload: LabelCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    label = Label(project_id=project_id, **payload.model_dump())
    db.add(label)
    await db.flush()
    await activity.record(
        db, user, Action.LABEL_CREATE,
        project_id=project_id, details={"name": label.name},
    )
    await db.commit()
    await db.refresh(label)
    return label


@router.delete("/{project_id}/labels/{label_id}")
async def delete_label(
    project_id: int,
    label_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    label = await db.get(Label, label_id)
    if not label or label.project_id != project_id:
        raise HTTPException(404, "Label not found")
    await db.delete(label)
    await db.commit()
    return {"ok": True}


# ─── Membership (admin-only) ─────────────────────────────────────────
class MemberOut(BaseModel):
    user_id: int
    username: str
    full_name: str
    role: str
    is_active: bool


class MemberAdd(BaseModel):
    user_id: int


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rows = await db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.username)
    )
    return [
        MemberOut(
            user_id=u.id, username=u.username, full_name=u.full_name,
            role=u.role, is_active=u.is_active,
        )
        for u in rows.scalars().all()
    ]


@router.post("/{project_id}/members", response_model=MemberOut)
async def add_member(
    project_id: int,
    payload: MemberAdd,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    target = await db.get(User, payload.user_id)
    if not target:
        raise HTTPException(404, "User not found")

    existing = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    if not existing:
        db.add(ProjectMember(
            project_id=project_id, user_id=payload.user_id, added_by=admin.id,
        ))
        await activity.record(
            db, admin, Action.MEMBER_ADD,
            project_id=project_id,
            details={"user_id": target.id, "username": target.username},
        )
        await db.commit()
    return MemberOut(
        user_id=target.id, username=target.username, full_name=target.full_name,
        role=target.role, is_active=target.is_active,
    )


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(
    project_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if not member:
        return {"ok": True, "removed": False}
    target = await db.get(User, user_id)
    await db.delete(member)
    await activity.record(
        db, admin, Action.MEMBER_REMOVE,
        project_id=project_id,
        details={"user_id": user_id,
                 "username": target.username if target else str(user_id)},
    )
    await db.commit()
    return {"ok": True, "removed": True}
