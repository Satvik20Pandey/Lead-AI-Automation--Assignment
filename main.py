import os
import re
import sys
import time
import logging
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# simple log setup: terminal + run.log file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("run.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

_access_token = os.getenv("ZOHO_ACCESS_TOKEN", "")

INVALID_LOG = "invalid_leads.log"
EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_RE = re.compile(r"^\+?\d{7,15}$")

REQUIRED_COLS = ["First_Name", "Last_Name", "Email", "Phone", "Company", "Lead_Source"]


def refresh_access_token():
    """Refresh Zoho OAuth access token using the refresh token."""
    global _access_token
    # token refresh endpoint
    url = "https://accounts.zoho.in/oauth/v2/token"
    params = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    resp = requests.post(url, params=params, timeout=30)
    data = resp.json()
    if "access_token" in data:
        _access_token = data["access_token"]
        log.info("Access token refreshed successfully")
        return _access_token
    raise RuntimeError(f"Token refresh failed: {data}")


def get_access_token():
    """Return current access token, refresh if empty."""
    global _access_token
    if not _access_token:
        return refresh_access_token()
    return _access_token


def validate_row(row, idx):
    """Validate a single lead row. Returns (is_valid, error_message)."""
    # first check: required fields should not be empty
    for col in REQUIRED_COLS:
        val = row.get(col, "")
        if pd.isna(val) or str(val).strip() == "":
            return False, f"Row {idx}: missing required field '{col}'"

    email = str(row["Email"]).strip()
    # basic email format check
    if not EMAIL_RE.match(email):
        return False, f"Row {idx}: invalid email '{email}'"

    phone = str(row["Phone"]).strip().replace(" ", "")
    # basic phone check: +optional and 7-15 digits
    if not PHONE_RE.match(phone):
        return False, f"Row {idx}: invalid phone '{phone}'"

    return True, ""


def read_and_validate(filepath):
    """Read Excel file and split into valid/invalid leads."""
    log.info(f"Reading Excel file: {filepath}")
    df = pd.read_excel(filepath, engine="openpyxl")
    df.columns = df.columns.str.strip()

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        log.error(f"Missing columns in Excel: {missing}")
        sys.exit(1)

    valid, invalid = [], []
    for idx, row in df.iterrows():
        ok, err = validate_row(row, idx + 2)  # +2 for Excel row numbering
        if ok:
            lead = {col: str(row[col]).strip() for col in REQUIRED_COLS}
            valid.append(lead)
        else:
            invalid.append(err)

    if invalid:
        with open(INVALID_LOG, "w") as f:
            f.write("\n".join(invalid))
        log.warning(f"{len(invalid)} invalid row(s) logged to {INVALID_LOG}")

    log.info(f"Valid leads: {len(valid)} | Invalid: {len(invalid)}")
    return valid


def create_lead_zoho(lead, retry=True):
    """Create a single lead in Zoho CRM via API."""
    url = f"{ZOHO_API_DOMAIN}/crm/v2/Leads"
    headers = {
        "Authorization": f"Zoho-oauthtoken {get_access_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "data": [
            {
                "First_Name": lead["First_Name"],
                "Last_Name": lead["Last_Name"],
                "Email": lead["Email"],
                "Phone": lead["Phone"],
                "Company": lead["Company"],
                "Lead_Source": lead["Lead_Source"],
            }
        ]
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code == 401 and retry:
        log.warning("Access token expired, refreshing...")
        refresh_access_token()
        return create_lead_zoho(lead, retry=False)

    if resp.status_code == 429:
        log.warning("Rate limit hit, waiting 60s...")
        time.sleep(60)
        return create_lead_zoho(lead, retry=retry)

    data = resp.json()
    if resp.status_code in (200, 201):
        record = data.get("data", [{}])[0]
        status = record.get("status", "unknown")
        if status == "success":
            log.info(f"Created lead: {lead['First_Name']} {lead['Last_Name']} (ID: {record['details']['id']})")
            return True
        else:
            log.error(f"Zoho API error for {lead['Email']}: {record.get('message', data)}")
            return False
    else:
        log.error(f"HTTP {resp.status_code} for {lead['Email']}: {resp.text}")
        return False


def send_to_n8n(leads):
    """Send validated leads to n8n webhook for orchestration."""
    if not N8N_WEBHOOK_URL:
        log.info("N8N_WEBHOOK_URL not set, skipping n8n dispatch")
        return False

    try:
        resp = requests.post(N8N_WEBHOOK_URL, json={"leads": leads}, timeout=30)
        if resp.status_code in (200, 201):
            log.info(f"Sent {len(leads)} leads to n8n webhook")
            return True
        log.warning(f"n8n webhook returned {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        log.warning(f"n8n webhook unreachable: {e}")
    return False


def main():
    # by default script reads sample file, else takes cli arg
    filepath = "sample_leads.xlsx"
    if len(sys.argv) > 1:
        filepath = sys.argv[1]

    if not os.path.exists(filepath):
        log.error(f"File not found: {filepath}")
        sys.exit(1)

    leads = read_and_validate(filepath)
    if not leads:
        log.warning("No valid leads to process")
        return

    # first try n8n webhook; if down then fallback to direct Zoho API
    n8n_ok = send_to_n8n(leads)

    if not n8n_ok:
        log.info("Processing leads directly via Zoho CRM API...")
        success, failed = 0, 0
        for lead in leads:
            if create_lead_zoho(lead):
                success += 1
            else:
                failed += 1
            time.sleep(0.5)  

        log.info(f"Done — Created: {success} | Failed: {failed}")
    else:
        log.info("Leads dispatched to n8n for processing")


if __name__ == "__main__":
    main()