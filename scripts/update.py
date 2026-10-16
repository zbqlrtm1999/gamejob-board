"""게임잡 '게임운영 + 경력무관' 공고와 알바몬 게임운영 공고를 가져와 index.html의 JOBS 목록을 새로 채운다.

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

ALBAMON_SEARCH = "https://www.albamon.com/total-search"
ALBAMON_KEYWORDS = ["게임운영", "게임 GM", "게임 CS", "게임 모니터링"]
ALBAMON_MAX_PAGES = 3
# 알바몬 키워드 검색에는 오락실·게임학원·보드게임카페 같은 공고가 섞여 나오므로 걸러낸다.
ALBAMON_EXCLUDE_PARTS = {"오락실·게임장", "학원운영지원", "PC방", "놀이공원·테마파크", "이벤트·행사스텝",
                         "백화점·쇼핑몰", "일반음식점", "서빙", "이색테마카페", "매장관리·판매"}
ALBAMON_EXCLUDE_TITLE = r"오락실|보드게임|학원|팝업|매장|홀덤|게임존|게임장"
ALBAMON_JOB_WORDS = r"운영|GM|CS|QA|모니터링|테스터"

INDEX = Path(__file__).resolve().parent.parent / "index.html"
UA = "Mozilla/5.0 (gamejob-board daily update; once a day)"


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
            "User-Agent": UA,
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
            "src": "게임잡",
            "id": int(gi.group(1)),
            "url": f"https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No={gi.group(1)}",
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


def fetch_albamon(keyword: str, page: int) -> dict:
    url = f"{ALBAMON_SEARCH}?{urllib.parse.urlencode({'keyword': keyword, 'page': page})}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read().decode("utf-8")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', body, re.S)
    if not m:
        raise ValueError("알바몬 페이지에서 공고 데이터를 찾지 못했습니다.")
    queries = json.loads(m.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
    return queries[0]["state"]["data"]["base"]


def parse_albamon_posted(raw: str, today: date):
    if re.search(r"(분|시간)\s*전|방금|오늘", raw):
        return today
    if "어제" in raw:
        return today - timedelta(days=1)
    return parse_reg(raw, today)


def albamon_item(it: dict, today: date):
    title = text(it.get("recruitTitle", ""))
    parts = set(it.get("parts") or [])
    if parts & ALBAMON_EXCLUDE_PARTS or re.search(ALBAMON_EXCLUDE_TITLE, title):
        return None
    if not (re.search(r"게임", title + it.get("companyName", "")) and re.search(ALBAMON_JOB_WORDS, title, re.I)):
        return None
    closing = it.get("closingDate") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", closing):
        end = date.fromisoformat(closing)
    else:
        end = parse_end(closing, today) if "상시" not in closing else None
    reg = parse_albamon_posted(it.get("postedDate") or "", today)
    pay_type = (it.get("payType") or {}).get("description", "")
    area = " ".join((it.get("workplaceArea") or "").split()[:2])
    no = it["recruitNo"]
    return {
        "src": "알바몬",
        "id": no,
        "url": f"https://www.albamon.com/jobs/detail/{no}",
        "kind": classify(title),
        "co": text(it.get("companyName", "")),
        "title": title,
        "type": f"{pay_type} {it.get('pay', '')}".strip() or "알바",
        "loc": area,
        "edu": f"근무 {it['workingPeriod']}" if it.get("workingPeriod") else "",
        "reg": reg.isoformat() if reg else None,
        "end": end.isoformat() if end else None,
        "careerNote": bool(re.search(r"\(경력\)|경력\s*\d+\s*년", title)),
    }


def collect_albamon(today: date) -> dict:
    found = {}
    for kw in ALBAMON_KEYWORDS:
        for page in range(1, ALBAMON_MAX_PAGES + 1):
            base = fetch_albamon(kw, page)
            items = (base.get("normal") or {}).get("collection") or []
            for it in items:
                j = albamon_item(it, today)
                if j:
                    found[j["id"]] = j
            total = (base.get("pagination") or {}).get("totalCount", 0)
            time.sleep(2)
            if page * 20 >= total or not items:
                break
    # 같은 회사가 같은 제목으로 여러 번 다시 올린 공고는 가장 최근 것 하나만 남긴다.
    latest = {}
    for j in found.values():
        key = (j["co"], j["title"])
        if key not in latest or (j["reg"] or "") > (latest[key]["reg"] or ""):
            latest[key] = j
    return {j["id"]: j for j in latest.values()}


def collect_gamejob(today: date) -> dict:
    found = {}
    for page in range(1, MAX_PAGES + 1):
        rows = parse_rows(fetch_page(page), today)
        for j in rows:
            found[j["id"]] = j
        if len(rows) < PAGE_SIZE:
            break
        time.sleep(2)
    return found


def main() -> int:
    now = datetime.now(KST)
    today = now.date()

    # 한 사이트가 실패해도 다른 사이트 공고는 보여준다. 둘 다 실패하면 페이지를 바꾸지 않는다.
    results = {}
    for name, collect in (("게임잡", collect_gamejob), ("알바몬", collect_albamon)):
        try:
            results[name] = collect(today)
        except Exception as e:  # noqa: BLE001
            print(f"{name} 공고를 가져오지 못했습니다: {e}", file=sys.stderr)
            results[name] = {}
        if not results[name]:
            print(f"{name}: 공고 0건 (화면 구조가 바뀌었을 수 있어요)", file=sys.stderr)

    found = {f"{j['src']}-{j['id']}": j for r in results.values() for j in r.values()}
    if not found:
        print("공고를 하나도 읽지 못했습니다.", file=sys.stderr)
        return 1

    since = today - timedelta(days=WINDOW_DAYS)
    recent = [j for j in found.values()
              if j["reg"] and date.fromisoformat(j["reg"]) >= since
              and not (j["end"] and date.fromisoformat(j["end"]) < today)]  # 이미 마감된 공고는 뺀다
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
    by_src = {s: sum(1 for j in recent if j["src"] == s) for s in results}
    print(f"전체 {len(found)}건 중 최근 {WINDOW_DAYS}일 공고 {len(recent)}건을 반영했습니다. {by_src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
