"""Send result / error emails via Gmail SMTP. No-op-logs when Gmail isn't
configured, so local testing works without an app password."""

import smtplib
from email.message import EmailMessage

from server import config


def _send(to, subject, body):
    if not config.EMAIL_ENABLED:
        print(f"[mailer] EMAIL DISABLED — would send to {to}:\n  {subject}\n  {body}")
        return
    msg = EmailMessage()
    msg["From"] = config.GMAIL_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        s.send_message(msg)
    print(f"[mailer] sent to {to}: {subject}")


def send_result(to, link):
    _send(to, "File nghe TOEIC đã cắt xong",
          f"Chào bạn,\n\nFile nghe của bạn đã được cắt thành các clip theo câu hỏi.\n"
          f"Link tải về:\n{link}\n\n(Link mở được cho bất kỳ ai có link.)\n")


def send_error(to):
    _send(to, "Không xử lý được file nghe TOEIC",
          "Chào bạn,\n\nRất tiếc, hệ thống không xử lý được file bạn gửi. "
          "Vui lòng kiểm tra file là bản ghi nghe TOEIC (.mp3) rồi thử lại.\n")
