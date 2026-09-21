import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from apps.app.core.settings import settings


class EmailUtil:

    @staticmethod
    def send(to, subject, html, attachment_path=None):
        mail_host = settings.mail_host
        mail_user = settings.mail_user
        mail_pass = settings.mail_pass

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = '"CentCom API Reporter" <no-reply@specopsecure.cloud>'
        msg["To"] = ", ".join(to) if isinstance(to, list) else to

        msg.set_content("This email requires an HTML-compatible client.")
        msg.add_alternative(html, subtype="html")

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype="application",
                    subtype="octet-stream",
                    filename=os.path.basename(attachment_path)
                )

        with smtplib.SMTP(mail_host, 587) as server:
            server.starttls()
            server.login(mail_user, mail_pass)
            server.send_message(msg)

    @staticmethod
    def create_template(html_file, data=None):
        data = data or {}

        template_dir = Path(__file__).parent / "templates"

        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

        template = env.get_template(html_file)
        return template.render(**data)