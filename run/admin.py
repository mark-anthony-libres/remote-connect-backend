import getpass
import sys

from apps.app.core.settings import settings
from apps.app.modules.monitor.services.monitor_session_service import generate_and_email_monitor_link
from apps.app.utils.logger import Logger


def print_main_usage() -> None:
    Logger.info("Usage: python -m run.admin generate")
    Logger.info("  Mints a one-time task-monitor access link, emails it to")
    Logger.info(f"  {settings.mail_default_to}, and prints it here too.")
    Logger.info("  The link itself is single-use: the first browser tab (or curl call)")
    Logger.info("  to open it exchanges it for a session, permanently killing the raw")
    Logger.info("  link - it's worthless afterward even if it leaks via browser history,")
    Logger.info("  a forwarded email, or a screenshot. The resulting session then lasts")
    Logger.info(f"  until it's idle for {settings.monitor_token_idle_timeout_seconds // 60} minutes with no requests, or hits its")
    Logger.info(f"  {settings.monitor_token_ttl_seconds // 60}-minute absolute lifetime, whichever comes first.")


def generate() -> None:
    if not settings.monitor_enabled:
        Logger.error("Task monitoring is disabled (MONITOR_ENABLED=false) - not generating a link.")
        sys.exit(1)

    result = generate_and_email_monitor_link(requested_by=getpass.getuser())
    idle_minutes = settings.monitor_token_idle_timeout_seconds // 60

    Logger.section("Task monitor access token")
    Logger.success(f"token         {result['token']}")
    Logger.info(f"max lifetime  {result['expires_in_seconds'] // 60} minutes")
    Logger.info(f"idle timeout  revoked after {idle_minutes} minutes with no requests")
    Logger.info(f"web link      {result['web_link']}")
    Logger.info(f"api curl      {result['curl_command']}")
    Logger.info(f"emailed to    {settings.mail_default_to}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "generate":
        print_main_usage()
        sys.exit(1)

    generate()


if __name__ == "__main__":
    main()
