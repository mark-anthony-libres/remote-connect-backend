from sqlalchemy.orm import Session

from apps.app.modules.app.entities.app_configuration_entity import AppConfiguration


def main(session: Session) -> None:
    app_configurations = [
        AppConfiguration(
            name="feature_request_email_recipient",
            label="Feature Request Email Recipient",
            value="gleen.israel@dte.global",
        ),
    ]

    existing_names = {
        name
        for (name,) in session.query(AppConfiguration.name).filter(
            AppConfiguration.name.in_([configuration.name for configuration in app_configurations])
        )
    }

    missing = [configuration for configuration in app_configurations if configuration.name not in existing_names]

    if missing:
        session.add_all(missing)
