from database.entities.base import BaseModel
from sqlalchemy import event
import enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from sqlalchemy.orm import relationship


class FeatureRequestStatusEnum(str, enum.Enum):
	NEW = "New"
	UNDER_REVIEW = "Under Review"
	MORE_INFO_REQUIRED = "More Info Required"
	ADDED_TO_ROADMAP = "Added to Roadmap"
	DECLINED = "Declined"


FEATURE_REQUEST_STATUS_ENUM = sa.Enum(
  FeatureRequestStatusEnum,
  name="feature_request_status",
  values_callable=lambda enum_cls: [member.value for member in enum_cls],
  create_type=True,
)

class FeatureRequestPriorityEnum(str, enum.Enum):
  LOW = "Low"
  MEDIUM = "Medium"
  HIGH = "High"

FEATURE_REQUEST_PRIORITY_ENUM = sa.Enum(
  FeatureRequestPriorityEnum,
  name="feature_request_priority",
  values_callable=lambda enum_cls: [member.value for member in enum_cls],
  create_type=True,
)

@Entity()
class FeatureRequest(BaseModel):
	__tablename__ = "tblm_feature_requests"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	request_id = sa.Column(sa.Text, nullable=False, unique=True)
	request_email = sa.Column(sa.Text, nullable=False)
	request_title = sa.Column(sa.Text, nullable=False)
	request_description = sa.Column(sa.Text, nullable=True)
	request_business_impact = sa.Column(sa.Text, nullable=True)
	request_status = sa.Column(FEATURE_REQUEST_STATUS_ENUM, default=FeatureRequestStatusEnum.NEW)
	request_priority = sa.Column(FEATURE_REQUEST_PRIORITY_ENUM, default=FeatureRequestPriorityEnum.LOW)
	request_notes = sa.Column(sa.Text, nullable=True)

	created_by_user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=False)
	created_by = relationship(
		"User",
		back_populates="created_feature_requests",
		lazy="selectin",
		foreign_keys=[created_by_user_id],
	)

	reviewed_by_user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=True)
	reviewed_by = relationship(
		"User",
		back_populates="reviewed_feature_requests",
		lazy="selectin",
		foreign_keys=[reviewed_by_user_id],
	)

	request_attachments = sa.Column(ARRAY(sa.Text), nullable=True)
