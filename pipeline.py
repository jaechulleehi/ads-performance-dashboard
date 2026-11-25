"""Channel + MMP(AppsFlyer) daily CSV pipeline.

Pure functions only (no Streamlit) so they can be unit-tested.
Pipeline: scan folder -> read -> de-duplicate -> outer join -> metrics -> quality issues.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(channel|appsflyer)\.csv$")

MEDIA_MAP: dict[str, str] = {
    "googleadwords_int": "구글",
    "Facebook Ads": "메타",
    "naver_search": "네이버",
}

KEY = ["일", "캠페인", "그룹", "소재"]
CH_TEXT = ["채널", "채널분류", "캠페인목적"]
CH_NUM = ["노출", "클릭", "비용", "회원가입", "구매", "구매매출"]
AF_RENAME = {"클릭": "AF클릭", "회원가입": "AF회원가입", "구매": "AF구매", "구매매출": "AF구매매출"}
AF_NUM = list(AF_RENAME.values())
SUM_COLS = CH_NUM + AF_NUM
COLUMNS = ["일", "채널", "채널분류", "캠페인", "캠페인목적", "그룹", "소재", *SUM_COLS, "매칭"]

Issue = dict[str, str]


def _issue(level: str, check: str, detail: str) -> Issue:
    return {"level": level, "check": check, "detail": detail}


def scan_folder(folder: str | Path) -> dict[str, dict[str, Path]]:
    """Return {date: {"channel": path, "appsflyer": path}} for matching files."""
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(Path(folder).glob("*.csv")):
        m = FILE_RE.match(path.name)
        if m:
            found.setdefault(m.group(1), {})[m.group(2)] = path
    return found


def folder_signature(folder: str | Path) -> tuple[tuple[str, int, int], ...]:
    """Cache key: changes whenever a matching file is added/changed/removed."""
    sig = []
    for kinds in scan_folder(folder).values():
        for path in kinds.values():
            st = path.stat()
            sig.append((path.name, st.st_mtime_ns, st.st_size))
    return tuple(sorted(sig))


def _read(path: Path, file_date: str, issues: list[Issue]) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["일"] = df["일"].astype(str)
    stray = sorted(set(df["일"]) - {file_date})
    if stray:
        issues.append(_issue("warn", "날짜 불일치", f"{path.name}: 파일 날짜와 다른 일자 {', '.join(stray)}"))
    return df


def _collapse(df: pd.DataFrame, num: list[str], source: str, issues: list[Issue]) -> pd.DataFrame:
    """Sum duplicate keys so the join cannot multiply rows."""
    dups = int(df.duplicated(KEY).sum())
    if dups:
        issues.append(_issue("warn", "키 중복", f"{source}: 중복 키 {dups}행을 합산했습니다"))
    other = [c for c in df.columns if c not in KEY and c not in num]
    agg = {**{c: "first" for c in other}, **{c: "sum" for c in num}}
    return df.groupby(KEY, as_index=False, sort=False).agg(agg)


def _empty() -> pd.DataFrame:
    df = pd.DataFrame({c: [] for c in COLUMNS})
    return df.assign(일=pd.to_datetime(df["일"]))


def load_joined(folder: str | Path) -> tuple[pd.DataFrame, list[Issue]]:
    """Load every date in the folder and outer-join channel with AppsFlyer."""
    found = scan_folder(folder)
    issues: list[Issue] = []
    if not found:
        return _empty(), [_issue("error", "파일 없음", f"{folder} 에서 YYYY-MM-DD_channel/appsflyer.csv 를 찾지 못했습니다")]

    ch_parts: list[pd.DataFrame] = []
    af_parts: list[pd.DataFrame] = []
    incomplete: set[str] = set()
    for date, kinds in found.items():
        for kind in ("channel", "appsflyer"):
            if kind not in kinds:
                incomplete.add(date)
                issues.append(_issue("warn", "파일 짝 누락", f"{date}: {kind} 파일이 없습니다"))
        if "channel" in kinds:
            ch_parts.append(_read(kinds["channel"], date, issues))
        if "appsflyer" in kinds:
            af_parts.append(_read(kinds["appsflyer"], date, issues))

    ch = pd.concat(ch_parts, ignore_index=True) if ch_parts else pd.DataFrame(columns=KEY + CH_TEXT + CH_NUM)
    af = pd.concat(af_parts, ignore_index=True) if af_parts else pd.DataFrame(columns=KEY + ["미디어소스", *AF_RENAME])
    ch = _collapse(ch, CH_NUM, "채널", issues)
    af = _collapse(af.rename(columns=AF_RENAME), AF_NUM, "AppsFlyer", issues)

    unknown = sorted(set(af["미디어소스"]) - set(MEDIA_MAP))
    if unknown:
        issues.append(_issue("warn", "미디어소스 미등록", f"MEDIA_MAP에 없는 값: {', '.join(unknown)}"))
    af = af.assign(AF채널=af["미디어소스"].map(MEDIA_MAP).fillna(af["미디어소스"])).drop(columns="미디어소스")

    df = ch.merge(af, on=KEY, how="outer", indicator=True)
    df["매칭"] = df["_merge"].astype(str).map({"both": "양쪽", "left_only": "채널만", "right_only": "AF만"})
    mismatch = df[(df["매칭"] == "양쪽") & (df["채널"] != df["AF채널"])]
    if len(mismatch):
        issues.append(_issue("warn", "매체 불일치", f"채널 파일과 AF의 매체가 다른 행 {len(mismatch)}개"))
    df["채널"] = df["채널"].fillna(df["AF채널"])
    df[["채널분류", "캠페인목적"]] = df[["채널분류", "캠페인목적"]].fillna("미분류")
    df[SUM_COLS] = df[SUM_COLS].fillna(0).astype("int64")
    df["일"] = pd.to_datetime(df["일"])
    df = df[COLUMNS].sort_values(["일", "채널", "캠페인", "그룹", "소재"], ignore_index=True)

    issues.extend(quality_issues(df, incomplete))
    return df, issues


def quality_issues(df: pd.DataFrame, skip_dates: set[str]) -> list[Issue]:
    """Row-level checks. Dates with a missing file are skipped (already reported)."""
    out: list[Issue] = []
    checked = df[~df["일"].dt.strftime("%Y-%m-%d").isin(skip_dates)]
    unmatched = checked[checked["매칭"] != "양쪽"]
    if len(unmatched):
        n_ch = int((unmatched["매칭"] == "채널만").sum())
        n_af = int((unmatched["매칭"] == "AF만").sum())
        out.append(_issue("warn", "조인 매칭 실패", f"채널에만 {n_ch}행, AF에만 {n_af}행 (소재명/캠페인명 확인)"))
    zero_cost = df[(df["비용"] <= 0) & (df["클릭"] > 0)]
    if len(zero_cost):
        out.append(_issue("warn", "비용 0 행", f"클릭은 있는데 비용이 0인 행 {len(zero_cost)}개 (ROAS 계산 불가)"))
    af_over = checked[(checked["매칭"] == "양쪽") & (checked["AF구매"] > checked["구매"])]
    if len(af_over):
        out.append(_issue("info", "AF 구매 > 채널 구매", f"{len(af_over)}행 (어트리뷰션 윈도우/중복 집계 확인)"))
    return out


def _div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.where(b != 0)


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with derived metrics. Ratios are NaN when the denominator is 0."""
    return df.assign(
        ROAS=_div(df["구매매출"], df["비용"]) * 100,
        AF_ROAS=_div(df["AF구매매출"], df["비용"]) * 100,
        CPA=_div(df["비용"], df["구매"]),
        AF_CPA=_div(df["비용"], df["AF구매"]),
        가입CPA=_div(df["비용"], df["회원가입"]),
        AF_가입CPA=_div(df["비용"], df["AF회원가입"]),
        CTR=_div(df["클릭"], df["노출"]) * 100,
        CPC=_div(df["비용"], df["클릭"]),
        CVR=_div(df["구매"], df["클릭"]) * 100,
        AF클릭비율=_div(df["AF클릭"], df["클릭"]) * 100,
        AF가입비율=_div(df["AF회원가입"], df["회원가입"]) * 100,
        AF구매비율=_div(df["AF구매"], df["구매"]) * 100,
        AF매출비율=_div(df["AF구매매출"], df["구매매출"]) * 100,
    )


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Aggregate base columns by `by` (empty list = grand total) and add metrics."""
    if by:
        grouped = df.groupby(by, as_index=False, observed=True)[SUM_COLS].sum()
    else:
        grouped = pd.DataFrame([df[SUM_COLS].sum()])
    return add_metrics(grouped)
