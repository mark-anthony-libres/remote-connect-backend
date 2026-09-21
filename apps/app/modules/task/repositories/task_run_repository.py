from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.app.modules.task.entities.task_run_entity import TaskRunEntity, TaskRunLogRetentionStatusEnum, TaskRunStatusEnum
from apps.app.utils.repositories.base_repository import BaseRepository


class TaskRunRepository(BaseRepository[TaskRunEntity]):


    def __init__(self, db: Session):
        super().__init__(db, TaskRunEntity)

    @staticmethod
    def _to_uuid(task_id: str) -> UUID:
        return UUID(str(task_id))

    def create_task_run(
        self, task_id: str, task_name: str, tag: str | None = None, name: str | None = None
    ) -> TaskRunEntity:
        stmt = (
            pg_insert(TaskRunEntity)
            .values(
                id=self._to_uuid(task_id),
                task_name=task_name,
                tag=tag,
                name=name,
                status=TaskRunStatusEnum.QUEUED,
            )
            .on_conflict_do_nothing(index_elements=[TaskRunEntity.id])
        )
        self.db.execute(stmt)
        self.db.commit()
        return self.get_by_id(self._to_uuid(task_id))

    def mark_running(self, task_id: str, is_retry: bool = False) -> TaskRunEntity | None:
        task_run = self.get_by_id(self._to_uuid(task_id))
        if not task_run:
            return None
        task_run.status = TaskRunStatusEnum.RUNNING
        task_run.started_at = datetime.now(UTC)
        task_run.is_retry = is_retry
        task_run.error = None
        return self.update(task_run)

    def try_start(
        self,
        task_id: str,
        task_name: str,
        tag: str | None = None,
        name: str | None = None,
        is_retry: bool = False,
    ) -> bool:
        id_ = self._to_uuid(task_id)
        now = datetime.now(UTC)

        stmt = pg_insert(TaskRunEntity).values(
            id=id_,
            task_name=task_name,
            tag=tag,
            name=name,
            status=TaskRunStatusEnum.RUNNING,
            started_at=now,
            is_retry=is_retry,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TaskRunEntity.id],
            set_={
                "status": TaskRunStatusEnum.RUNNING,
                "started_at": now,
                "is_retry": is_retry,
                "error": None,
            },
            where=(TaskRunEntity.status == TaskRunStatusEnum.QUEUED),
        ).returning(TaskRunEntity.id)

        result = self.db.execute(stmt)
        self.db.commit()
        return result.first() is not None

    def mark_success(self, task_id: str) -> TaskRunEntity | None:
        task_run = self.get_by_id(self._to_uuid(task_id))
        if not task_run:
            return None
        now = datetime.now(UTC)
        task_run.status = TaskRunStatusEnum.SUCCESS
        task_run.finished_at = now
        task_run.started_at = task_run.started_at or now
        task_run.error = None
        return self.update(task_run)

    def mark_failed(self, task_id: str, error: str | None) -> TaskRunEntity | None:
        task_run = self.get_by_id(self._to_uuid(task_id))
        if not task_run:
            return None
        now = datetime.now(UTC)
        task_run.status = TaskRunStatusEnum.FAILED
        task_run.finished_at = now
        task_run.started_at = task_run.started_at or now
        task_run.error = error
        return self.update(task_run)

    def mark_interrupted(self, task_id: str, reason: str | None = None) -> TaskRunEntity | None:
        task_run = self.get_by_id(self._to_uuid(task_id))
        if not task_run:
            return None
        now = datetime.now(UTC)
        task_run.status = TaskRunStatusEnum.INTERRUPTED
        task_run.finished_at = now
        task_run.started_at = task_run.started_at or now
        task_run.error = reason
        return self.update(task_run)

    def get_stale_queued_or_running(self, older_than: datetime) -> list[TaskRunEntity]:
        return (
            self.db.query(TaskRunEntity)
            .filter(
                TaskRunEntity.status.in_([
                    TaskRunStatusEnum.QUEUED,
                    TaskRunStatusEnum.RUNNING,
                ]),
                TaskRunEntity.created_at < older_than,
            )
            .all()
        )


    def get_task(self, task_id: str) -> TaskRunEntity | None:
        return self.get_by_id(self._to_uuid(task_id))

    def get_by_task_ids(self, task_ids: list[str]) -> list[TaskRunEntity]:
        if not task_ids:
            return []
        return (
            self.db.query(TaskRunEntity)
            .filter(TaskRunEntity.id.in_([self._to_uuid(task_id) for task_id in task_ids]))
            .all()
        )

    def get_recent_task_runs(self, limit: int = 50) -> list[TaskRunEntity]:
        return (
            self.db.query(TaskRunEntity)
            .order_by(TaskRunEntity.created_at.desc())
            .limit(limit)
            .all()
        )
    
    def get_last_process_task(self) -> TaskRunEntity | None:
        return (
            self.db.query(TaskRunEntity)
            .filter(
                TaskRunEntity.status.in_([
                    TaskRunStatusEnum.SUCCESS,
                    TaskRunStatusEnum.FAILED
                ])
            )
            .order_by(TaskRunEntity.finished_at.desc())
            .first()
        )
    
    def count_pending_since_last_process(self) -> int:
            last_process = self.get_last_process_task()
            if not last_process:
                return self.db.query(TaskRunEntity).filter(
                    TaskRunEntity.status.in_([
                        TaskRunStatusEnum.QUEUED,
                        TaskRunStatusEnum.RUNNING
                    ])
                ).count()
            return self.db.query(TaskRunEntity).filter(
                TaskRunEntity.status.in_([
                    TaskRunStatusEnum.QUEUED,
                    TaskRunStatusEnum.RUNNING
                ]),
                TaskRunEntity.created_at > last_process.created_at
            ).count()

    def get_expired_task_runs(self, cutoff: datetime) -> list[tuple]:
        rows = (
            self.db.query(TaskRunEntity.id, TaskRunEntity.log_s3_bucket, TaskRunEntity.log_s3_path)
            .filter(TaskRunEntity.created_at < cutoff)
            .all()
        )
        return [(str(row.id), row.log_s3_bucket, row.log_s3_path) for row in rows]

    def delete_by_ids(self, task_ids: list[str]) -> int:
        if not task_ids:
            return 0
        deleted = (
            self.db.query(TaskRunEntity)
            .filter(TaskRunEntity.id.in_([self._to_uuid(task_id) for task_id in task_ids]))
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted

    def get_log_ids_older_than(self, cutoff: datetime) -> list[str]:
        rows = self.db.query(TaskRunEntity.id).filter(TaskRunEntity.created_at < cutoff).all()
        return [str(row[0]) for row in rows]

    def set_log_archived(self, task_id: str, s3_bucket: str, s3_log_path: str, s3_log_url: str) -> None:
        task_run = self.get_by_id(self._to_uuid(task_id))
        if not task_run:
            return
        task_run.log_s3_bucket = s3_bucket
        task_run.log_s3_path = s3_log_path
        task_run.log_s3_url = s3_log_url
        task_run.log_retention_status = TaskRunLogRetentionStatusEnum.ARCHIVED
        self.update(task_run)
