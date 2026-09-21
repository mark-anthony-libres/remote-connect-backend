from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, DateTime, event
import datetime

Base = declarative_base()


class BaseModel(Base):
    __abstract__ = True

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    class Config:
        orm_mode = True


# Automatically update updated_at on update
@event.listens_for(BaseModel, "before_update", propagate=True)
def set_updated_at(mapper, connection, target):
    target.updated_at = datetime.datetime.now(datetime.timezone.utc)