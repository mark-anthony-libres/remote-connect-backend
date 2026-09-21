import importlib
import inspect
from pathlib import Path
from apps.app.utils.logger import Logger


class AnalysisJobDiscovery:
    def __init__(self, modules_path: str = "apps/app/modules"):
        self.modules_path = Path(modules_path)

    def iter_analysis_module_names(self):
        for module_directory in self.modules_path.iterdir():
            if not module_directory.is_dir():
                continue

            analysis_directory = module_directory / "analysis"
            if not analysis_directory.exists():
                continue

            for analysis_file in analysis_directory.glob("*_analysis.py"):
                module_name = (
                    analysis_file.with_suffix("")
                    .as_posix()
                    .replace("/", ".")
                )
                yield module_name

    def import_analysis_modules(self):
        for module_name in self.iter_analysis_module_names():
            importlib.import_module(module_name)

    def discover_analysis_jobs(self):
        discovered_analysis_jobs = []
        for module_name in self.iter_analysis_module_names():
            imported_module = importlib.import_module(module_name)

            for _, function_object in inspect.getmembers(imported_module):
                if (
                    inspect.isfunction(function_object)
                    and getattr(function_object, "_is_analysis", False)
                ):
                    discovered_analysis_jobs.append({
                        "job_id": getattr(
                            function_object,
                            "_analysis_job_id",
                            function_object.__name__
                        ),
                        "name": getattr(function_object, "_analysis_name", None),
                        "function": function_object,
                        "module": function_object.__module__,
                    })
        return discovered_analysis_jobs

    def discover_analysis_job(self, job_id: str):
        for analysis_job in self.discover_analysis_jobs():
            if analysis_job["job_id"] == job_id:
                return analysis_job
        return None

    @staticmethod
    def _resolve_target(function_object, via_task: bool):
        if via_task:
            return function_object
        return getattr(function_object, "__wrapped__", function_object)

    @staticmethod
    def _invoke(target, via_task: bool, force: bool):
        if via_task:
            return target(force=force)

        first_param = next(iter(inspect.signature(target).parameters), None)
        if first_param == "self":
            return target(None)
        return target()

    def run_all_analysis_jobs(self, via_task: bool = False, force: bool = False):

        job_list = self.discover_analysis_jobs()

        if not job_list:
            Logger.error(
                "No analysis jobs were discovered. "
                "Make sure analysis modules are imported and decorated with @analysis."
            )
            return

        total_jobs = len(job_list)
        Logger.section(f"Starting analysis execution ({total_jobs} jobs discovered)")

        for index, analysis_job in enumerate(job_list, start=1):
            job_id = analysis_job["job_id"]

            Logger.section(f"[{index}/{total_jobs}] Executing analysis job '{job_id}'")

            try:
                target = self._resolve_target(analysis_job["function"], via_task)
                self._invoke(target, via_task, force)
                Logger.success(f"Analysis job '{job_id}' completed successfully.")
            except Exception as exc:
                Logger.error(f"Analysis job '{job_id}' failed with error: {exc}")
                raise

        Logger.success(f"Finished executing {total_jobs} analysis jobs.")

    def run_analysis_job(self, job_id: str, via_task: bool = False, force: bool = False):
        analysis_job = self.discover_analysis_job(job_id)

        if not analysis_job:
            error_msg = f"Analysis job '{job_id}' was not found."
            Logger.error(error_msg)
            raise ValueError(error_msg)

        Logger.section(f"Running analysis job: {job_id}")

        try:
            target = self._resolve_target(analysis_job["function"], via_task)
            self._invoke(target, via_task, force)
            Logger.success(f"Analysis job '{job_id}' completed successfully.")
        except Exception as exc:
            Logger.error(f"Analysis job '{job_id}' failed with error: {exc}")
            raise