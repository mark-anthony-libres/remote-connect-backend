from sqlalchemy.orm import Session

from apps.app.modules.miscellaneous.entities.feature_request_entity import FeatureRequest
from apps.app.utils.repositories.base_repository import BaseRepository
from apps.app.modules.miscellaneous.entities.feature_request_entity import FeatureRequestStatusEnum
from apps.app.modules.miscellaneous.entities.feature_request_entity import FeatureRequestPriorityEnum
from apps.app.utils import log_exception_with_traceback
import sqlalchemy as sa
from datetime import datetime

class FeatureRequestRepository(BaseRepository[FeatureRequest]):
  def __init__(self, db: Session):
    super().__init__(db, FeatureRequest)

  def get_paginated_feature_requests(
    self,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    sort_field: str = "request_title",
    sort_direction: str = "asc",
    request_status: FeatureRequestStatusEnum | None = None,
    request_priority: FeatureRequestPriorityEnum | None = None,
    user_id: int | None = None,
  ) -> list[FeatureRequest]:
    query = self.db.query(FeatureRequest)
    if user_id:
      query = query.filter(FeatureRequest.created_by_user_id == user_id)
    if keyword:
      keyword = keyword.lower()
      query = query.filter(sa.func.lower(FeatureRequest.request_title).like(f"%{keyword}%") | sa.func.lower(FeatureRequest.request_id).like(f"%{keyword}%"))
    if request_status is not None:
      query = query.filter(FeatureRequest.request_status == request_status)
    if request_priority is not None:
      query = query.filter(FeatureRequest.request_priority == request_priority)
    if sort_field and sort_direction:
      query = query.order_by(getattr(FeatureRequest, sort_field).asc() if sort_direction == "asc" else getattr(FeatureRequest, sort_field).desc())
    if page and page_size:
      query = query.offset((page - 1) * page_size).limit(page_size)
    feature_requests = query.all()
    count = query.count()
    return feature_requests, count

  def get_feature_request_count(self, request_status: FeatureRequestStatusEnum | None = None) -> int:
    try:
      query = self.db.query(FeatureRequest)
      if request_status is not None:
        query = query.filter(FeatureRequest.request_status == request_status)
      count = query.count()
      return count
    except Exception as e:
      log_exception_with_traceback(e, context="Feature request count retrieval failed")
      raise e
  
  def get_total_feature_requests_this_year(self) -> int:
    try:
      query = self.db.query(FeatureRequest)
      query = query.filter(sa.extract('year', FeatureRequest.created_at) == datetime.now().year)
      count = query.count()
      return count
    except Exception as e:
      log_exception_with_traceback(e, context="Feature request count retrieval failed")
      raise e
