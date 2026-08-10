import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "1KvZnspQHukVp-nqAAA1URXRMGB7MrJMCe7D7CIqnu7I"
SHEET_NAME = "Sheet1"


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # 1. Try loading credentials from Vercel Environment Variable
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            raise Exception(
                f"Failed to parse GOOGLE_CREDENTIALS env variable: {str(e)}"
            )
    else:
        # 2. Fallback to local credentials.json file if environment variable is missing
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cred_path = os.path.join(current_dir, "credentials.json")
        if os.path.exists(cred_path):
            creds = Credentials.from_service_account_file(
                cred_path, scopes=scopes
            )
        else:
            raise Exception(
                "GOOGLE_CREDENTIALS environment variable not set and credentials.json file not found."
            )

    # cache_discovery=False prevents the file_cache error on Vercel
    return build(
        "sheets", "v4", credentials=creds, cache_discovery=False
    ).spreadsheets()


def safe_int(val, default=0):
    """Safely converts spreadsheet values to integer without throwing exceptions on empty strings."""
    try:
        if val == "" or val is None:
            return default
        return int(float(val))
    except (ValueError, TypeError):
        return default


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        """Handle CORS preflight requests from frontend JS."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    # -------------------------------------------------------------
    # POST: ESP32 uploads new sensor data -> Google Sheets
    # -------------------------------------------------------------
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            row = [
                data.get("date", ""),
                data.get("time", ""),
                data.get("mq2", 0),
                data.get("mq135", 0),
                data.get("temperature", 0),
                data.get("humidity", 0),
                data.get("score", 0),
                data.get("status", "Good"),
            ]

            service = get_sheets_service()
            service.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:H",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"status": "success", "message": "Data logged"}
                ).encode("utf-8")
            )

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "error", "message": str(e)}).encode(
                    "utf-8"
                )
            )

    # -------------------------------------------------------------
    # GET: Dashboard / History requests
    # -------------------------------------------------------------
    def do_GET(self):
        try:
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            mode = query_params.get("mode", ["live"])[0]

            service = get_sheets_service()
            result = (
                service.values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:H")
                .execute()
            )
            rows = result.get("values", [])

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            if len(rows) <= 1:
                # Return empty payload if spreadsheet is empty
                payload = [] if mode == "history" else {}
                self.wfile.write(json.dumps(payload).encode("utf-8"))
                return

            headers = rows[0]
            data_rows = rows[1:]

            # Mode 1: Return ALL rows for history.js
            if mode == "history":
                history_list = []
                for r in data_rows:
                    while len(r) < len(headers):
                        r.append("")
                    raw_dict = dict(zip(headers, r))
                    history_list.append(
                        {
                            "date": raw_dict.get("date", ""),
                            "time": raw_dict.get("time", ""),
                            "mq2": safe_int(raw_dict.get("mq2", 0)),
                            "mq135": safe_int(raw_dict.get("mq135", 0)),
                            "temperature": safe_int(
                                raw_dict.get("temperature", 0)
                            ),
                            "humidity": safe_int(raw_dict.get("humidity", 0)),
                            "score": safe_int(raw_dict.get("score", 0)),
                            "status": raw_dict.get("status", "Good"),
                        }
                    )
                self.wfile.write(json.dumps(history_list).encode("utf-8"))

            # Mode 2: Default - Return ONLY the LATEST row for script.js
            else:
                last_row = data_rows[-1]
                while len(last_row) < len(headers):
                    last_row.append("")
                raw_dict = dict(zip(headers, last_row))

                latest_data = {
                    "date": raw_dict.get("date", ""),
                    "time": raw_dict.get("time", ""),
                    "mq2": safe_int(raw_dict.get("mq2", 0)),
                    "mq135": safe_int(raw_dict.get("mq135", 0)),
                    "temperature": safe_int(raw_dict.get("temperature", 0)),
                    "humidity": safe_int(raw_dict.get("humidity", 0)),
                    "score": safe_int(raw_dict.get("score", 0)),
                    "status": raw_dict.get("status", "Good"),
                }
                self.wfile.write(json.dumps(latest_data).encode("utf-8"))

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "error", "message": str(e)}).encode(
                    "utf-8"
                )
            )