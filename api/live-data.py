import json             # Imports the JSON library to parse incoming ESP32 data and format API responses.
import os               # Imports the OS library to securely access Vercel environment variables.
import base64           # Imports Base64 to decode the hidden Google Service Account credentials.
import math             # Imports the Math module for advanced calculations (if needed for curve fitting).
from http.server import BaseHTTPRequestHandler  # Imports the base class required by Vercel to handle HTTP web requests.
from urllib.parse import parse_qs, urlparse     # Imports URL parsing tools to read query parameters like '?mode=history'.
from google.oauth2.service_account import Credentials # Imports Google's specific auth class for server-to-server communication.
from googleapiclient.discovery import build     # Imports the build function to construct the Google Sheets API client.

# Global variables defining the exact Google Sheet and tab the database will use.
SPREADSHEET_ID = "1KvZnspQHukVp-nqAAA1URXRMGB7MrJMCe7D7CIqnu7I" # The unique ID extracted from your Google Sheets URL.
SHEET_NAME = "Sheet1" # The specific tab name inside the spreadsheet where rows will be appended.

# --- Google Authentication Function ---
def get_sheets_service():
    # Defines the specific API permissions required; in this case, full read/write access to Google Sheets.
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # Attempts to retrieve the Base64-encoded credentials string from Vercel's environment variables.
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64")
    
    if creds_b64: # Executes if the Base64 environment variable was successfully found.
        try:
            # Strips whitespace, decodes the Base64 string into bytes, and translates it back into a UTF-8 JSON string.
            creds_json = base64.b64decode(creds_b64.strip()).decode("utf-8")
            # Parses the raw JSON string into a structured Python dictionary.
            info = json.loads(creds_json)
            # Generates an OAuth2 credential object using the dictionary and the required scopes.
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            # If any step of the decoding process fails, it halts execution and raises a descriptive error.
            raise Exception(f"GOOGLE_CREDENTIALS_B64 decode failed: {str(e)}")

    else: # Fallback block executed if the Base64 variable is missing.
        # Attempts to look for a raw, unencoded JSON environment variable instead.
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            try:
                # Parses the raw JSON string into a Python dictionary.
                info = json.loads(creds_json)
                # Fixes a common Vercel bug where actual newline characters in private keys are escaped as literal '\n' text.
                if "private_key" in info:
                    info["private_key"] = info["private_key"].replace("\\n", "\n")
                # Generates the credential object using the corrected dictionary.
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            except json.JSONDecodeError as e:
                # Raises an error specifically if the environment variable contains malformed JSON text.
                raise Exception(f"GOOGLE_CREDENTIALS is not valid JSON. Use GOOGLE_CREDENTIALS_B64 instead. Error: {str(e)}")
            except Exception as e:
                # Catches and raises any other general authentication errors.
                raise Exception(f"GOOGLE_CREDENTIALS auth failed: {str(e)}")
        else:
            # Halts execution if neither the Base64 nor the raw JSON environment variables exist.
            raise Exception("No credentials found. Set GOOGLE_CREDENTIALS_B64 in Vercel environment variables.")

    # Constructs and returns the final Google Sheets API client object, disabling cache_discovery for read-only cloud environments.
    return build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()


# --- Helper Functions for Data Safety ---
def safe_float(val, default=0.0):
    """Safely converts empty cells or broken text into a float (decimal)."""
    try:
        if val in ("", None): # Checks if the provided value is empty or completely null.
            return default    # Returns the 0.0 fallback if it is empty.
        return float(val)     # Attempts to cast the value into a floating-point number.
    except (ValueError, TypeError):
        return default        # Returns the 0.0 fallback if the value was text (like a header) instead of a number.

def safe_int(val, default=0):
    """Safely converts empty cells or broken text into an integer."""
    try:
        if val in ("", None): # Checks if the provided value is empty or completely null.
            return default    # Returns the 0 fallback if it is empty.
        # First converts to a float to handle values like "47.3", then truncates it into a whole integer (47).
        return int(float(val)) 
    except (ValueError, TypeError):
        return default        # Returns the 0 fallback if the conversion mathematically fails.


# --- ADC to PPM Conversion Functions ---
def mq135_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0.0            # Returns 0 PPM immediately if the hardware sends an impossibly low ADC count.
    if raw_adc >= 4090:
        return 1000.0         # Imposes a ceiling of 1000 PPM to prevent extreme mathematical spikes at max ADC.
    
    # Converts the raw 12-bit ADC value (0-4095) into an equivalent voltage based on a 3.3V logic level.
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage >= 3.25:
        return 1000.0         # Returns the max 1000 PPM if voltage indicates max saturation.
    
    # Calculates the sensor resistance (Rs) using a voltage divider formula against a 1.0 kΩ load resistor.
    rs = ((3.3 - voltage) / voltage) * 1.0  
    r0 = 20.0                 # Sets the clean-air baseline resistance constant for the MQ-135.
    ratio = rs / r0           # Calculates the ratio between current resistance and baseline clean-air resistance.
    
    if ratio <= 0.05:
        return 1000.0         # Triggers max PPM if the ratio is critically low (heavy gas presence).
        
    # Applies the power-law curve (A * ratio^B) derived from the sensor's datasheet to find actual PPM.
    ppm = 110.47 * (ratio ** -2.862)
    # Bounds the final PPM between 0.0 and 1000.0, rounding it to 1 decimal place for clean data logging.
    return round(max(0.0, min(ppm, 1000.0)), 1)


