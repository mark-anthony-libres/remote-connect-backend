import enum
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from database.entities.base import Base


class TaskRunStatusEnum(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TASK_RUN_STATUS_ENUM = sa.Enum(
    TaskRunStatusEnum,
    name="task_run_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    create_type=True,
)


class TaskRunLogRetentionStatusEnum(str, enum.Enum):
    LOCAL = "local"
    ARCHIVED = "archived"
    PURGED = "purged"


TASK_RUN_LOG_RETENTION_STATUS_ENUM = sa.Enum(
    TaskRunLogRetentionStatusEnum,
    name="task_run_log_retention_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    create_type=True,
)


@Entity()
class TaskRunEntity(Base):
    __tablename__ = "tblm_task_run"

    id = sa.Column(UUID(as_uuid=True), primary_key=True)
    task_name = sa.Column(sa.Text, nullable=False)
    name = sa.Column(sa.Text, nullable=True)
    tag = sa.Column(sa.Text, nullable=True)
    status = sa.Column(
        TASK_RUN_STATUS_ENUM,
        nullable=False,
        default=TaskRunStatusEnum.QUEUED,
        server_default=TaskRunStatusEnum.QUEUED.value,
    )
    is_retry = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    finished_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    error = sa.Column(sa.Text, nullable=True)
    log_s3_bucket = sa.Column(sa.Text, nullable=True)
    log_s3_path = sa.Column(sa.Text, nullable=True)
    log_s3_url = sa.Column(sa.Text, nullable=True)
    log_retention_status = sa.Column(
        TASK_RUN_LOG_RETENTION_STATUS_ENUM,
        nullable=False,
        default=TaskRunLogRetentionStatusEnum.LOCAL,
        server_default=TaskRunLogRetentionStatusEnum.LOCAL.value,
    )
