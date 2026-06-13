import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def _aware(dt: datetime) -> datetime:
    """Return dt with UTC timezone, attaching it if the value is naive.

    SQLite strips timezone info on round-trip. Using DateTime(timezone=True)
    on the column stores an offset-aware value and ensures SQLAlchemy returns
    an aware datetime on all backends; this helper is a belt-and-suspenders
    guard for any value that somehow arrives naive.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class ExpiryMixin:
    """Mixin for models that have an ``expires_in`` (seconds) and ``created_at``."""

    expires_in: Mapped[int | None]
    created_at: Mapped[datetime]

    @property
    def is_expired(self) -> bool:
        if self.expires_in is None:
            return False
        return datetime.now(timezone.utc) > _aware(self.created_at) + timedelta(
            seconds=self.expires_in
        )

    @property
    def expires_at(self) -> datetime | None:
        if self.expires_in is None:
            return None
        return _aware(self.created_at) + timedelta(seconds=self.expires_in)


class ApiToken(ExpiryMixin, Base):
    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Share(Base):
    __tablename__ = "share"

    share_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, name="id", primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    links: Mapped[list["ShareLink"]] = relationship(
        "ShareLink", back_populates="share", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "share_id": str(self.share_id),
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
            "links": [link.to_dict() for link in self.links],
        }


class ShareLink(ExpiryMixin, Base):
    __tablename__ = "share_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, unique=True)
    share_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("share.id"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    share: Mapped["Share"] = relationship("Share", back_populates="links")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "link_id": str(self.link_id),
            "label": self.label,
            "expires_in": self.expires_in,
            "download_count": self.download_count,
            "created_at": self.created_at.isoformat(),
        }
