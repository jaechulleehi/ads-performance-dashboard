"""광고 성과 대시보드: 채널 데이터 + AppsFlyer(MMP) 일별 조인.

실행: streamlit run app.py
폴더에 YYYY-MM-DD_channel.csv / YYYY-MM-DD_appsflyer.csv 가 추가되면
새로고침(또는 사이드바 버튼)만으로 반영됩니다.
"""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import pipeline as pl

DEFAULT_DIR = str(Path(__file__).resolve().parent)
# Streamlit Community Cloud mounts the repo under /mount/src. A public viewer must not be able to browse server paths.
IS_CLOUD = DEFAULT_DIR.startswith("/mount/src")

BASIS = {
    "채널 기준": {"가입": "회원가입", "구매": "구매", "매출": "구매매출", "ROAS": "ROAS", "CPA": "CPA"},
    "AF 기준": {"가입": "AF회원가입", "구매": "AF구매", "매출": "AF구매매출", "ROAS": "AF_ROAS", "CPA": "AF_CPA"},
}
CH_COLORS = {"구글": "#4C78A8", "메타": "#B279A2", "네이버": "#54A24B"}
LEVELS = {"캠페인": ["채널", "캠페인"], "그룹": ["채널", "캠페인", "그룹"]}
CREATIVE_BY = ["채널", "캠페인", "그룹", "소재"]

st.set_page_config(page_title="광고 성과 대시보드", page_icon=":material/monitoring:", layout="wide")


# ---------- data ----------
@st.cache_data(show_spinner="데이터 불러오는 중...")
def load(folder: str, signature: tuple) -> tuple[pd.DataFrame, list[dict]]:
    """`signature` is only a cache key: new/changed files invalidate the cache."""
    return pl.load_joined(folder)


def view(summary: pd.DataFrame, by: list[str], basis: dict[str, str]) -> pd.DataFrame:
    """Standardise column names for the chosen attribution basis."""
    out = summary[by].copy() if by else pd.DataFrame(index=summary.index)
    return out.assign(
        비용=summary["비용"], 노출=summary["노출"], 클릭=summary["클릭"],
        가입=summary[basis["가입"]], 구매=summary[basis["구매"]], 매출=summary[basis["매출"]],
        ROAS=summary[basis["ROAS"]], CPA=summary[basis["CPA"]],
        CTR=summary["CTR"], CPC=summary["CPC"],
    )


def fmt(value: float, unit: str = "") -> str:
    return "-" if pd.isna(value) else f"{value:,.0f}{unit}"


def ch_scale() -> alt.Scale:
    return alt.Scale(domain=list(CH_COLORS), range=list(CH_COLORS.values()))


