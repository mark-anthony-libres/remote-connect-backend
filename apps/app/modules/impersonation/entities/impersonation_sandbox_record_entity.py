import sqlalchemy as sa

from apps.app.utils.decorators.entity import Entity
from database.entities.base import BaseModel


@Entity()
class ImpersonationSandboxRecord(BaseModel):
    __tablename__ = "tblm_impersonation_sandbox_records"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.Text, nullable=False, unique=True)
    value = sa.Column(sa.Integer, nullable=False, server_default=sa.text("0"))