def mq2_adc_to_ppm(raw_adc):
    if raw_adc <= 0:
        return 0.0            # Returns 0 PPM immediately if the hardware sends an impossibly low ADC count.
    if raw_adc >= 4090:
        return 1000.0         # Imposes a 1000 PPM safety ceiling for extreme ADC reads.
        
    # Converts the 12-bit ADC value into a 3.3V scale voltage.
    voltage = (raw_adc / 4095.0) * 3.3
    if voltage <= 0.05:
        return 0.0            # Returns 0 PPM if the voltage is near zero, indicating no gas detection.
    if voltage >= 3.25:
        return 1000.0         # Returns max PPM if the voltage is near the 3.3V rail limit.
        
    # Calculates sensor resistance (Rs) against a 20.0 kΩ load resistor specific to this MQ-2 hardware setup.
    rs = ((3.3 - voltage) / voltage) * 20.0
    
    r0 = 12.5                 # Sets the clean-air baseline resistance constant for the MQ-2.
    ratio = rs / r0           # Calculates the Rs/R0 ratio.
    
    if ratio <= 0.01:
        return 1000.0         # Forces max PPM if the ratio hits a near-zero critical threshold.
        
    # Applies the MQ-2 specific datasheet power-law curve to calculate PPM.
    ppm = 613.9 * (ratio ** -2.074)
    # Bounds the PPM between 0.0 and 1000.0, rounding to a single decimal place.
    return round(max(0.0, min(ppm, 1000.0)), 1)


# --- Score & Status Calculation ---
def calculate_air_quality(mq2_ppm, mq135_ppm):
    # Calculates severity percentage by dividing current PPM by realistic thresholds (400 for MQ135), capped at 100%.
    mq135_severity = min((mq135_ppm / 400.0) * 100.0, 100.0)
    # Calculates severity percentage for MQ2 based on a 1000 PPM threshold, capped at 100%.
    mq2_severity = min((mq2_ppm / 1000.0) * 100.0, 100.0)
    
    # Derives an overall quality score out of 100, weighting MQ135 (air quality) at 60% and MQ2 (smoke/gas) at 40%.
    calculated_score = int(100 - ((0.6 * mq135_severity) + (0.4 * mq2_severity)))
    # Ensures the final score remains strictly bounded between 0 and 100.
    score = max(0, min(100, calculated_score))
    
    # Assigns a "GOOD" string status if the computed score is 80 or above.
    if score >= 80:
        status = "GOOD"
    # Assigns a "MODERATE" string status if the computed score is between 50 and 79.
    elif score >= 50:
        status = "MODERATE"
    # Assigns a "POOR" string status if the score falls below 50.
    else:
        status = "POOR"
        
    # Returns both the numerical score and the text status back to the caller.
    return score, status


