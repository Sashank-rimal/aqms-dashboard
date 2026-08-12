import json
import os
import base64
import math
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "1KvZnspQHukVp-nqAAA1URXRMGB7MrJMCe7D7CIqnu7I"
SHEET_NAME = "Sheet1"


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # Primary method: Base64-encoded credentials (safe for Vercel env vars)
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64")
    if creds_b64:
        try:
            creds_json = base64.b64decode(creds_b64.strip()).decode("utf-8")
            info = json.loads(creds_json)
            # No key rebuilding needed - json.loads already handles \n correctly
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            raise Exception(f"GOOGLE_CREDENTIALS_B64 decode failed: {str(e)}")

    # Fallback: Raw JSON string (handles the \n issue with a simple replace)
    else:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            try:
                info = json.loads(creds_json)
                # Only fix needed: if Vercel stored literal \n instead of real newlines
                if "private_key" in info:
                    info["private_key"] = info["private_key"].replace("\\n", "\n")
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            except json.JSONDecodeError as e:
                raise Exception(
                    f"GOOGLE_CREDENTIALS is not valid JSON. Use GOOGLE_CREDENTIALS_B64 instead. Error: {str(e)}"
                )
            except Exception as e:
                raise Exception(f"GOOGLE_CREDENTIALS auth failed: {str(e)}")
        else:
            raise Exception(
                "No credentials found. Set GOOGLE_CREDENTIALS_B64 in Vercel environment variables. "
                "See project README for setup instructions."
            )

    return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


def safe_float(val, default=0.0):
    """Safely converts spreadsheet values to float."""
    try:
        if val in ("", None):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """Safely converts spreadsheet values to integer."""
    try:
        if val in ("", None):
            return default
        return int(float(val))
    except (ValueError, TypeError):
        return default


# --- NEW: ADC to PPM Conversion Functions ---
def mq135_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0
    # 1. Convert 12-bit ADC (0-4095) to Voltage (3.3V)
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage <= 0.1:
        return 0
    
    # 2. Estimate Sensor Resistance (Rs) assuming 10k Load Resistor
    rs = ((3.3 - voltage) / voltage) * 10.0
    r0 = 10.0  # Clean air baseline resistance estimate
    ratio = rs / r0
    
    # 3. Apply standard power-law PPM curve formula for CO2/Air pollutants
    ppm = 110.47 * (ratio ** -2.862)
    return round(ppm, 1)

def mq2_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage <= 0.1:
        return 0
    rs = ((3.3 - voltage) / voltage) * 10.0
    r0 = 10.0
    ratio = rs / r0
    
    # MQ-2 Smoke/Combustible gas curve formula
    ppm = 613.9 * (ratio ** -2.074)
    return round(ppm, 1)
# --------------------------------------------


class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        """Suppress default HTTP server logs to keep Vercel logs clean."""
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, status_code, payload):
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    # ------------------------------------------------------------------
    # POST: ESP32 uploads sensor data → Google Sheets
    # ------------------------------------------------------------------
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_json_response(400, {"status": "error", "message": "Empty request body"})
                return

            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            # --- NEW: Process raw values through the PPM converters ---
            raw_mq2 = safe_int(data.get("mq2", 0))
            raw_mq135 = safe_int(data.get("mq135", 0))

            mq2_ppm = mq2_adc_to_ppm(raw_mq2)
            mq135_ppm = mq135_adc_to_ppm(raw_mq135)

            row = [
                data.get("date", ""),
                data.get("time", ""),
                mq2_ppm,         # Log converted PPM
                mq135_ppm,       # Log converted PPM
                data.get("temperature", 0),
                data.get("humidity", 0),
                data.get("score", 0),
                data.get("status", "Good"),
            ]
            # ----------------------------------------------------------

            service = get_sheets_service()
            service.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:H",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()

            self._send_json_response(200, {"status": "success", "message": "Data logged"})

        except json.JSONDecodeError:
            self._send_json_response(400, {"status": "error", "message": "Invalid JSON format"})
        except Exception as e:
            self._send_json_response(500, {"status": "error", "message": str(e)})

    # ------------------------------------------------------------------
    # GET: Dashboard (live) or History page
    # ------------------------------------------------------------------
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

            if len(rows) <= 1:
                payload = [] if mode == "history" else {}
                self._send_json_response(200, payload)
                return

            headers = rows[0]
            data_rows = rows[1:]

            if mode == "history":
                history_list = []
                for r in data_rows:
                    while len(r) < len(headers):
                        r.append("")
                    raw = dict(zip(headers, r))
                    history_list.append({
                        "date":        raw.get("date", ""),
                        "time":        raw.get("time", ""),
                        "mq2":         safe_int(raw.get("mq2", 0)),
                        "mq135":       safe_int(raw.get("mq135", 0)),
                        "temperature": safe_float(raw.get("temperature", 0)),
                        "humidity":    safe_float(raw.get("humidity", 0)),
                        "score":       safe_int(raw.get("score", 0)),
                        "status":      raw.get("status", "Good"),
                    })
                self._send_json_response(200, history_list)

            else:
                last_row = data_rows[-1]
                while len(last_row) < len(headers):
                    last_row.append("")
                raw = dict(zip(headers, last_row))
                self._send_json_response(200, {
                    "date":        raw.get("date", ""),
                    "time":        raw.get("time", ""),
                    "mq2":         safe_int(raw.get("mq2", 0)),
                    "mq135":       safe_int(raw.get("mq135", 0)),
                    "temperature": safe_float(raw.get("temperature", 0)),
                    "humidity":    safe_float(raw.get("humidity", 0)),
                    "score":       safe_int(raw.get("score", 0)),
                    "status":      raw.get("status", "Good"),
                })

        except Exception as e:
            self._send_json_response(500, {"status": "error", "message": str(e)})