from sqlalchemy.orm import Session

from apps.app.modules.app.entities.app_configuration_entity import AppConfiguration
from apps.app.utils.repositories.base_repository import BaseRepository
from apps.app.core.db import session_factory
from apps.app.utils import log_exception_with_traceback

class AppConfigurationRepository(BaseRepository[AppConfiguration]):
  def __init__(self, db: Session | None = None):
    super().__init__(db or session_factory(), AppConfiguration)

  def get_configuration_by_name(self, name: str) -> AppConfiguration | None:
    try:
      configuration = self.db.query(AppConfiguration).filter(AppConfiguration.name == name).first()
      if configuration:
        return configuration
      else:
        raise Exception(f"App configuration with name {name} not found")
    except Exception as e:
      log_exception_with_traceback(e)
      raise e
