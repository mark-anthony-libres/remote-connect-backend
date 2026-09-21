from sqlalchemy.orm import Session, Query
from typing import Any, Type, TypeVar, Generic, Optional, List

from database.session_factory import SessionLocal

T = TypeVar('T')

class GenericRepository(Generic[T]):
    def __init__(self, model: Type[T], db: Optional[Session] = None):
        self.owns_session = db is None
        self.db = db if db is not None else SessionLocal()
        self.model = model

    def __enter__(self) -> "GenericRepository[T]":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.owns_session:
            self.db.close()

    def get_by_id(self, entity_id: Any) -> Optional[T]:
        return self.db.query(self.model).get(entity_id)

    def get_all(self) -> List[T]:
        return self.db.query(self.model).all()

    @property
    def base_query(self) -> Query[T]:
        return self.db.query(self.model)

    def _persist(self) -> None:
        if self.owns_session:
            self.db.commit()
        else:
            self.db.flush()

    def create(self, obj: T) -> T:
        self.db.add(obj)
        self._persist()
        self.db.refresh(obj)
        return obj

    def save_changes(self, obj: T) -> T:
        self._persist()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: T) -> None:
        self.db.delete(obj)
        self._persist()
