from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# CLI / 테스트용 입력 디렉터리 (build.py가 사용)
INPUT_DIR = ROOT_DIR / "data"
SCHOOL_FILES_GLOB = "*_school_updated_call.csv"

# 다중 dataset 저장 위치 (server.py의 /upload가 사용)
OUTPUT_DIR = ROOT_DIR / "output"
DATASETS_DIR = OUTPUT_DIR / "datasets"

# 업로드 폼 정적 HTML
UPLOAD_FORM_PATH = ROOT_DIR / "upload_form.html"

META_COLUMNS = ["call", "grade", "class", "student_type"]
N_META_COLUMNS = len(META_COLUMNS)

SUBJECT_NAME_ROW = 0
UNIT_ROW = 1
LO_LIMIT_ROW = 2
HI_LIMIT_ROW = 3
STUDENT_DATA_START_ROW = 6

COLS_PER_ROW = 5

LINE_COLOR = "royalblue"
LIMIT_COLOR = "red"
MARKER_SIZE = 5
LIMIT_LINE_WIDTH = 1
X_RANGE_PADDING_RATIO = 0.15
TITLE_FONT_SIZE = 11

CELL_ASPECT_W = 16
CELL_ASPECT_H = 11
