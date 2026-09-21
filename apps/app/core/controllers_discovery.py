from pathlib import Path
import importlib

from fastapi import APIRouter
from apps.app.core.settings import settings


class ControllersAutoDiscovery:
    def __init__(self):
        self.router = APIRouter()

        # apps/app/core -> apps/app
        self.app_path = Path(__file__).resolve().parent.parent

        # apps/app/modules
        self.modules_path = self.app_path / "modules"

        # apps.app.modules
        self.base_package = "apps.app.modules"

    def discover(self) -> APIRouter:
        for module_dir in self.modules_path.iterdir():
            if not module_dir.is_dir():
                continue

            controller_dir = module_dir / "controller"
            if not controller_dir.is_dir():
                continue

            for controller_file in controller_dir.glob("*_controller.py"):
                module_name = (
                    f"{self.base_package}."
                    f"{module_dir.name}.controller."
                    f"{controller_file.stem}"
                )

                module = importlib.import_module(module_name)

                child_router = getattr(module, "router", None)
                if child_router is None:
                    continue

                tag = (
                    controller_file.stem
                    .removesuffix("_controller")
                    .replace("_", "-")
                )

                self.router.include_router(
                    child_router,
                    tags=child_router.tags or [tag]
                )

        return self.router


controllers = ControllersAutoDiscovery()