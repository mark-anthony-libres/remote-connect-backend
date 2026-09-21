from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import glob
from pathlib import Path
from dotenv import load_dotenv
from apps.app.utils import get_model_globs
from sqlalchemy import MetaData
import importlib
import pkgutil
import inspect

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_dotenv()

env_path = Path(__file__).parent.parent.parent / ".env"

from database.entities.base import BaseModel
from apps.app.core.settings import settings

if env_path.exists():
    load_dotenv(env_path)

VALIDATION_DATABASE = context.get_x_argument(as_dictionary=True).get("database")

try:
    db_user = settings.pg_db_user
    db_password = settings.pg_db_password
    db_host = settings.pg_db_host
    db_port = settings.pg_db_port
    db_name = VALIDATION_DATABASE or settings.pg_db_name

    db_url = (
        f"postgresql+psycopg2://"
        f"{db_user}:{db_password}"
        f"@{db_host}:{db_port}"
        f"/{db_name}"
    )

    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

except Exception as e:
    raise RuntimeError(f"Failed to set sqlalchemy.url from environment: {e}") from e

MODEL_GLOBS = get_model_globs()


def path_to_module(path):
    rel_path = os.path.relpath(path, os.getcwd())
    return rel_path.replace(os.sep, ".")


MODEL_PACKAGES = set()
for pattern in MODEL_GLOBS:
    for folder in glob.glob(pattern, recursive=True):
        if os.path.isdir(folder) and not folder.endswith("__pycache__"):
            MODEL_PACKAGES.add(path_to_module(folder))
MODEL_PACKAGES = list(MODEL_PACKAGES)


entity_classes = []

for package_path in MODEL_PACKAGES:
    package = importlib.import_module(package_path)
    for _, module_name, is_package in pkgutil.iter_modules(package.__path__):
        if not is_package and module_name != "base":
            module = importlib.import_module(f"{package_path}.{module_name}")
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ == module.__name__:
                    if getattr(cls, "_is_entity", False):
                        entity_classes.append(cls)


target_metadata = MetaData()
table_class_map = {}

for cls in entity_classes:
    table = getattr(cls, "__table__", None)
    if table is not None:
        table_class_map[table.name] = cls
        new_table = table.tometadata(target_metadata)
        new_table.info = {}
        for col in new_table.columns:
            col.info = {}


def include_object(object, name, type_, reflected, compare_to):
    if type_ != "table":
        return True

    metadata_tables = BaseModel.metadata.tables

    if reflected and name not in metadata_tables:
        return False

    mapped_class = table_class_map.get(name)

    if mapped_class and getattr(mapped_class, "__ignore_migration__", False):
        return False

    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    version_table = config.get_main_option("version_table") or "alembic_version"

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=version_table,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        version_table = config.get_main_option("version_table") or "alembic_version"

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=version_table,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()