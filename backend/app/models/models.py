"""SQLAlchemy ORM models.

Types are declared Postgres-first: JSON columns become JSONB and timestamps
are timezone-aware. `with_variant` keeps the same models loadable on SQLite so
the test suite can run without a database server — production is Postgres.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# JSONB on Postgres (indexable, binary), plain JSON elsewhere.
JSONType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    """Timezone-aware UTC. `datetime.utcnow` is naive and deprecated in 3.12+."""
    return datetime.now(timezone.utc)


TimestampTZ = DateTime(timezone=True)


# ─── Identity ────────────────────────────────────────────────────────
class Role:
    """Global roles. Two tiers: a plain USER, and an ADMIN who can do everything.

    The old three-tier ladder (annotator < reviewer < admin) was collapsed:
    everything the reviewer role could do now belongs to admin. `ANNOTATOR` and
    `REVIEWER` are kept as aliases only so old references don't break during the
    migration — new code should use USER / ADMIN.
    """

    USER = "user"
    ADMIN = "admin"

    # Backwards-compatible aliases (do not use in new code).
    ANNOTATOR = USER
    REVIEWER = ADMIN

    ALL = (USER, ADMIN)
    # Rank lets permission checks ask "at least admin?" without listing roles.
    RANK = {USER: 1, ADMIN: 2}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=Role.USER, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set on the seeded admin (and any admin-created account) so the UI can force
    # a password change on first sign-in. Cleared once the password is changed.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_review(self) -> bool:
        """Review powers (approve/reject, edit others' work) now belong to admin.

        Kept as a named property so the many call sites reading "can this user
        review?" stay readable; it simply means "is an admin" under two roles.
        """
        return self.role == Role.ADMIN


# ─── Projects & data ─────────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(50), default="detection")
    # projects → dataset_versions → projects is a genuine cycle. use_alter
    # makes this constraint a follow-up ALTER TABLE instead of part of the
    # CREATE, so the tables can be created in a valid order. Without it
    # Postgres fails the first migration on a forward reference.
    active_version_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "dataset_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_projects_active_version",
        ),
        nullable=True,
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)

    images: Mapped[list["Image"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    labels: Mapped[list["Label"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="DatasetVersion.project_id",
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    parent_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)

    project: Mapped[Project] = relationship(
        back_populates="versions", foreign_keys=[project_id]
    )


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#ffffff")
    shortcut: Mapped[str] = mapped_column(String(10), default="")
    keypoint_names: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    skeleton_edges: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="labels")


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="unannotated", index=True)
    split: Mapped[str] = mapped_column(String(10), default="train")
    sequence_id: Mapped[str] = mapped_column(String(64), default="")
    frame_index: Mapped[int] = mapped_column(Integer, default=0)

    # Workload: who should annotate this.
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)

    # Review outcome, set by a reviewer or admin.
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(TimestampTZ, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="images")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_images_project_status", "project_id", "status"),
    )


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), index=True
    )
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    geometry: Mapped[dict] = mapped_column(JSONType)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(20), default="manual")

    # Ownership: annotators may only modify their own work.
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TimestampTZ, default=utcnow, onupdate=utcnow
    )

    image: Mapped[Image] = relationship(back_populates="annotations")
    label: Mapped[Label] = relationship()


class ProjectMember(Base):
    """Which users may work on which project.

    Membership is the access boundary: a non-member (who is not an admin) cannot
    see or touch a project at all. Role stays global — this table only answers
    "is this user allowed on this project", not "as what".
    """

    __tablename__ = "project_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    added_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)
    added_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )


# ─── Collaboration ───────────────────────────────────────────────────
class ImageLock(Base):
    """Soft check-out. One annotator holds an image at a time.

    Locks expire (see LOCK_TIMEOUT_SECONDS) so a closed laptop never strands
    an image permanently.
    """

    __tablename__ = "image_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    acquired_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow)

    __table_args__ = (UniqueConstraint("image_id", name="uq_image_lock"),)


class ActivityLog(Base):
    """Append-only audit trail. Every mutation writes one row."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised so the feed still reads correctly after a user is deleted.
    username: Mapped[str] = mapped_column(String(80), default="")

    action: Mapped[str] = mapped_column(String(50), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    image_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    annotation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Free-form context: before/after geometry, old/new status, and so on.
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TimestampTZ, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_activity_project_created", "project_id", "created_at"),
        Index("ix_activity_user_created", "user_id", "created_at"),
    )


class Action:
    """Canonical action names written to ActivityLog.action."""

    LOGIN = "login"
    LOGOUT = "logout"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DEACTIVATE = "user.deactivate"
    MEMBER_ADD = "project.member_add"
    MEMBER_REMOVE = "project.member_remove"
    PROJECT_CREATE = "project.create"
    PROJECT_DELETE = "project.delete"
    LABEL_CREATE = "label.create"
    LABEL_DELETE = "label.delete"
    IMAGE_UPLOAD = "image.upload"
    IMAGE_DELETE = "image.delete"
    IMAGE_ASSIGN = "image.assign"
    IMAGE_STATUS = "image.status_change"
    ANNOTATION_CREATE = "annotation.create"
    ANNOTATION_UPDATE = "annotation.update"
    ANNOTATION_DELETE = "annotation.delete"
    REVIEW_APPROVE = "review.approve"
    REVIEW_REJECT = "review.reject"
    REVIEW_REQUEST = "review.request"
    VERSION_CREATE = "version.create"
    EXPORT = "export"
