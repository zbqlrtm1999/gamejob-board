"""게임잡에서 '게임운영 + 경력무관' 공고를 가져와 index.html의 JOBS 목록을 새로 채운다.

GitHub Actions가 매일 실행한다 (.github/workflows/update.yml).
외부 패키지 없이 파이썬 표준 라이브러리만 사용한다.
"""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
LIST_URL = "https://www.gamejob.co.kr/Recruit/_GI_Job_List/"
REFERER = "https://www.gamejob.co.kr/Recruit/joblist?menucode=duty"
DUTY_GAME_OPS = "23"      # 직종: 게임운영·QA > 게임운영
CAREER_ANY = "2"          # 경력: 경력무관
WINDOW_DAYS = 14          # 최근 며칠 안에 등록된 공고만 보여줄지
PAGE_SIZE = 40
MAX_PAGES = 5

INDEX = Path(__file__).resolve().parent.parent / "index.html"


def fetch_page(page: int) -> str:
    form = {
        "condition[menucode]": "duty",
        "condition[duty]": DUTY_GAME_OPS,
        "condition[dutyCtgrSelect]": "5",
        "condition[dutySelect]": DUTY_GAME_OPS,
        "condition[career_stat]": CAREER_ANY,
        "page": str(page),
        "pagesize": str(PAGE_SIZE),
        "direct": "0",
        "order": "2",
        "tabcode": "1",
    }
    req = urllib.request.Request(
        LIST_URL,
        data=urllib.parse.urlencode(form).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": REFERER,
            "User-Agent": "Mozilla/5.0 (gamejob-board daily update; once a day)",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def text(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def guess_year(month: int, day: int, today: date, future: bool) -> date:
    """월/일만 있는 날짜에 연도를 붙인다. 등록일은 과거, 마감일은 미래 쪽으로 맞춘다."""
    d = date(today.year, month, day)
    if future and d < today - timedelta(days=60):
        d = date(today.year + 1, month, day)
    if not future and d > today:
        d = date(today.year - 1, month, day)
    return d


def parse_reg(raw: str, today: date):
    m = re.search(r"(\d+)\s*일\s*전", raw)
    if m:
        return today - timedelta(days=int(m.group(1)))
    if "오늘" in raw or re.search(r"\d+\s*(시간|분)\s*전", raw):
        return today
    m = re.search(r"(\d{1,2})/(\d{1,2})", raw)
    if m:
        return guess_year(int(m.group(1)), int(m.group(2)), today, future=False)
    return None


def parse_end(raw: str, today: date):
    if "오늘" in raw:
        return today
    if "내일" in raw:
        return today + timedelta(days=1)
    m = re.search(r"(\d{1,2})/(\d{1,2})", raw)
    if m:
        return guess_year(int(m.group(1)), int(m.group(2)), today, future=True)
    return None  # 채용시, 상시


LANG_WORDS = r"Linguist|번역|현지화|로컬라이|검수"
OPS_WORDS = r"운영|GM|CS|CM|모니터링|커뮤니티"
PLAN_WORDS = r"PM|기획|사업"


def classify(title: str) -> str:
    if re.search(LANG_WORDS, title, re.I):
        return "lang"
    if re.search(PLAN_WORDS, title) and not re.search(OPS_WORDS, title):
        return "plan"
    return "ops"


def parse_rows(page_html: str, today: date):
    jobs = []
    for row in re.findall(r"<tr>[\s\S]*?</tr>", page_html):
        gi = re.search(r"GI_No=(\d+)", row)
        if not gi:
            continue
        co = re.search(r'class="company[\s\S]*?<strong>([^<]+)</strong>', row)
        title = re.search(r'GI_No=\d+"[^>]*><strong>([^<]+)</strong>', row)
        info = re.search(r'<p class="info">([\s\S]*?)</p>', row)
        spans = [text(s) for s in re.findall(r"<span>([^<]*)</span>", info.group(1))] if info else []
        end_raw = re.search(r'class="date">([^<]*)<', row)
        reg_raw = re.search(r'class="modifyDate">([^<]*)<', row)
        if not (co and title and len(spans) >= 5):
            continue
        t = text(title.group(1))
        reg = parse_reg(reg_raw.group(1) if reg_raw else "", today)
        end = parse_end(end_raw.group(1) if end_raw else "", today)
        edu = spans[1].replace("고등학교졸업↑", "고졸 이상")
        jobs.append({
            "id": int(gi.group(1)),
            "kind": classify(t),
            "co": text(co.group(1)),
            "title": t,
            "type": spans[4],
            "loc": spans[2].replace(" > ", " "),
            "edu": edu,
            "reg": reg.isoformat() if reg else None,
            "end": end.isoformat() if end else None,
            "careerNote": bool(re.search(r"\(경력\)|경력\s*\d+\s*년", t)),
        })
    return jobs


def main() -> int:
    now = datetime.now(KST)
    today = now.date()
    found = {}
    for page in range(1, MAX_PAGES + 1):
        rows = parse_rows(fetch_page(page), today)
        for j in rows:
            found[j["id"]] = j
        if len(rows) < PAGE_SIZE:
            break
        time.sleep(2)

    if not found:
        print("공고를 하나도 읽지 못했습니다. 게임잡 화면 구조가 바뀌었을 수 있어요.", file=sys.stderr)
        return 1

    since = today - timedelta(days=WINDOW_DAYS)
    recent = [j for j in found.values() if j["reg"] and date.fromisoformat(j["reg"]) >= since]
    recent.sort(key=lambda j: (j["reg"], j["id"]), reverse=True)

    lines = [f'  const UPDATED = {json.dumps(now.strftime("%Y-%m-%d %H:%M"))};', "  const JOBS = ["]
    lines += [f"    {json.dumps(j, ensure_ascii=False)}," for j in recent]
    lines.append("  ];")
    block = "\n".join(lines)

    page = INDEX.read_text(encoding="utf-8")
    new, n = re.subn(r"(/\* JOBS:START \*/\n)[\s\S]*?(\n  /\* JOBS:END \*/)",
                     lambda m: m.group(1) + block + m.group(2), page)
    if n != 1:
        print("index.html에서 JOBS:START / JOBS:END 표시를 찾지 못했습니다.", file=sys.stderr)
        return 1
    INDEX.write_text(new, encoding="utf-8", newline="\n")
    print(f"전체 {len(found)}건 중 최근 {WINDOW_DAYS}일 공고 {len(recent)}건을 반영했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
