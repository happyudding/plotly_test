import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def _path_env(name, default):
    v = os.getenv(name)
    return Path(v).expanduser().resolve() if v else default


INPUT_DIR = _path_env("PLOTLY_INPUT_DIR", ROOT_DIR / "data")
OUTPUT_DIR = _path_env("PLOTLY_OUTPUT_DIR", ROOT_DIR / "output")
DATASETS_DIR = _path_env("PLOTLY_DATASETS_DIR", OUTPUT_DIR / "datasets")
UPLOAD_FORM_PATH = ROOT_DIR / "server" / "upload_form.html"

# Report module HTML 위치 (report 패키지 안으로 이동됨)
REPORT_ANALYSIS_INDEX_HTML = ROOT_DIR / "report" / "report_analysis_index.html"
REPORT_VIEW_HTML           = ROOT_DIR / "report" / "report_view.html"
SCHOOL_FILES_GLOB = os.getenv("SCHOOL_FILES_GLOB", "*_school_renamed.csv")

META_COLUMNS = ["DUT", "XCoord", "YCoord", "Bin", "Serial"]
N_META_COLUMNS = len(META_COLUMNS)

SUBJECT_NAME_ROW, UNITS_ROW, LOWER_LIMIT_ROW, UPPER_LIMIT_ROW = 0, 1, 2, 3
DATA_START_ROW = 6

COLS_PER_ROW = 5

# Base URL of the running Flask server (used for hyperlinks in exported XLSX).
# HOST/PORT 환경변수가 있으면 자동으로 맞추고, 그 외에는 SERVER_BASE_URL 환경변수로 직접 지정 가능.
_HOST = os.getenv("HOST", "127.0.0.1")
_PORT = os.getenv("PORT", "8000")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", f"http://{_HOST}:{_PORT}")
CELL_ASPECT_W, CELL_ASPECT_H = 16, 11

LINE_COLOR = "royalblue"
LIMIT_COLOR = "red"
MARKER_SIZE = 5
LIMIT_LINE_WIDTH = 1
X_RANGE_PADDING_RATIO = 0.15
TITLE_FONT_SIZE = 11

# Report module (/pe/report) ------------------------------------------------
REPORT_DB_PATH = _path_env("REPORT_DB_PATH", ROOT_DIR / "DB" / "pe" / "report" / "report.db")
REPORT_UPLOAD_DIR = _path_env("REPORT_UPLOAD_DIR", ROOT_DIR / "uploads" / "report")

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

# boto3 S3 client HTTP connection pool 크기.
# 기본 10 은 너무 작아 동시 분석 다수가 PUT/GET 시 풀에서 줄서기 발생.
# 동시 사용자 10명 × thumb_workers 8 = 80 동시 요청 가능 → 30~50 권장.
REPORT_S3_MAX_POOL_CONNECTIONS = int(os.getenv("REPORT_S3_MAX_POOL_CONNECTIONS", "30"))

REPORT_LOCK_TTL_SEC = 300
REPORT_LOCK_POLL_SEC = 0.5
REPORT_LOCK_MAX_WAIT_SEC = 60
