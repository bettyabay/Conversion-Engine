import resend
import os
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")

r = resend.Emails.send({
    "from": os.getenv("RESEND_FROM_EMAIL"),
    "to": [os.getenv("RESEND_TO_TEST")],
    "subject": "Conversion Engine — smoke test",
    "html": "<p>Pipeline is alive.</p>"
})

print(f"Message ID: {r['id']}")
print(f"Resend is alive.")