# ---------- sidebar ----------
def sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.header("설정")
        folder = st.text_input("데이터 폴더", DEFAULT_DIR, disabled=IS_CLOUD,
                               help="YYYY-MM-DD_channel.csv / _appsflyer.csv 가 있는 폴더")
        if st.button("새로고침", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        basis = st.segmented_control("성과 기준", list(BASIS), default="AF 기준",
                                     help="가입·구매·매출·ROAS·CPA를 어느 쪽 수치로 볼지. 비용은 항상 채널 파일 기준")
    return folder, basis or "AF 기준"


def filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.divider()
        lo, hi = df["일"].min().date(), df["일"].max().date()
        picked = st.date_input("기간", (lo, hi), min_value=lo, max_value=hi)
        start, end = (picked[0], picked[-1]) if isinstance(picked, (list, tuple)) and picked else (lo, hi)
        channels = st.multiselect("매체", sorted(df["채널"].unique()), default=sorted(df["채널"].unique()))
        purposes = st.multiselect("캠페인 목적", sorted(df["캠페인목적"].unique()), default=sorted(df["캠페인목적"].unique()))
    mask = df["일"].dt.date.between(start, end) & df["채널"].isin(channels) & df["캠페인목적"].isin(purposes)
    return df[mask]


# ---------- sections ----------
def kpi_row(f: pd.DataFrame, basis: dict[str, str], basis_name: str) -> None:
    total = view(pl.summarize(f, []), [], basis).iloc[0]
    daily = view(pl.summarize(f, ["일"]), ["일"], basis).sort_values("일")
    spark = (lambda col: daily[col].fillna(0).tolist()) if len(daily) > 1 else (lambda col: None)
    cards = [
        ("광고비", fmt(total["비용"], "원"), "비용", "bar"),
        (f"매출 ({basis_name[:2]})", fmt(total["매출"], "원"), "매출", "bar"),
        ("ROAS", fmt(total["ROAS"], "%"), "ROAS", "line"),
        ("구매 CPA", fmt(total["CPA"], "원"), "CPA", "line"),
        ("구매", fmt(total["구매"], "건"), "구매", "bar"),
        ("회원가입", fmt(total["가입"], "건"), "가입", "bar"),
    ]
    with st.container(horizontal=True):
        for label, value, col, kind in cards:
            data = spark(col)
            if data:
                st.metric(label, value, border=True, chart_data=data, chart_type=kind)
            else:
                st.metric(label, value, border=True)


X_DAY = alt.X("일:T", title="일자", axis=alt.Axis(format="%m/%d"))


def tab_summary(f: pd.DataFrame, basis: dict[str, str], basis_name: str) -> None:
    kpi_row(f, basis, basis_name)
    daily = view(pl.summarize(f, ["일"]), ["일"], basis)
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("일별 광고비 · 매출")
        long = daily.melt("일", ["비용", "매출"], var_name="지표", value_name="금액")
        st.altair_chart(
            alt.Chart(long).mark_line(point=True).encode(
                x=X_DAY, y=alt.Y("금액:Q", title="금액(원)"),
                color=alt.Color("지표:N", title=None), tooltip=["일:T", "지표:N", alt.Tooltip("금액:Q", format=",.0f")],
            ), width="stretch")
    with right, st.container(border=True):
        st.subheader("일별 ROAS · 구매 CPA")
        st.altair_chart(
            alt.layer(
                alt.Chart(daily).mark_line(point=True, color="#54A24B").encode(
                    x=X_DAY, y=alt.Y("ROAS:Q", title="ROAS(%)", scale=alt.Scale(zero=False)),
                    tooltip=["일:T", alt.Tooltip("ROAS:Q", format=",.0f")]),
                alt.Chart(daily).mark_line(point=True, color="#E45756").encode(
                    x=X_DAY, y=alt.Y("CPA:Q", title="구매 CPA(원)", scale=alt.Scale(zero=False)),
                    tooltip=["일:T", alt.Tooltip("CPA:Q", format=",.0f")]),
            ).resolve_scale(y="independent"), width="stretch")


def tab_media(f: pd.DataFrame, basis: dict[str, str]) -> None:
    by_ch_day = view(pl.summarize(f, ["일", "채널"]), ["일", "채널"], basis)
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("매체별 광고비")
        st.altair_chart(
            alt.Chart(by_ch_day).mark_bar().encode(
                x=X_DAY, y=alt.Y("비용:Q", title="광고비(원)"),
                color=alt.Color("채널:N", scale=ch_scale(), title=None),
                tooltip=["일:T", "채널:N", alt.Tooltip("비용:Q", format=",.0f")],
            ), width="stretch")
    with right, st.container(border=True):
        st.subheader("매체별 ROAS (로그 스케일)")
        st.altair_chart(
            alt.Chart(by_ch_day).mark_line(point=True).encode(
                x=X_DAY, y=alt.Y("ROAS:Q", title="ROAS(%)", scale=alt.Scale(type="log")),
                color=alt.Color("채널:N", scale=ch_scale(), title=None),
                tooltip=["일:T", "채널:N", alt.Tooltip("ROAS:Q", format=",.0f")],
            ), width="stretch")
    with st.container(border=True):
        st.subheader("매체별 성과")
        tbl = view(pl.summarize(f, ["채널"]), ["채널"], basis).sort_values("비용", ascending=False)
        st.dataframe(tbl, hide_index=True, width="stretch", column_config=perf_columns())


def perf_columns() -> dict:
    money = st.column_config.NumberColumn(format="localized")
    return {
        "비용": st.column_config.NumberColumn("광고비", format="localized"),
        "노출": money, "클릭": money, "가입": money, "구매": money, "매출": money,
        "ROAS": st.column_config.NumberColumn("ROAS", format="%.0f%%"),
        "CPA": st.column_config.NumberColumn("구매 CPA", format="localized"),
        "CTR": st.column_config.NumberColumn("CTR", format="%.2f%%"),
        "CPC": st.column_config.NumberColumn("CPC", format="localized"),
    }


def roas_bar_columns(tbl: pd.DataFrame) -> dict:
    top = tbl["ROAS"].max(skipna=True)
    top = float(top) if pd.notna(top) and top > 0 else 1.0
    return {**perf_columns(), "ROAS": st.column_config.ProgressColumn("ROAS", format="%.0f%%", min_value=0, max_value=top)}


def tab_campaign(f: pd.DataFrame, basis: dict[str, str]) -> None:
    level = st.segmented_control("집계 단위", list(LEVELS), default="캠페인") or "캠페인"
    by = LEVELS[level]
    tbl = view(pl.summarize(f, by), by, basis).sort_values("비용", ascending=False)
    with st.container(border=True):
        st.subheader(f"{level}별 성과")
        st.dataframe(tbl, hide_index=True, width="stretch", column_config=roas_bar_columns(tbl))


def tab_creative(f: pd.DataFrame, basis: dict[str, str]) -> None:
    by = CREATIVE_BY
    tbl = view(pl.summarize(f, by), by, basis)
    ranked = tbl[tbl["비용"] > 0]
    top, bottom = st.columns(2)
    keep = ["채널", "캠페인", "그룹", "소재", "비용", "ROAS", "CPA"]
    for col, title, data in ((top, "ROAS 상위 5 소재", ranked.nlargest(5, "ROAS")),
                             (bottom, "ROAS 하위 5 소재", ranked.nsmallest(5, "ROAS"))):
        with col, st.container(border=True):
            st.subheader(title)
            st.dataframe(data[keep], hide_index=True, width="stretch", column_config=perf_columns())
    with st.container(border=True):
        st.subheader("소재별 성과")
        st.dataframe(tbl.sort_values("비용", ascending=False), hide_index=True, width="stretch",
                     column_config=roas_bar_columns(tbl))


def tab_af_gap(f: pd.DataFrame) -> None:
    st.caption("AF 수치 ÷ 채널 수치 (100% = 일치). 낮을수록 채널이 AF보다 성과를 크게 잡고 있다는 뜻입니다.")
    by_ch = pl.summarize(f, ["채널"])
    ratio_cols = {"AF클릭비율": "클릭", "AF가입비율": "회원가입", "AF구매비율": "구매", "AF매출비율": "매출"}
    long = by_ch.melt("채널", list(ratio_cols), var_name="지표", value_name="비율").assign(
        지표=lambda d: d["지표"].map(ratio_cols))
    with st.container(border=True):
        st.subheader("매체별 AF/채널 비율")
        st.altair_chart(
            alt.Chart(long).mark_bar().encode(
                x=alt.X("지표:N", sort=list(ratio_cols.values()), title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("비율:Q", title="AF / 채널 (%)"), xOffset="채널:N",
                color=alt.Color("채널:N", scale=ch_scale(), title=None),
                tooltip=["채널:N", "지표:N", alt.Tooltip("비율:Q", format=".1f")],
            ), width="stretch")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("일별 구매 비율")
        daily = pl.summarize(f, ["일", "채널"])
        st.altair_chart(
            alt.Chart(daily).mark_line(point=True).encode(
                x=alt.X("일:T", title="일자", axis=alt.Axis(format="%m/%d")), y=alt.Y("AF구매비율:Q", title="AF/채널 구매(%)", scale=alt.Scale(zero=False)),
                color=alt.Color("채널:N", scale=ch_scale(), title=None),
                tooltip=["일:T", "채널:N", alt.Tooltip("AF구매비율:Q", format=".1f")],
            ), width="stretch")
    with right, st.container(border=True):
        st.subheader("ROAS 비교")
        st.dataframe(by_ch[["채널", "ROAS", "AF_ROAS", "CPA", "AF_CPA"]], hide_index=True, width="stretch", column_config={
            "ROAS": st.column_config.NumberColumn("ROAS(채널)", format="%.0f%%"),
            "AF_ROAS": st.column_config.NumberColumn("ROAS(AF)", format="%.0f%%"),
            "CPA": st.column_config.NumberColumn("CPA(채널)", format="localized"),
            "AF_CPA": st.column_config.NumberColumn("CPA(AF)", format="localized"),
        })


def tab_quality(df: pd.DataFrame, issues: list[dict], folder: str) -> None:
    with st.container(border=True):
        st.subheader("검사 결과")
        if not issues:
            st.success("모든 검사를 통과했습니다.", icon=":material/check_circle:")
        shown = {"error": st.error, "warn": st.warning, "info": st.info}
        for issue in issues:
            shown[issue["level"]](f"**{issue['check']}** · {issue['detail']}")
    with st.container(border=True):
        st.subheader("일자별 파일 · 매칭 현황")
        files = pl.scan_folder(folder)
        rows = []
        for date in sorted(files):
            day = df[df["일"].dt.strftime("%Y-%m-%d") == date]
            rows.append({
                "일자": date,
                "채널 파일": "O" if "channel" in files[date] else "X",
                "AF 파일": "O" if "appsflyer" in files[date] else "X",
                "행 수": len(day),
                "양쪽": int((day["매칭"] == "양쪽").sum()),
                "채널만": int((day["매칭"] == "채널만").sum()),
                "AF만": int((day["매칭"] == "AF만").sum()),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------- main ----------
def main() -> None:
    st.title("광고 성과 대시보드")
    folder, basis_name = sidebar()
    if not Path(folder).is_dir():
        st.error(f"폴더를 찾을 수 없습니다: {folder}")
        return
    df, issues = load(folder, pl.folder_signature(folder))
    if df.empty:
        for issue in issues:
            st.error(f"**{issue['check']}** · {issue['detail']}")
        return
    f = filters(df)
    if f.empty:
        st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
        return
    basis = BASIS[basis_name]
    days = f["일"].dt.date
    st.caption(f"{days.min()} ~ {days.max()} · {days.nunique()}일 · {len(f)}행 · {basis_name}")
    problems = [i for i in issues if i["level"] != "info"]
    if problems:
        st.warning(f"데이터 품질 확인 필요 {len(problems)}건 (‘데이터 품질’ 탭 참고)", icon=":material/warning:")
    t_sum, t_media, t_camp, t_cre, t_af, t_q = st.tabs(["요약", "매체", "캠페인", "소재", "채널 vs AF", "데이터 품질"])
    with t_sum:
        tab_summary(f, basis, basis_name)
    with t_media:
        tab_media(f, basis)
    with t_camp:
        tab_campaign(f, basis)
    with t_cre:
        tab_creative(f, basis)
    with t_af:
        tab_af_gap(f)
    with t_q:
        tab_quality(df, issues, folder)


main()
