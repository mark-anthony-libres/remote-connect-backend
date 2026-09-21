from datetime import datetime, UTC

from sqlalchemy.orm import Session

from apps.app.modules.device.entities.device_entity import DeviceEntity
from apps.app.utils.repositories.base_repository import BaseRepository


class DeviceRepository(BaseRepository[DeviceEntity]):

    def __init__(self, db: Session):
        super().__init__(db, DeviceEntity)

    def get_by_device_code(self, device_code: str) -> DeviceEntity | None:
        return self.db.query(DeviceEntity).filter(DeviceEntity.device_code == device_code).first()

    def get_by_install_key(self, install_key: str) -> DeviceEntity | None:
        return self.db.query(DeviceEntity).filter(DeviceEntity.install_key == install_key).first()

    def create_device(self, device_code: str, install_key: str, device_name: str | None = None) -> DeviceEntity:
        device = DeviceEntity(
            device_code=device_code,
            install_key=install_key,
            device_name=device_name,
            last_seen_at=datetime.now(UTC),
        )
        return self.create(device)

    def touch_last_seen(self, device: DeviceEntity) -> DeviceEntity:
        device.last_seen_at = datetime.now(UTC)
        return self.update(device)
