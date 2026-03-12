"""
Email distribution for reports.
"""

import smtplib
import yaml
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from datetime import datetime


def _load_email_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "snowflake_config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("email", {})


def send_reports(
    files: list,
    subject: str = None,
    body: str = None,
    config_path: str = None,
):
    """
    Email report files to configured recipients.

    Args:
        files: List of file paths to attach
        subject: Email subject (auto-generated if None)
        body: Email body text (auto-generated if None)
        config_path: Path to config yaml
    """
    cfg = _load_email_config(config_path)

    if not cfg.get("sender") or not cfg.get("password"):
        print("Email not configured (sender/password empty in config).")
        print("Files generated locally:")
        for f in files:
            print(f"  {f}")
        return

    recipients = cfg.get("recipients", [])
    recipients = [r for r in recipients if r]  # Filter empty strings

    if not recipients:
        print("No recipients configured.")
        return

    if subject is None:
        subject = f"Mighty Pilates - Monthly Reports ({datetime.now().strftime('%B %Y')})"

    if body is None:
        body = f"""Hi,

Please find attached the monthly revenue reports for Mighty Pilates.

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Files attached:
"""
        for f in files:
            body += f"  - {Path(f).name}\n"
        body += "\nBest regards,\nMighty Pilates Revenue System"

    msg = MIMEMultipart()
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for filepath in files:
        part = MIMEBase("application", "octet-stream")
        with open(filepath, "rb") as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={Path(filepath).name}")
        msg.attach(part)

    server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"])
    server.starttls()
    server.login(cfg["sender"], cfg["password"])
    server.sendmail(cfg["sender"], recipients, msg.as_string())
    server.quit()

    print(f"Reports emailed to: {', '.join(recipients)}")
