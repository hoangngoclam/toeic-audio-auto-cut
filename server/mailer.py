"""Send result / error emails via Gmail SMTP. No-op-logs when Gmail isn't
configured, so local testing works without an app password.

A failed job sends two mails: an apology to the customer (no traceback — it
tells them nothing, and their quota wasn't charged so they can retry) and the
raw traceback to config.ADMIN_EMAIL, which is how the operator finds out at all."""

import smtplib
from datetime import datetime
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
    _send(to, "Rất tiếc, chưa cắt được file nghe TOEIC của bạn",
          "Chào bạn,\n\n"
          "Chúng tôi xin lỗi vì hệ thống chưa xử lý được file bạn vừa gửi. "
          "Bộ phận kỹ thuật đã nhận được thông báo và đang kiểm tra.\n\n"
          "Lượt của bạn KHÔNG bị tính, bạn có thể gửi lại file bất cứ lúc nào. "
          "Nếu vẫn lỗi, vui lòng kiểm tra file là bản ghi nghe TOEIC đầy đủ "
          "(khoảng 45 phút, 100 câu) ở dạng .mp3.\n\n"
          "Cảm ơn bạn đã thông cảm.\n")


def send_admin_error(job_id, customer_email, original_name, error_text):
    """Tell the operator a job died: whose it was, and the raw traceback."""
    if not config.ADMIN_EMAIL:
        return
    _send(config.ADMIN_EMAIL,
          f"[TOEIC cut] Job lỗi — {original_name}",
          f"Job:       {job_id}\n"
          f"Khách:     {customer_email}\n"
          f"File:      {original_name}\n"
          f"Thời gian: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
          f"Sheet:     dòng của khách đã được đánh dấu 'error'\n\n"
          f"{error_text}")
