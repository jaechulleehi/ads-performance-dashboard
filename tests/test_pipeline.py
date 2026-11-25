import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline as pl  # noqa: E402

CH_HEADER = "일,채널,채널분류,캠페인,캠페인목적,그룹,소재,노출,클릭,비용,회원가입,구매,구매매출\n"
AF_HEADER = "일,미디어소스,캠페인,그룹,소재,클릭,회원가입,구매,구매매출\n"


def write(folder, name, header, rows):
    (folder / name).write_text(header + "".join(r + "\n" for r in rows), encoding="utf-8-sig")


@pytest.fixture
def folder(tmp_path):
    write(tmp_path, "2025-01-01_channel.csv", CH_HEADER, [
        "2025-01-01,구글,외부,GGL_A,플러스가입,논타겟,VID_1,1000,100,10000,10,5,50000",
        "2025-01-01,메타,외부,META_A,신규유저,논타겟,IMG_1,2000,200,20000,4,2,10000",
    ])
    write(tmp_path, "2025-01-01_appsflyer.csv", AF_HEADER, [
        "2025-01-01,googleadwords_int,GGL_A,논타겟,VID_1,90,8,4,40000",
        "2025-01-01,Facebook Ads,META_A,논타겟,IMG_1,180,3,1,5000",
    ])
    return tmp_path


def test_scan_folder_pairs_by_date(folder):
    write(folder, "2025-01-02_channel.csv", CH_HEADER, [])
    found = pl.scan_folder(folder)
    assert set(found) == {"2025-01-01", "2025-01-02"}
    assert set(found["2025-01-01"]) == {"channel", "appsflyer"}
    assert set(found["2025-01-02"]) == {"channel"}


def test_scan_folder_ignores_other_files(folder):
    (folder / "notes.csv").write_text("x")
    (folder / "2025-01-01_other.csv").write_text("x")
    assert set(pl.scan_folder(folder)) == {"2025-01-01"}


def test_signature_changes_when_file_added(folder):
    before = pl.folder_signature(folder)
    write(folder, "2025-01-02_channel.csv", CH_HEADER, [])
    assert pl.folder_signature(folder) != before


def test_load_joins_on_key(folder):
    df, issues = pl.load_joined(folder)
    assert len(df) == 2
    assert set(df["매칭"]) == {"양쪽"}
    g = df[df["채널"] == "구글"].iloc[0]
    assert g["구매매출"] == 50000 and g["AF구매매출"] == 40000
    assert issues == [] or all(i["level"] != "error" for i in issues)


def test_unmatched_rows_are_kept_and_flagged(folder):
    write(folder, "2025-01-01_appsflyer.csv", AF_HEADER, [
        "2025-01-01,googleadwords_int,GGL_A,논타겟,VID_1,90,8,4,40000",
        "2025-01-01,naver_search,NVR_A,논타겟,TXT_1,50,5,3,30000",
    ])
    df, issues = pl.load_joined(folder)
    assert set(df["매칭"]) == {"양쪽", "채널만", "AF만"}
    af_only = df[df["매칭"] == "AF만"].iloc[0]
    assert af_only["채널"] == "네이버"
    assert af_only["비용"] == 0 and af_only["AF구매"] == 3
    assert any("매칭" in i["check"] for i in issues)


def test_missing_pair_reported(folder):
    write(folder, "2025-01-02_channel.csv", CH_HEADER, [
        "2025-01-02,구글,외부,GGL_A,플러스가입,논타겟,VID_1,1,1,1,1,1,1",
    ])
    df, issues = pl.load_joined(folder)
    assert any("파일" in i["check"] and "2025-01-02" in i["detail"] for i in issues)
    assert "2025-01-02" in set(df["일"].dt.strftime("%Y-%m-%d"))


def test_duplicate_keys_are_summed_and_reported(folder):
    write(folder, "2025-01-01_appsflyer.csv", AF_HEADER, [
        "2025-01-01,googleadwords_int,GGL_A,논타겟,VID_1,50,4,2,20000",
        "2025-01-01,googleadwords_int,GGL_A,논타겟,VID_1,40,4,2,20000",
        "2025-01-01,Facebook Ads,META_A,논타겟,IMG_1,180,3,1,5000",
    ])
    df, issues = pl.load_joined(folder)
    assert len(df) == 2
    assert df[df["채널"] == "구글"].iloc[0]["AF구매매출"] == 40000
    assert any("중복" in i["check"] for i in issues)


def test_unknown_media_source_reported(folder):
    write(folder, "2025-01-01_appsflyer.csv", AF_HEADER, [
        "2025-01-01,tiktok_int,TT_A,논타겟,VID_9,10,1,1,1000",
    ])
    _, issues = pl.load_joined(folder)
    assert any("미디어소스" in i["check"] for i in issues)


def test_summarize_metrics(folder):
    df, _ = pl.load_joined(folder)
    s = pl.summarize(df, ["채널"]).set_index("채널")
    g = s.loc["구글"]
    assert g["ROAS"] == pytest.approx(500.0)       # 50000 / 10000
    assert g["AF_ROAS"] == pytest.approx(400.0)
    assert g["CPA"] == pytest.approx(2000.0)
    assert g["CTR"] == pytest.approx(10.0)
    assert g["CPC"] == pytest.approx(100.0)
    assert g["AF매출비율"] == pytest.approx(80.0)


def test_summarize_total_and_zero_division(folder):
    df, _ = pl.load_joined(folder)
    zero = df.assign(비용=0)
    s = pl.summarize(zero, [])
    assert pd.isna(s.iloc[0]["ROAS"])


def test_load_empty_folder(tmp_path):
    df, issues = pl.load_joined(tmp_path)
    assert df.empty
    assert any(i["level"] == "error" for i in issues)
