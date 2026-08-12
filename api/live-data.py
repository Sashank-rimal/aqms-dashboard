import json             # Used to parse and format data as JSON
import os               # Used to access Vercel environment variables securely
import base64           # Used to decode the Base64 Google credentials
import math             # Mathematical functions (though mostly using native python math here)
from http.server import BaseHTTPRequestHandler  # Base class to handle HTTP GET/POST requests
from urllib.parse import parse_qs, urlparse     # Used to read query parameters (like ?mode=history)
from google.oauth2.service_account import Credentials # Google Auth library for Service Accounts
from googleapiclient.discovery import build     # Used to build the Google Sheets API service

# Global variables defining which Google Sheet to target
SPREADSHEET_ID = "1KvZnspQHukVp-nqAAA1URXRMGB7MrJMCe7D7CIqnu7I" # Your specific Sheet ID
SHEET_NAME = "Sheet1" # The specific tab inside your Google Sheet

# --- Google Authentication Function ---
def get_sheets_service():
    # Define the scope of access (we need to read and write spreadsheets)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # Try to grab the Base64 encoded credentials from environment variables
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64")
    
    if creds_b64: # If the Base64 variable exists...
        try:
            # Decode the Base64 string back into normal text (JSON)
            creds_json = base64.b64decode(creds_b64.strip()).decode("utf-8")
            # Parse the text into a Python dictionary
            info = json.loads(creds_json)
            # Generate Google credentials from that dictionary
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            # If decoding fails, crash and show the error
            raise Exception(f"GOOGLE_CREDENTIALS_B64 decode failed: {str(e)}")

    else: # Fallback: If Base64 doesn't exist, try looking for raw JSON text
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            try:
                info = json.loads(creds_json)
                # Fix Vercel formatting issue where newlines are literal \n characters
                if "private_key" in info:
                    info["private_key"] = info["private_key"].replace("\\n", "\n")
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            except json.JSONDecodeError as e:
                raise Exception(f"GOOGLE_CREDENTIALS is not valid JSON. Use GOOGLE_CREDENTIALS_B64 instead. Error: {str(e)}")
            except Exception as e:
                raise Exception(f"GOOGLE_CREDENTIALS auth failed: {str(e)}")
        else:
            # If neither variable exists, tell the developer to set them up
            raise Exception("No credentials found. Set GOOGLE_CREDENTIALS_B64 in Vercel environment variables.")

    # Build and return the Google Sheets service object so we can interact with the sheet
    return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


# --- Helper Functions for Data Safety ---
def safe_float(val, default=0.0):
    """Safely converts empty cells or broken text into a float (decimal)."""
    try:
        if val in ("", None): # If cell is empty, return 0.0
            return default
        return float(val)     # Attempt to convert to float
    except (ValueError, TypeError):
        return default        # If it's a word instead of a number, return 0.0

def safe_int(val, default=0):
    """Safely converts empty cells or broken text into an integer."""
    try:
        if val in ("", None):
            return default
        return int(float(val)) # Convert to float first to handle decimals, then to integer
    except (ValueError, TypeError):
        return default


# --- ADC to PPM Conversion Functions ---
# --- ADC to PPM Conversion Functions ---
def mq135_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0.0
    if raw_adc >= 4090:
        return 1000.0  # Max cap
    
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage >= 3.25:
        return 1000.0
    
    # REMOVED the "if voltage <= 0.01:" check entirely!
    # This forces the 1k load resistor circuit to calculate a PPM value no matter how low the voltage drops.
    
    rs = ((3.3 - voltage) / voltage) * 1.0  # R_L = 1.0 (1 kΩ)
    r0 = 20.0  # Custom R_0 baseline
    ratio = rs / r0
    
    if ratio <= 0.05:
        return 1000.0
        
    ppm = 110.47 * (ratio ** -2.862)
    return round(max(0.0, min(ppm, 1000.0)), 1)


def mq2_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0.0
    if raw_adc >= 4090:
        return 1000.0  # Max cap set to 1000 PPM safety ceiling
        
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage <= 0.05:
        return 0.0
    if voltage >= 3.25:
        return 1000.0
        
    # R_L = 20.0 (20 kΩ)
    rs = ((3.3 - voltage) / voltage) * 20.0
    
    # Custom R_0 = 12.5 baseline
    r0 = 12.5  
    ratio = rs / r0
    
    if ratio <= 0.01:
        return 1000.0
        
    ppm = 613.9 * (ratio ** -2.074)
    return round(max(0.0, min(ppm, 1000.0)), 1)


# --- Score & Status Calculation ---
def calculate_air_quality(mq2_ppm, mq135_ppm):
    # Scale severity against realistic operational thresholds rather than maximum limits
    mq135_severity = min((mq135_ppm / 400.0) * 100.0, 100.0)
    mq2_severity = min((mq2_ppm / 1000.0) * 100.0, 100.0)
    
    calculated_score = int(100 - ((0.6 * mq135_severity) + (0.4 * mq2_severity)))
    score = max(0, min(100, calculated_score))
    
    if score >= 80:
        status = "GOOD"
    elif score >= 50:
        status = "MODERATE"
    else:
        status = "POOR"
        
    return score, status



