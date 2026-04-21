import hubspot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate
from hubspot.crm.contacts.exceptions import ApiException
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("HUBSPOT_TOKEN")
if not token:
    print("ERROR: HUBSPOT_TOKEN not found in .env")
    exit(1)

print(f"Token loaded: {token[:20]}...")

client = hubspot.Client.create(access_token=token)

try:
    contact = SimplePublicObjectInputForCreate(
        properties={
            "firstname": "Turing",
            "lastname":  "Signal",
            "email":     "cto@turingsignal.com",
            "company":   "Turing Signal",
            "jobtitle":  "VP Engineering",
        }
    )

    response = client.crm.contacts.basic_api.create(
        simple_public_object_input_for_create=contact
    )
    print(f"Contact ID: {response.id}")
    print(f"HubSpot is alive.")

except ApiException as e:
    if "already exists" in str(e.body):
        print(f"Contact already exists — HubSpot is alive.")
    else:
        print(f"Error: {e.status} - {e.reason}")
        print(f"Body: {e.body}")