# --- Main HTTP Request Handler ---
class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Overrides the default logging method to do nothing, keeping Vercel runtime logs clean of standard HTTP noise.
        pass

    def _send_cors_headers(self):
        # Sets CORS headers to allow cross-origin requests, so a dashboard hosted on another domain can fetch this data.
        self.send_header("Access-Control-Allow-Origin", "*")
        # Specifies which HTTP methods are permitted to interact with this backend.
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # Specifies which headers the client is allowed to send in their request.
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, status_code, payload):
        # Sends the initial HTTP status code (e.g., 200 for OK, 500 for Error).
        self.send_response(status_code) 
        # Defines the response content type as JSON so the client knows how to parse it.
        self.send_header("Content-type", "application/json") 
        # Injects the CORS headers into the response.
        self._send_cors_headers() 
        # Finalizes the headers block.
        self.end_headers() 
        # Converts the Python dictionary payload into a JSON string, encodes it to UTF-8 bytes, and transmits it.
        self.wfile.write(json.dumps(payload).encode("utf-8")) 

    def do_OPTIONS(self):
        # Handles CORS preflight requests sent automatically by web browsers before POST/GET requests.
        self.send_response(200)
        # Attaches the CORS headers to confirm the origin is allowed.
        self._send_cors_headers()
        # Closes the headers, completing the OPTIONS response.
        self.end_headers()

    # --- POST ROUTE (ESP32 sends data here) ---
    def do_POST(self):
        try:
            # Reads the 'Content-Length' header to determine exactly how many bytes the ESP32 transmitted.
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                # Triggers an immediate 400 Bad Request error if the ESP32 sent an empty payload.
                self._send_json_response(400, {"status": "error", "message": "Empty request body"})
                return

            # Reads the exact number of bytes specified by Content-Length from the incoming data stream.
            post_data = self.rfile.read(content_length)
            # Decodes the raw bytes into a string and parses it into a Python dictionary.
            data = json.loads(post_data.decode("utf-8"))

            # Extracts the raw 'mq2' and 'mq135' ADC integers sent by the ESP32, defaulting to 0 if missing.
            raw_mq2 = safe_int(data.get("mq2", 0))
            raw_mq135 = safe_int(data.get("mq135", 0))

            # Processes the raw hardware integers through the physics math functions to get physical PPM values.
            mq2_ppm = mq2_adc_to_ppm(raw_mq2)
            mq135_ppm = mq135_adc_to_ppm(raw_mq135)

            # Passes the new PPM floats into the business logic function to generate an air quality score and status text.
            score, status = calculate_air_quality(mq2_ppm, mq135_ppm)

            # Constructs a structured Python list representing a single organized row for the Google Sheet.
            row = [
                data.get("date", ""),       # Column A: Real-time Date
                data.get("time", ""),       # Column B: Real-time Timestamp
                mq2_ppm,                    # Column C: Computed float PPM for MQ-2
                mq135_ppm,                  # Column D: Computed float PPM for MQ-135
                data.get("temperature", 0), # Column E: Temperature from DHT11
                data.get("humidity", 0),    # Column F: Humidity from DHT11
                score,                      # Column G: Calculated overall quality score
                status,                     # Column H: Calculated status string (GOOD/MODERATE/POOR)
            ]

            # Authenticates and opens a connection to the Google Sheets API.
            service = get_sheets_service()
            # Executes the API call to append the newly constructed row array to the bottom of the target sheet.
            service.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:H", # Restricts the append operation to columns A through H.
                valueInputOption="USER_ENTERED", # Tells Google Sheets to interpret the data (like formatting decimals) automatically.
                body={"values": [row]},
            ).execute()

            # Responds to the ESP32 with an HTTP 200 OK to confirm the data was successfully logged in the cloud.
            self._send_json_response(200, {"status": "success", "message": "Data logged"})

        except json.JSONDecodeError:
            # Catches formatting errors and returns HTTP 400 if the ESP32 transmitted corrupt JSON.
            self._send_json_response(400, {"status": "error", "message": "Invalid JSON format"})
        except Exception as e:
            # Acts as a catch-all for any other system failures (e.g., Google API timeouts) and returns a 500 error.
            self._send_json_response(500, {"status": "error", "message": str(e)})

    # --- GET ROUTE (Dashboard requests data from here) ---
    def do_GET(self):
        try:
            # Parses the specific URL path the dashboard used to make the request.
            parsed_url = urlparse(self.path)
            # Extracts the query string parameters (everything after the '?') into a dictionary.
            query_params = parse_qs(parsed_url.query)
            # Looks for a 'mode' parameter, defaulting to 'live' if the dashboard didn't specify one.
            mode = query_params.get("mode", ["live"])[0]

            # Authenticates and establishes a connection to the Google Sheets API.
            service = get_sheets_service()
            # Executes a bulk read command, pulling down all populated rows from Columns A through H.
            result = (
                service.values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:H")
                .execute()
            )
            # Extracts the raw list of row arrays from the Google API response dictionary.
            rows = result.get("values", []) 

            # Checks if the sheet is completely empty or only contains the header row.
            if len(rows) <= 1:
                # If there's no data, returns an empty array for 'history' mode or an empty object for 'live' mode.
                payload = [] if mode == "history" else {}
                self._send_json_response(200, payload)
                return

            # Slices the array to isolate the first row as headers.
            headers = rows[0]
            # Slices the array to store all subsequent rows as the actual data payload.
            data_rows = rows[1:]

            if mode == "history":
                history_list = []
                # Iterates through every single data row pulled from the sheet.
                for r in data_rows:
                    # Google Sheets occasionally trims empty trailing cells; this loop pads the row back to the header length.
                    while len(r) < len(headers):
                        r.append("")
                    # Zips the headers array and the current row array together to create a key-value dictionary.
                    raw = dict(zip(headers, r))
                    # Safely extracts, sanitizes, and structures the data for the frontend dashboard list.
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
                # Transmits the full array of sanitized objects to the dashboard for the history table.
                self._send_json_response(200, history_list)

            else: # Executes if the mode is 'live' (or undefined).
                # Isolates only the very last row in the data_rows array.
                last_row = data_rows[-1]
                # Pads the row with empty strings if trailing cells are missing.
                while len(last_row) < len(headers):
                    last_row.append("")
                # Zips the headers and the last row together to map keys to values.
                raw = dict(zip(headers, last_row))
                # Transmits a single sanitized dictionary object to power the live gauges on the dashboard.
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
            # Catches any fatal errors during the GET process and returns them as a 500 Server Error to the dashboard.
            self._send_json_response(500, {"status": "error", "message": str(e)})