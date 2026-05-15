from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

EXCEL_PATH = ROOT_DIR / "test_data_50subjects_300students_normalized_unique.xlsx"
OUTPUT_PATH = ROOT_DIR / "output" / "cumulative.html"

META_COLUMNS = ["call", "grade", "class", "student_type"]
N_META_COLUMNS = len(META_COLUMNS)

SUBJECT_NAME_ROW = 0
UNIT_ROW = 1
LO_LIMIT_ROW = 2
HI_LIMIT_ROW = 3
STUDENT_DATA_START_ROW = 6

COLS_PER_ROW = 5

LINE_COLOR = "royalblue"
LO_LIMIT_COLOR = "red"
HI_LIMIT_COLOR = "red"
LIMIT_LINE_WIDTH = 1
DATA_LINE_WIDTH = 1.5

SUBPLOT_HEIGHT_PX = 330
ROW_GAP_PX = 60
HORIZONTAL_SPACING = 0.04
X_RANGE_PADDING_RATIO = 0.15
SUBPLOT_TITLE_FONT_SIZE = 11