# --- Main HTTP Request Handler ---
class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Prevent the server from printing default logs to keep Vercel dashboard clean
        pass

    def _send_cors_headers(self):
        # CORS headers allow the frontend dashboard (running on a browser) to talk to this backend
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, status_code, payload):
        # Standardizes how we send data back to the browser/ESP32
        self.send_response(status_code) # e.g., 200 OK, 400 Error, 500 Server Error
        self.send_header("Content-type", "application/json") # Tell client we are sending JSON
        self._send_cors_headers() # Attach the CORS rules
        self.end_headers() # Close headers
        self.wfile.write(json.dumps(payload).encode("utf-8")) # Send the actual data body

    def do_OPTIONS(self):
        # Browsers send an "OPTIONS" request before a POST to check CORS rules. We reply OK.
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    # --- POST ROUTE (ESP32 sends data here) ---
    def do_POST(self):
        try:
            # Figure out how much data the ESP32 sent
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                # If nothing was sent, throw an error
                self._send_json_response(400, {"status": "error", "message": "Empty request body"})
                return

            # Read the raw byte data and decode it into a Python Dictionary
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            # Safely extract the raw ADC values sent by the ESP32
            raw_mq2 = safe_int(data.get("mq2", 0))
            raw_mq135 = safe_int(data.get("mq135", 0))

            # Convert those raw ADC values into actual PPM using our functions
            mq2_ppm = mq2_adc_to_ppm(raw_mq2)
            mq135_ppm = mq135_adc_to_ppm(raw_mq135)

            # Calculate the overall score and status using the PPM values
            score, status = calculate_air_quality(mq2_ppm, mq135_ppm)

            # Build an array representing a single row in Google Sheets
            row = [
                data.get("date", ""),       # Column A
                data.get("time", ""),       # Column B
                mq2_ppm,                    # Column C (Computed PPM)
                mq135_ppm,                  # Column D (Computed PPM)
                data.get("temperature", 0), # Column E
                data.get("humidity", 0),    # Column F
                score,                      # Column G (Computed Score)
                status,                     # Column H (Computed Status)
            ]

            # Connect to Google Sheets and append the new row to the bottom
            service = get_sheets_service()
            service.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:H", # Target columns A through H
                valueInputOption="USER_ENTERED", # Interpret data as if a human typed it
                body={"values": [row]},
            ).execute()

            # Tell the ESP32 that the data was successfully saved
            self._send_json_response(200, {"status": "success", "message": "Data logged"})

        except json.JSONDecodeError:
            # Catch error if ESP32 sends malformed JSON
            self._send_json_response(400, {"status": "error", "message": "Invalid JSON format"})
        except Exception as e:
            # Catch all other errors (like Google Sheets API failures)
            self._send_json_response(500, {"status": "error", "message": str(e)})

    # --- GET ROUTE (Dashboard requests data from here) ---
    def do_GET(self):
        try:
            # Look at the URL the dashboard used (e.g., /api/live-data?mode=history)
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            # Check if dashboard wants "history" or "live". Default to "live" if missing.
            mode = query_params.get("mode", ["live"])[0]

            # Ask Google Sheets for all data in Columns A through H
            service = get_sheets_service()
            result = (
                service.values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:H")
                .execute()
            )
            rows = result.get("values", []) # Extract the list of rows

            # If sheet is empty (or only has the header row), return empty data
            if len(rows) <= 1:
                payload = [] if mode == "history" else {}
                self._send_json_response(200, payload)
                return

            # Separate the first row (headers) from the rest of the data
            headers = rows[0]
            data_rows = rows[1:]

            if mode == "history":
                history_list = []
                # Loop through all rows in the sheet
                for r in data_rows:
                    # Pad empty cells at the end of a row if Google Sheets truncated them
                    while len(r) < len(headers):
                        r.append("")
                    # Match headers to values to create a Dictionary (e.g., {"date": "2026-08-10"})
                    raw = dict(zip(headers, r))
                    # Safely format the data and add it to our history list
                    history_list.append({
                        "date":        raw.get("date", ""),
                        "time":        raw.get("time", ""),
                        "mq2":         safe_float(raw.get("mq2", 0)),
                        "mq135":       safe_float(raw.get("mq135", 0)),
                        "temperature": safe_float(raw.get("temperature", 0)),
                        "humidity":    safe_float(raw.get("humidity", 0)),
                        "score":       safe_int(raw.get("score", 0)),
                        "status":      raw.get("status", "Good"),
                    })
                # Send the complete list of history back to the dashboard
                self._send_json_response(200, history_list)

            else: # If mode == "live" (or missing)
                # Grab ONLY the very last row in the sheet
                last_row = data_rows[-1]
                # Pad empty cells if needed
                while len(last_row) < len(headers):
                    last_row.append("")
                # Match headers to values
                raw = dict(zip(headers, last_row))
                # Send a single object containing only the latest data back to the dashboard
                self._send_json_response(200, {
                    "date":        raw.get("date", ""),
                    "time":        raw.get("time", ""),
                    "mq2":         safe_float(raw.get("mq2", 0)),
                    "mq135":       safe_float(raw.get("mq135", 0)),
                    "temperature": safe_float(raw.get("temperature", 0)),
                    "humidity":    safe_float(raw.get("humidity", 0)),
                    "score":       safe_int(raw.get("score", 0)),
                    "status":      raw.get("status", "Good"),
                })

        except Exception as e:
            # Catch and return any errors to the frontend
            self._send_json_response(500, {"status": "error", "message": str(e)})
        # it must work properly