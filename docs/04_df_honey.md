# 04. df_honey 라이브러리 블록

서버/HTTP 흐름 없이 **데이터프레임 1개 또는 여러 개에 대해 동일한 통계 분석을 직접 호출**할 수 있는 단일 객체 래퍼.
`table_builder._build_cpk / _build_yield / _build_fail_items` 가 기대하는 `schools = {name: ExcelData}` 인터페이스를 흉내내어,
report 모듈에서 쓰는 함수들을 노트북/스크립트에서 그대로 재사용하는 것이 목적.

- **파일**: [df_honey.py](../df_honey.py)
- **의존 함수**: [table_builder.py](../table_builder.py), [preprocess.py](../preprocess.py), [data_loader.py](../data_loader.py), [config.py](../config.py)

---

## 1. 입력 데이터 형식 (CSV 구조)

[config.py:11-15](../config.py#L11-L15) 에서 위치 상수 정의.

| 행 번호 | 내용 |
|---------|------|
| 0 | 과목명 (subject names) — meta 4개 이후 |
| 1 | 단위 (units) |
| 2 | LO_LIMIT (하한) |
| 3 | HI_LIMIT (상한) |
| 4 | (사용 안 함, 보통 비움) |
| 5 | (사용 안 함) |
| 6+ | 학생 데이터 — `STUDENT_DATA_START_ROW` |

좌측 4 컬럼은 메타 (`META_COLUMNS = ["call", "grade", "class", "student_type"]`), 5번째 컬럼부터 과목 점수.

> `STUDENT_DATA_START_ROW = 6` 인 점에 주의: 4행/5행은 의도적으로 건너뛴다. df_honey 에 raw df 를 직접 넣을 때 같은 구조여야 한다.

---

## 2. `df_honey` — 단일 파일 단위

### 2.1 생성

```python
from df_honey import df_honey

# CSV / Excel 경로에서
h = df_honey.from_file("data/a_school_updated_call.csv")

# header=None 으로 읽은 raw DataFrame 에서
import pandas as pd
df = pd.read_csv("...", header=None)
h = df_honey.from_df(df, name="a_school")
```

내부 속성:
- `name` (str)
- `subjects: list[str]`, `units: list[str]`
- `lo_limits: list[float|nan]`, `hi_limits: list[float|nan]`
- `scores: pd.DataFrame` (컬럼은 0..N-1 정수 인덱스)
- `meta: pd.DataFrame` (컬럼: call/grade/class/student_type)

`ExcelData` 와 호환되어 `table_builder` 가 `table.subjects / table.scores / ...` 를 그대로 사용할 수 있다.

### 2.2 분석 메서드

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `.cpk(subject_idx=None)` | `list[dict]` | CPK 통계 (subject별). idx 지정 시 해당 과목만 |
| `.yield_rate()` | `list[dict]` | student_type 별 count/portion/Main Fail subject |
| `.fail_items()` | `dict` | yield + fail subject 목록 (UI 표시용) |
| `.fail_values()` | `list[dict]` | 비합격 학생 × 과목별 측정값/lo/hi/fail 방향 (issue table 와 같은 행 단위) |
| `.distribution(subject_idx)` | `(xs, ys)` | 누적분포 numpy arrays |
| `.summary()` | `list[dict]` | `build_summary_rows` 결과 — DB 저장 직전 행들 |

내부적으로 모두 `self._as_schools()` 로 `{self.name: self}` dict 를 만들어 `_build_*` 호출.

---

## 3. `df_honey_group` — 여러 honey 묶음

여러 학교를 비교/통합 분석할 때 사용.

```python
from df_honey import df_honey, df_honey_group

group = df_honey_group([
    df_honey.from_file("a_school.csv"),
    df_honey.from_file("b_school.csv"),
    df_honey.from_file("c_school.csv"),
])

group.cpk()                       # 전체 통합 CPK
group.yield_rate()                # 전체 통합 수율
group.fail_items()                # 전체 통합 fail items
group.summary()                   # 통합 summary rows
group.distribution(idx)           # {name: (xs, ys)} 모든 학교
group.distribution(idx, "a_school")  # ("a_school" 만)
group.compare_cpk()               # subject × source pivot DataFrame
group.names()
len(group)
```

내부는 `self._schools = {name: honey}` dict. report 모듈이 사용하는 schools 구조와 동일.

---

## 4. report 흐름과의 관계

`/pe/report/analyze` 가 내부적으로 하는 일과 거의 같다:

```python
# 서버 분석 흐름 (요약)
schools = {p.stem: load_table(p) for p in csv_paths}
rows = build_summary_rows(schools)
save_summary_batch(...)

# 동등한 df_honey 흐름
group = df_honey_group([df_honey.from_file(p) for p in csv_paths])
rows = group.summary()
# rows 를 그대로 report_db.save_summary_batch 에 넣을 수 있음
```

S3 / DB / 락 / analysis_key 캐시는 모두 service 레이어 (`report_analysis_service`) 가 담당.
df_honey 는 **순수 계산만** — 서버 코드 없이 같은 결과 검증 / 시각화 노트북 등에 적합.

---

## 5. 활용 예시

```python
# 한 학교의 5번 과목 CPK 만
df_honey.from_file("a_school.csv").cpk(subject_idx=5)

# fail 데이터만 빠르게 확인
h = df_honey.from_file("a_school.csv")
print(len(h.fail_values()), "fail records")

# 학교간 CPK 비교 pivot
group.compare_cpk().to_csv("compare_cpk.csv")
```

---

## 6. 주의

- `from_df` 에 넣는 DataFrame 은 반드시 `header=None` 으로 읽어야 한다 (subject row 가 0행이어야 함).
- `subject_idx` 는 항상 0부터 시작하는 정수 (subjects 리스트 인덱스). 과목명이 아님.
- numeric 변환 실패값(`pd.to_numeric(errors='coerce')`)은 분석에서 자동 제외.
- `_fmt_type` 이 정수형 student_type 을 문자열로 정규화 (예: `1.0` → `"1"`). `PASS_STUDENT_TYPE = "1"` 이 합격 기준.
- df_honey 는 **report_object_info, report_session 등 DB 에 어떤 것도 쓰지 않는다.** 순수 메모리 분석.
