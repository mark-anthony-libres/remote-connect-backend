from database.entities.base import BaseModel

import sqlalchemy as sa

from apps.app.utils.decorators.entity import Entity


@Entity()
class DeviceEntity(BaseModel):
    __tablename__ = "tblm_devices"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    device_code = sa.Column(sa.Text, nullable=False, unique=True)
    install_key = sa.Column(sa.Text, nullable=False, unique=True)
    device_name = sa.Column(sa.Text, nullable=True)
    last_seen_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    # created_at / updated_at inherited from BaseModel — do not redeclare
