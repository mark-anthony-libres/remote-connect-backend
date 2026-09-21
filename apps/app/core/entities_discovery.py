import glob
import importlib
import os
from pathlib import Path

from apps.app.utils import get_model_globs


class EntitiesAutoDiscovery:
    def iter_entity_module_names(self):
        for pattern in get_model_globs():
            for folder in glob.glob(pattern, recursive=True):
                if not os.path.isdir(folder) or folder.endswith("__pycache__"):
                    continue

                package_name = os.path.relpath(folder, os.getcwd()).replace(os.sep, ".")

                for entity_file in Path(folder).glob("*.py"):
                    if entity_file.stem in ("base", "__init__"):
                        continue
                    yield f"{package_name}.{entity_file.stem}"

    def import_entity_modules(self):
        for module_name in self.iter_entity_module_names():
            importlib.import_module(module_name)
