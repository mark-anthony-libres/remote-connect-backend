from datetime import datetime
from sqlalchemy.orm import Session
from typing import Type, TypeVar, Generic, Optional, List

T = TypeVar('T')

class BaseRepository(Generic[T]):
    def __init__(self, db: Session, model: Type[T]):
        self.db = db
        self.model = model

    def get_by_id(self, id) -> Optional[T]:
        return self.db.query(self.model).get(id)

    def all(self) -> List[T]:
        return self.db.query(self.model).all()
    
    @property
    def query(self):
        return self.db.query(self.model)

    def create(self, obj: T) -> T:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj: T) -> T:
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: T):
        self.db.delete(obj)
        self.db.commit()

    def soft_delete(self, obj: T) -> T:
        obj.deleted_at = datetime.now()
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def restore(self, obj: T) -> T:
        obj.deleted_at = None
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def get_active_by_id(self, id) -> Optional[T]:
        query = self.db.query(self.model).filter(self.model.id == id)
        if hasattr(self.model, 'deleted_at'):
            query = query.filter(self.model.deleted_at.is_(None))
        return query.first()

    def total_count(self) -> int:
        if hasattr(self.model, 'deleted_at'):
            query = self.db.query(self.model).filter(self.model.deleted_at.is_(None))
        else:
            query = self.db.query(self.model)
        return query.count()

    def count_created_between(self, start: datetime, end: datetime) -> int:
        query = self.db.query(self.model).filter(self.model.created_at >= start, self.model.created_at < end)
        if hasattr(self.model, 'deleted_at'):
            query = query.filter(self.model.deleted_at.is_(None))
        return query.count()

    def count_created_before(self, cutoff: datetime) -> int:
        query = self.db.query(self.model).filter(self.model.created_at < cutoff)
        if hasattr(self.model, 'deleted_at'):
            query = query.filter(self.model.deleted_at.is_(None))
        return query.count()
