"""
GitHub Actions용 트래커
매시간 순위를 기록하고, 주간 리포트를 생성합니다.
데이터는 GitHub Actions artifact로 누적 저장됩니다.
"""

import requests
import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA_FILE = Path("tracker_data.json")

BRAND_KEYWORDS = ["모다올", "모다올의원"]
NEGATIVE_TERMS = ["실패", "부작용", "사기", "피해", "소송", "고소", "폐업", "망", "최악", "후회"]
POSITIVE_TERMS = ["후기", "비용", "가격", "생착률", "원장", "비절개", "리뷰", "전후"]


def fetch_google_autocomplete(keyword):
    url = "https://suggestqueries.google.com/complete/search"
    params = {"client": "firefox", "q": keyword, "hl": "ko"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[1] if isinstance(data, list) and len(data) > 1 else []
    except Exception:
        return []


def fetch_naver_autocomplete(keyword):
    url = "https://ac.search.naver.com/nx/ac"
    params = {
        "q": keyword, "con": "1", "frm": "nv", "ans": "2",
        "r_format": "json", "r_enc": "UTF-8", "r_unicode": "0",
        "type": "all", "t_koreng": "1", "run": "2",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        suggestions = []
        for item_group in data.get("items", []):
            for item in item_group:
                if isinstance(item, list) and len(item) > 0:
                    suggestions.append(item[0])
                elif isinstance(item, str):
                    suggestions.append(item)
        return suggestions
    except Exception:
        return []


def classify_keyword(term, brand_kw):
    suffix = term.replace(brand_kw, "").strip()
    for neg in NEGATIVE_TERMS:
        if neg in suffix:
            return "negative", neg
    for pos in POSITIVE_TERMS:
        if pos in suffix:
            return "positive", pos
    return "neutral", suffix


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": []}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record():
    now = datetime.now(KST)
    data = load_data()

    record_entry = {
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.hour,
        "keywords": {},
    }

    alerts = []

    for brand_kw in BRAND_KEYWORDS:
        google = fetch_google_autocomplete(brand_kw)
        naver = fetch_naver_autocomplete(brand_kw)

        kw_data = {"google": [], "naver": []}

        for platform, terms in [("google", google), ("naver", naver)]:
            if terms:
                print(f"\n[{platform.upper()}] '{brand_kw}' 자동완성:")
            for rank, term in enumerate(terms, 1):
                sentiment, matched = classify_keyword(term, brand_kw)
                kw_data[platform].append({
                    "rank": rank,
                    "term": term,
                    "sentiment": sentiment,
                    "matched": matched,
                })
                marker = " <-- NEGATIVE" if sentiment == "negative" else ""
                print(f"  {rank}. {term}{marker}")

                if sentiment == "negative":
                    alerts.append({
                        "platform": platform,
                        "term": term,
                        "rank": rank,
                        "matched": matched,
                    })

        record_entry["keywords"][brand_kw] = kw_data

    data["records"].append(record_entry)
    save_data(data)

    print(f"\n[{now.strftime('%Y-%m-%d %H:%M KST')}] 기록 완료 (총 {len(data['records'])}건)")

    # 알림 필요 여부
    if alerts:
        print("\nALERT_DETECTED")
        # 이메일 본문 생성
        lines = [
            f"모다올 자동완성 부정 키워드 감지 ({now.strftime('%Y-%m-%d %H:%M KST')})",
            "=" * 50,
            "",
        ]
        for a in alerts:
            lines.append(f"  [{a['platform'].upper()}] \"{a['term']}\" #{a['rank']}위 (매칭: {a['matched']})")
        lines += ["", "---", "자동 발송 알림 | GitHub Actions"]

        with open("alert_email.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    return alerts


def generate_weekly_report():
    """주간 리포트용 텍스트를 생성합니다."""
    data = load_data()
    records = data["records"]
    if not records:
        print("데이터 없음")
        return

    now = datetime.now(KST)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # 최근 7일 데이터
    recent = [r for r in records if r["date"] >= week_ago]
    if not recent:
        print("최근 7일 데이터 없음")
        return

    # 일별 부정 키워드 순위 집계
    daily_neg = {}
    daily_pos = {}

    for r in recent:
        date = r["date"]
        for brand_kw in BRAND_KEYWORDS:
            for platform in ["google", "naver"]:
                terms = r.get("keywords", {}).get(brand_kw, {}).get(platform, [])
                for t in terms:
                    if t["sentiment"] == "negative":
                        key = t["term"]
                        if key not in daily_neg:
                            daily_neg[key] = {}
                        if date not in daily_neg[key]:
                            daily_neg[key][date] = []
                        daily_neg[key][date].append(t["rank"])
                    elif t["sentiment"] == "positive":
                        key = t["term"]
                        if key not in daily_pos:
                            daily_pos[key] = {}
                        if date not in daily_pos[key]:
                            daily_pos[key][date] = []
                        daily_pos[key][date].append(t["rank"])

    lines = [
        f"모다올 주간 키워드 포지션 리포트",
        f"기간: {week_ago} ~ {now.strftime('%Y-%m-%d')}",
        f"총 기록: {len(recent)}건",
        "=" * 50,
        "",
    ]

    if daily_neg:
        lines.append("[ 부정 키워드 일별 평균 순위 ]")
        for term, dates_data in daily_neg.items():
            lines.append(f"\n  {term}:")
            sorted_dates = sorted(dates_data.keys())
            for d in sorted_dates:
                ranks = dates_data[d]
                avg = round(sum(ranks) / len(ranks), 1)
                lines.append(f"    {d}: 평균 {avg}위 ({len(ranks)}회 측정)")

            # 추세 계산
            if len(sorted_dates) >= 2:
                first_avg = sum(dates_data[sorted_dates[0]]) / len(dates_data[sorted_dates[0]])
                last_avg = sum(dates_data[sorted_dates[-1]]) / len(dates_data[sorted_dates[-1]])
                diff = last_avg - first_avg
                if diff > 0:
                    lines.append(f"    --> 추세: 순위 하락 중 (개선) +{diff:.1f}")
                elif diff < 0:
                    lines.append(f"    --> 추세: 순위 상승 중 (악화) {diff:.1f}")
                else:
                    lines.append(f"    --> 추세: 변동 없음")
        lines.append("")

    if daily_pos:
        lines.append("[ 긍정 키워드 일별 평균 순위 ]")
        for term, dates_data in daily_pos.items():
            lines.append(f"\n  {term}:")
            sorted_dates = sorted(dates_data.keys())
            for d in sorted_dates:
                ranks = dates_data[d]
                avg = round(sum(ranks) / len(ranks), 1)
                lines.append(f"    {d}: 평균 {avg}위")
        lines.append("")

    lines += [
        "---",
        f"생성: {now.strftime('%Y-%m-%d %H:%M KST')}",
        "GitHub: hy28lee/modaol-autocomplete-monitor",
    ]

    report_text = "\n".join(lines)
    print(report_text)

    with open("weekly_report.txt", "w", encoding="utf-8") as f:
        f.write(report_text)

    print("\nWEEKLY_REPORT_READY")


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "record"
    if action == "record":
        record()
    elif action == "report":
        generate_weekly_report()
