"""Project membership checks.

Membership is the access boundary for non-admins: a plain user can only see and
touch projects they've been added to. Admins bypass membership entirely — they
can reach every project.
"""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Image, ProjectMember, User


async def is_member(db: AsyncSession, project_id: int, user: User) -> bool:
    """True if the user may access the project (admin, or an explicit member)."""
    if user.is_admin:
        return True
    found = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    return found is not None


async def member_project_ids(db: AsyncSession, user: User) -> set[int]:
    """The set of project ids a non-admin user belongs to."""
    rows = await db.execute(
        select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    )
    return {r[0] for r in rows.all()}


async def assert_member(db: AsyncSession, project_id: int, user: User) -> None:
    """Raise 403 unless the user may access the project."""
    if not await is_member(db, project_id, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project.",
        )


async def assert_member_by_image(db: AsyncSession, image_id: int, user: User) -> Image:
    """Look up an image, confirm the user may access its project, and return it.

    Convenience for the many endpoints that receive an `image_id` and must both
    load the image (404 if missing) and enforce project membership (403 if the
    caller isn't a member and isn't an admin). Returns the loaded image so the
    caller doesn't fetch it twice.
    """
    image = await db.get(Image, image_id)
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    await assert_member(db, image.project_id, user)
    return image
