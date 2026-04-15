"""
GitHub Actions용 모니터링 스크립트
로컬 파일시스템 의존성 없이 1회 체크 후 결과를 출력합니다.
"""

import requests
import json
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

BRAND_KEYWORDS = ["모다올", "모다 올", "모다올의원", "modaol"]
NEGATIVE_TERMS = ["실패", "부작용", "사기", "피해", "소송", "고소", "폐업", "망", "최악", "후회"]


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
    except Exception as e:
        print(f"[오류] 네이버 조회 실패 ({keyword}): {e}")
        return []


def fetch_google_autocomplete(keyword):
    url = "https://suggestqueries.google.com/complete/search"
    params = {"client": "chrome", "q": keyword + " ", "hl": "ko", "gl": "kr"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[1] if isinstance(data, list) and len(data) > 1 else []
    except Exception as e:
        print(f"[오류] 구글 조회 실패 ({keyword}): {e}")
        return []


def main():
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S KST')}] 자동완성 모니터링 체크")
    print("=" * 60)

    all_suggestions = {}
    alerts = []

    for kw in BRAND_KEYWORDS:
        naver = fetch_naver_autocomplete(kw)
        google = fetch_google_autocomplete(kw)
        all_suggestions[kw] = {"naver": naver, "google": google}

        for platform, terms in [("naver", naver), ("google", google)]:
            if terms:
                print(f"\n[{platform.upper()}] '{kw}' 자동완성:")
                for i, term in enumerate(terms, 1):
                    print(f"  {i}. {term}")

            for rank, term in enumerate(terms, 1):
                for neg in NEGATIVE_TERMS:
                    if neg in term:
                        alerts.append({
                            "platform": platform,
                            "brand_keyword": kw,
                            "rank": rank,
                            "suggestion": term,
                            "matched_negative": neg,
                        })

    # 로그 파일 저장
    log_data = {
        "timestamp": now.isoformat(),
        "suggestions": all_suggestions,
        "alerts": alerts,
    }
    with open("monitor_log.json", "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    # 결과 출력
    print("\n" + "=" * 60)
    if alerts:
        # GitHub Actions에서 감지하는 시그널
        print("ALERT_DETECTED")
        print(f"🚨 부정 키워드 {len(alerts)}건 감지!")
        for a in alerts:
            print(f"  [{a['platform'].upper()}] '{a['suggestion']}' (#{a['rank']}위) — 매칭: '{a['matched_negative']}'")

        # 이메일 본문 생성
        lines = [
            "모다올 자동완성 부정 키워드가 감지되었습니다.",
            f"확인 시각: {now.strftime('%Y-%m-%d %H:%M KST')}",
            "",
            "=" * 50,
            "감지된 부정 키워드:",
            "=" * 50,
        ]
        for a in alerts:
            lines.append(
                f"  [{a['platform'].upper()}] \"{a['suggestion']}\" "
                f"(#{a['rank']}위, 매칭: '{a['matched_negative']}')"
            )
        lines += [
            "",
            "=" * 50,
            "전체 자동완성 현황:",
            "=" * 50,
        ]
        for kw, platforms in all_suggestions.items():
            for platform, terms in platforms.items():
                if terms:
                    lines.append(f"\n[{platform.upper()}] '{kw}':")
                    for i, term in enumerate(terms, 1):
                        marker = " ⚠️" if any(neg in term for neg in NEGATIVE_TERMS) else ""
                        lines.append(f"  {i}. {term}{marker}")
        lines += [
            "",
            "---",
            "이 알림은 GitHub Actions에서 자동 발송되었습니다.",
            "https://github.com/hy28lee/modaol-autocomplete-monitor",
        ]

        with open("alert_email.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    else:
        print("✅ 부정 키워드가 감지되지 않았습니다.")


if __name__ == "__main__":
    main()
