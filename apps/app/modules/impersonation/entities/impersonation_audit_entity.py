import sqlalchemy as sa

from apps.app.utils.decorators.entity import Entity
from database.entities.base import BaseModel


@Entity()
class ImpersonationAudit(BaseModel):

    __tablename__ = "tblm_impersonation_audit"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    impersonation_id = sa.Column(sa.Text, nullable=False, unique=True, index=True)
    admin_user_id = sa.Column(sa.Integer, nullable=False)
    target_user_id = sa.Column(sa.Integer, nullable=False)
    started_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    ended_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    termination_reason = sa.Column(sa.Text, nullable=True)
    status = sa.Column(sa.Text, nullable=False, server_default=sa.text("'active'"))
