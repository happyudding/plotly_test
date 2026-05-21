import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
INPUT_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
DATASETS_DIR = OUTPUT_DIR / "datasets"
UPLOAD_FORM_PATH = ROOT_DIR / "upload_form.html"
SCHOOL_FILES_GLOB = "*_school_updated_call.csv"

META_COLUMNS = ["call", "grade", "class", "student_type"]
N_META_COLUMNS = len(META_COLUMNS)

SUBJECT_NAME_ROW, UNIT_ROW, LO_LIMIT_ROW, HI_LIMIT_ROW = 0, 1, 2, 3
STUDENT_DATA_START_ROW = 6

COLS_PER_ROW = 5

# Base URL of the running Flask server (used for hyperlinks in exported XLSX)
SERVER_BASE_URL = "http://127.0.0.1:5000"
CELL_ASPECT_W, CELL_ASPECT_H = 16, 11

LINE_COLOR = "royalblue"
LIMIT_COLOR = "red"
MARKER_SIZE = 5
LIMIT_LINE_WIDTH = 1
X_RANGE_PADDING_RATIO = 0.15
TITLE_FONT_SIZE = 11

# Report module (/pe/report) ------------------------------------------------
REPORT_DB_PATH = ROOT_DIR / "DB" / "pe" / "report" / "report.db"
REPORT_UPLOAD_DIR = ROOT_DIR / "uploads" / "report"

REPORT_S3_ENDPOINT = os.getenv("REPORT_S3_ENDPOINT", "")
REPORT_S3_BUCKET = os.getenv("REPORT_S3_BUCKET", "")
REPORT_S3_REGION = os.getenv("REPORT_S3_REGION", "us-east-1")
REPORT_S3_ACCESS_KEY = os.getenv("REPORT_S3_ACCESS_KEY", "")
REPORT_S3_SECRET_KEY = os.getenv("REPORT_S3_SECRET_KEY", "")
REPORT_S3_PREFIX       = os.getenv("REPORT_S3_PREFIX",       "pe/report/plotly")
REPORT_S3_CSV_PREFIX   = os.getenv("REPORT_S3_CSV_PREFIX",   "pe/report/origin_csv_files")
REPORT_S3_FAIL_PREFIX  = os.getenv("REPORT_S3_FAIL_PREFIX",  "pe/report/fail_items")
REPORT_S3_ISSUE_PREFIX = os.getenv("REPORT_S3_ISSUE_PREFIX", "pe/report/issue_table")
REPORT_S3_THUMB_PREFIX = os.getenv("REPORT_S3_THUMB_PREFIX", "pe/report/thumbs")

# SVG thumbnail upload concurrency (분석 1회당 2000장 정도 업로드)
REPORT_THUMB_WORKERS   = int(os.getenv("REPORT_THUMB_WORKERS", "8"))

REPORT_LOCK_TTL_SEC = 300
REPORT_LOCK_POLL_SEC = 0.5
REPORT_LOCK_MAX_WAIT_SEC = 60
