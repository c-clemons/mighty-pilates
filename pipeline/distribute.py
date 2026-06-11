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


# Hard-coded production distribution. We do NOT keep this in the config yaml so a
# stray edit can't accidentally route a test run to the client. Switching to
# production requires explicitly passing mode="production" (or --production on
# the CLI).
PRODUCTION_RECIPIENTS = [
    "Cat Martin <cat@mightypilates.com>",
    "Rasa Silverman <rasa@crewfinance.com>",
    "Vy Nguyen <vy@crewfinance.com>",
    "Ashley Palomarez <accounting@mightypilates.com>",
]
PRODUCTION_CC = ["chandler.clemons@gmail.com"]
TEST_RECIPIENTS = ["chandler.clemons@gmail.com"]
TEST_CC = []


def _strip_recipient_addresses(recipients):
    """Pull bare email addresses out of 'Name <addr>' format for SMTP envelope."""
    import re
    out = []
    for r in recipients:
        m = re.search(r"<([^>]+)>", r)
        out.append(m.group(1) if m else r)
    return out


def send_reports(
    files: list,
    subject: str = None,
    body: str = None,
    config_path: str = None,
    mode: str = "test",
):
    """
    Email report files.

    Args:
        files: List of file paths to attach
        subject: Email subject (auto-generated if None)
        body: Email body text (auto-generated if None)
        config_path: Path to config yaml
        mode: 'test' (sends only to chandler.clemons@gmail.com) or
              'production' (sends to the full Crew Finance / Mighty distro).
              Defaults to 'test' so an unqualified call is always safe.
    """
    cfg = _load_email_config(config_path)

    if not cfg.get("sender") or not cfg.get("password"):
        print("Email not configured (sender/password empty in config).")
        print("Files generated locally:")
        for f in files:
            print(f"  {f}")
        return

    if mode == "production":
        recipients = list(PRODUCTION_RECIPIENTS)
        cc        = list(PRODUCTION_CC)
        print(f"[mode=production] To: {len(recipients)} recipients; Cc: {len(cc)}")
    elif mode == "test":
        recipients = list(TEST_RECIPIENTS)
        cc        = list(TEST_CC)
        print(f"[mode=test] To: {recipients}; Cc: {cc}")
    else:
        raise ValueError(f"Unknown mode {mode!r}; expected 'test' or 'production'")

    recipients = [r for r in recipients if r]
    cc         = [r for r in cc         if r]

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

    # From-display preference: use 'from_display' from config if present, else 'sender'.
    # This lets us show 'Chandler Clemons <chandler.clemons@gmail.com>' even though SMTP
    # auth runs as cfg['sender'] (the Google Workspace account that holds the app password).
    from_addr = cfg.get("from_display") or cfg["sender"]
    reply_to  = cfg.get("reply_to")

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
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
    # SMTP envelope recipients must be bare email addresses, not "Name <addr>"
    envelope = _strip_recipient_addresses(recipients + cc)
    server.sendmail(cfg["sender"], envelope, msg.as_string())
    server.quit()

    print(f"Reports emailed to: {', '.join(envelope)}")
