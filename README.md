# 광고 성과 대시보드

채널 CSV와 AppsFlyer(MMP) CSV를 일별로 조인해 보는 Streamlit 대시보드.

## 로컬 실행
```bash
pip install -r requirements.txt
python3 -m streamlit run app.py
```

## 매일 데이터 추가
`YYYY-MM-DD_channel.csv`와 `YYYY-MM-DD_appsflyer.csv`를 루트에 넣고 커밋·푸시하면 Streamlit Cloud가 자동 재배포합니다.

```bash
git add *_channel.csv *_appsflyer.csv && git commit -m "data: add daily files" && git push
```

## 문서
규칙과 정의는 [AGENTS.md](AGENTS.md)와 `docs/` 참고. 테스트: `pip install -r requirements-dev.txt && python3 -m pytest tests -q`
