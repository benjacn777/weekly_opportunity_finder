import yagmail
import os
from datetime import datetime

def main():
    # read email + password from GitHub secrets (passed via env vars)
    email_user = os.environ.get("EMAIL_USERNAME")
    email_pass = os.environ.get("EMAIL_PASSWORD")
    recipient = email_user  # send to yourself for testing

    # connect to Gmail via yagmail
    yag = yagmail.SMTP(user=email_user, password=email_pass)

    # create test message
    subject = "✅ Weekly Opportunities Test Email"
    body = f"Hi Benja,\n\nThis is a test email sent automatically at {datetime.utcnow()} UTC.\n\nIf you see this, your GitHub Action works!"

    # send the email
    yag.send(to=recipient, subject=subject, contents=body)

    print("Email sent successfully!")

if __name__ == "__main__":
    main()
