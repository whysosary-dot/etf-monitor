# ETF Monitor

`stock-valuation` 템플릿을 기반으로 만든 ETF 전용 모니터.
미국/글로벌·한국 ETF 총 117종목 — 분류, 섹터, 등락률, 3년/1년 차트, 현재가, 메모를 한 화면에서 본다.

🔗 **Live**: <https://whysosary-dot.github.io/etf-monitor/>

## 컬럼 구성

| 컬럼 | 설명 |
|---|---|
| ★ ETF 명칭 | 종목명 + 즐겨찾기. 네이버 종목 페이지 링크 |
| 티커 | 거래소 심볼 (한국 ETF는 `XXXXXX.KS`) |
| 분류 | 국가/지역 · 섹터/테마 · 한국 ETF |
| 섹터 | 반도체, 바이오, 방산 등 (색상 칩) |
| 투자 대상 | 원본 사진에 적혀 있던 설명 |
| 등락률 | 전일 종가 대비 일간 변화율 (한국식: 상승=빨강) |
| 3년 차트 | 주간봉 sparkline |
| 1년 차트 | 주간봉 sparkline |
| 현재가 | 원·달러 표기 (currency 기준) |
| 메모 | localStorage + GitHub 커밋 |

## 기능

- 검색·정렬·분류/섹터 필터·즐겨찾기 필터·섹터 그룹 보기
- 메모와 즐겨찾기는 브라우저 `localStorage`에 저장 → ☁️ 커밋 버튼으로 GitHub에 영구 저장
- GitHub PAT(`repo` 권한)는 ⚙️ 버튼에서 설정. 브라우저 안에만 저장됨

## 데이터 갱신

`fetch_chunk.py`가 yfinance에서 가격/3y·1y 주간 종가를 받아 `etfs.json`에 기록한다.

```bash
python3 fetch_chunk.py 0 117   # 한 번에 117개
```

## 파일

```
index.html        # 메인 페이지
etfs.json         # ETF 메타 + 가격 + 차트 데이터 (117개)
etfs_seed.py      # 분류·티커·설명 시드 데이터
fetch_chunk.py    # yfinance 가격 수집 스크립트
```
