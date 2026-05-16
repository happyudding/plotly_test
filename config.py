from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

INPUT_DIR = ROOT_DIR
SCHOOL_FILES_GLOB = "*_school.csv"

OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_PATH = OUTPUT_DIR / "cumulative.html"
CHART_DATA_PATH = OUTPUT_DIR / "chart_data.json"

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
