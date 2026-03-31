Made By Satvik Pandey

# Excel to Zoho CRM — Lead Automation

Automated pipeline that reads leads from an Excel file, validates them, and pushes valid entries to Zoho CRM. Invalid rows are logged and skipped. Uses a **hybrid architecture**: Python handles data processing + validation, while an optional n8n workflow handles API orchestration.

---

## Architecture

```
Excel File ──▶ Python (validate) ──▶ n8n Webhook ──▶ Zoho CRM API
                                   │ (if n8n unavailable)
                                   └──▶ Direct Zoho API call
```

Python reads the spreadsheet, validates every row (email format, phone format, required fields), and then:
1. **Primary path** — POSTs valid leads to an n8n webhook, which processes them through Zoho CRM.
2. **Fallback path** — If n8n is unreachable, the script calls Zoho CRM API directly.

---

## Quick Start

### 1. Prerequisites

- Python 3.9+
- (Optional) [n8n](https://n8n.io) for workflow orchestration

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure credentials

All secrets live in `.env` (already included). Update these values with your own Zoho OAuth tokens:

```
ZOHO_CLIENT_ID=<your_client_id>
ZOHO_CLIENT_SECRET=<your_client_secret>
ZOHO_ACCESS_TOKEN=<your_access_token>
ZOHO_REFRESH_TOKEN=<your_refresh_token>
ZOHO_API_DOMAIN=https://www.zohoapis.in
N8N_WEBHOOK_URL=https://satvik-workspace.app.n8n.cloud/webhook/zoho-leads
```

**Getting Zoho OAuth tokens:**

1. Register a self-client at [Zoho API Console](https://api-console.zoho.in/)
2. Generate a code with scope `ZohoCRM.modules.ALL`
3. Exchange the code for access + refresh tokens via `https://accounts.zoho.in/oauth/v2/token`

The script auto-refreshes the access token when it expires (1 hr lifetime).

### 4. Run

```bash
python main.py
```

Or specify a custom file:

```bash
python main.py my_leads.xlsx
```

---

## n8n Workflow Setup (n8n Cloud)

1. Open your n8n cloud workspace
2. Go to **Workflows → Import from File**
3. Select `n8n_workflow.json`
4. Set the environment variable `ZOHO_ACCESS_TOKEN` in n8n settings
5. Activate the workflow
6. The webhook endpoint becomes `https://satvik-workspace.app.n8n.cloud/webhook/zoho-leads`

The workflow:
- Receives leads via webhook
- Splits the array into individual items
- Processes each one through Zoho CRM API
- Retries failed requests up to 3 times

---

## Zoho CRM API Rate Limits

| Plan       | Limit               |
|------------|----------------------|
| Free       | 5,000 API calls/day  |
| Standard   | 100,000 calls/day    |
| Per minute | 100 requests/min     |
| Per API call | Max 100 records     |

The script adds a **0.5s delay** between requests to stay well under the per-minute cap. If a `429 Too Many Requests` response is received, it waits 60s before retrying.

---

## Excel File Format

All columns are required. Email must be valid format, phone must be 7–15 digits (optional `+` prefix).

---

## Sample Log Output

```
2026-03-31 16:45:01 [INFO] Reading Excel file: sample_leads.xlsx
2026-03-31 16:45:01 [INFO] Valid leads: 6 | Invalid: 1
2026-03-31 16:45:01 [WARNING] 1 invalid row(s) logged to invalid_leads.log
2026-03-31 20:18:17 [INFO] Reading Excel file: sample_leads.xlsx
2026-03-31 20:18:20 [WARNING] 1 invalid row(s) logged to invalid_leads.log
2026-03-31 20:18:20 [INFO] Valid leads: 6 | Invalid: 1
2026-03-31 20:18:23 [INFO] Sent 6 leads to n8n webhook
2026-03-31 20:18:23 [INFO] Leads dispatched to n8n for processing
```

**invalid_leads.log:**
```
Row 8: missing required field 'First_Name'
```

---

## Project Structure

```
├── main.py               # Core automation script
├── n8n_workflow.json     # Importable n8n workflow
├── requirements.txt      # Python dependencies
├── sample_leads.xlsx     # Sample input data
└── Screenshots/          # Test run proof
```