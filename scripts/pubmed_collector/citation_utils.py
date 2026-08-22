"""인용문 저자 표기 판별 — 3단계(build_all)와 C단계(enrich_authors_mesh)가 함께 쓴다.

원래 이 판별은 build_all.py의 비공개 함수(`_is_author_token`·`_is_author_segment`)로만
있었고, enrich_authors_mesh.py가 `build_all._is_author_segment(...)` 처럼 직접 참조했다.
2026-08-20에 build_all.py의 파서를 갈아엎으면서 그 함수를 지웠더니 C단계가
`AttributeError`로 죽었다. 같은 일이 다시 일어나지 않게 여기로 분리한다.

두 스크립트가 같은 규칙을 써야 하는 이유:
  · build_all — 인용문에서 제목을 뽑을 때 앞뒤 저자 목록을 떼어내야 한다
  · enrich_authors_mesh — 인용문 저자부에서 (성, 이니셜)을 뽑아 '본인 저자'를 가른다
규칙이 갈리면 한쪽이 저자로 본 조각을 다른 쪽이 제목으로 보게 되어 결과가 어긋난다.

판정 원칙: **저자인지 제목인지 확신할 수 없으면 저자로 판정하지 않는다.**
제목을 저자로 오인해 떼어내면 그 논문을 통째로 잃지만, 저자를 제목에 남겨 두면
검색어가 지저분해질 뿐 대조 단계에서 걸러진다.
"""

import re

# 저자 한 명 꼴: "Oh SM" / "van der Berg JT" — 마지막 단어가 대문자 이니셜(1~3자)
AUTHOR_LAST_RE = re.compile(r"[A-Z][A-Z.\-]{0,2}$")

# 이름 앞머리에 오는 소문자 조각. 이것 말고 소문자로 시작하는 낱말이 있으면 저자가 아니다
# — "Effects of vitamin D"의 "of"처럼 기능어가 낀 제목을 저자로 오인하지 않기 위해서다.
NAME_PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "do", "dos", "da",
    "la", "le", "du", "ter", "ten", "bin", "ibn", "al", "abu", "mac", "mc", "st",
    "and", "&",                                    # 목록 마지막 저자 앞의 접속사
}

# 이름 한 토막. 한글·유니코드 하이픈(Gonzalez‐Ortiz)까지 견디게 넓게 잡는다
NAME_WORD = r"[A-Z][\w'’‐‑\-]*"

# 제목과 붙어 버린 저자 한 명
#  - 이니셜 표기: "Choi EH.Hospital-Based …" / "… Case Reports. Lee DW"
#  - 전체 이름  : "… Tae Sun Park. The Neuroprotective …"
# 목록 마지막 저자에는 "and"/"&"가 앞에 붙기도 한다 ("…, and Ruhl S. (2013) 제목")
GLUED_AUTHOR = r"(?:and\s+|&\s*)?[A-Z][A-Za-z'’\-]*(?:\s+[A-Za-z'’\-]+)*\s+[A-Z][A-Z.\-]{0,2}"
GLUED_FULLNAME = NAME_WORD + r"(?:\s+" + NAME_WORD + r"){1,3}"

# "Kim, Yeshin; Kang, Dong Woo; …; Suh, Jeewon." 처럼 세미콜론으로 나열한 저자 목록.
# 마지막 저자 뒤의 마침표까지 통째로 떼어낸다.
_SEMI_NAME = r"[A-Z](?:[\w'’‐‑\-]|\.(?=[A-Z]))*"
SEMI_AUTHOR_RUN = re.compile(
    r"^(?:" + _SEMI_NAME + r",\s+" + _SEMI_NAME + r"(?:\s+" + _SEMI_NAME + r")*\.?\s*;\s*)+"
    + _SEMI_NAME + r",\s+" + _SEMI_NAME + r"(?:\s+" + _SEMI_NAME + r")*\.\s+"
)

# 학위 표기 — 저자 목록 안에 섞여 들어온다 ("Jun Tak Choi, MD, Jeong-Hwan Seo, MD, PhD, …")
CREDENTIALS = {"md", "phd", "ms", "msc", "mph", "dds", "dmd", "rn", "bs", "mba", "dvm"}
CREDENTIAL_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(sorted(CREDENTIALS, key=len, reverse=True)) + r")\b[\s.,]*", re.I
)

# "et al." 접두 — 저자 목록 끝의 "et al."이 제목에 붙어 남는다
ET_AL_PREFIX_RE = re.compile(r"^(?:and\s+)?et\s*\.?\s*al\.?[\s.,;]*", re.I)

# 성과 이니셜이 붙어 버린 원문 오타를 떼어 본다 — "YoonSJ" → "Yoon SJ".
# (판별할 때만 쓴다. 원문 자체는 바꾸지 않는다)
STUCK_INITIALS_RE = re.compile(r"\b([A-Z][a-z]{2,})([A-Z]{1,3})\b")


def _is_name_part(word):
    """저자 이름을 이루는 낱말인가 — 대문자로 시작하거나, 이름 앞머리 소문자 조각이거나."""
    if not word:
        return False
    if word[0].isupper():
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z.'’\-]*", word))
    return word.lower().rstrip(".") in NAME_PARTICLES


def is_author_token(token):
    """쉼표로 나눈 토큰 하나가 '성 + 이니셜' 저자 표기인지 판별한다.

    마지막 낱말이 대문자 이니셜(1~3자)이고, 앞의 낱말들이 전부 이름 조각이어야 한다.

    앞 낱말에 '이름 조각' 조건을 두는 이유: 그것이 없으면 "Effects of vitamin D"처럼
    4단어 이하이고 마지막이 대문자 한 글자인 **제목**이 저자로 잡힌다. 흔한 제목
    모양이라 언젠가 실제로 걸린다. "of"는 이름에 쓰이지 않으므로 여기서 걸러진다.
    """
    t = token.strip().rstrip(".")
    if not t:
        return False
    if t.lower() in {"et al", "and et al"}:
        return True
    words = t.split()
    if len(words) < 2 or len(words) > 4:           # "Kim NJ"~"van der Berg JT" 범위
        return False
    if not AUTHOR_LAST_RE.fullmatch(words[-1]):    # 마지막 단어 = 대문자 이니셜
        return False
    return all(_is_name_part(w) for w in words[:-1])


def is_author_segment(segment):
    """조각 하나가 저자 목록인지 판별 — 쉼표 토큰의 6할 이상이 저자 표기면 저자 조각.

    C단계 enrich_authors_mesh.py가 "인용문 저자부에서 (성, 이니셜) 뽑기"에 쓴다.
    제목·학술지 조각의 대문자 낱말을 저자로 오인하지 않으려면 판별 규칙이 한 곳에 있어야 한다.
    """
    tokens = [t for t in segment.split(",") if t.strip()]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if is_author_token(t))
    if len(tokens) == 1:
        return hits == 1
    return hits / len(tokens) >= 0.6


def is_fullname_token(token):
    """'Heung Yong Jin' / 'Jun Tak Choi'처럼 이니셜 없이 전체 이름으로 쓴 저자 한 명.

    2~4단어가 모두 대문자로 시작할 때만 인정한다. 논문 제목은 기능어(of/the/in)가
    소문자라 이 조건에 잘 걸리지 않는다. 그래도 위험하므로 호출하는 쪽에서
    '연속 2명 이상'일 때만 저자 목록으로 취급한다.
    """
    t = token.strip().rstrip(".")
    if not t:
        return False
    if t.lower().replace(".", "") in CREDENTIALS:   # "MD" "PhD" 같은 학위 표기
        return True
    words = t.split()
    if not (2 <= len(words) <= 4):
        return False
    return all(re.fullmatch(NAME_WORD, w) for w in words)


def is_name_fragment(token):
    """'Choo'처럼 이니셜이 빠진 성 하나로 보이는 짧은 토막인지 — 1~2단어에 전부 대문자 시작."""
    t = token.strip().rstrip(".")
    words = t.split()
    if not (1 <= len(words) <= 2):
        return False
    return all(re.fullmatch(NAME_WORD, w) for w in words)


def looks_like_author(token):
    """파서 전용 저자 판별 — is_author_token에 원문 오타 보정을 더한 것.

    "YoonSJ, Lee KB." 처럼 성과 이니셜이 붙어 버린 표기를 떼어서 한 번 더 본다
    (윤선중 교수 인용문에 실제로 있는 모양이다).
    """
    if is_author_token(token):
        return True
    return is_author_token(STUCK_INITIALS_RE.sub(r"\1 \2", token.strip()))


def has_glued_author_prefix(text):
    """'Lee CS. 제목…' 처럼 맨 앞에 저자 한 명이 제목과 붙어 있는가."""
    for pattern in (r"^(" + GLUED_AUTHOR + r")\.\s*(?=\S)",
                    r"^(" + GLUED_FULLNAME + r")\.\s*(?=\S)"):
        m = re.match(pattern, text or "")
        if m and (looks_like_author(m.group(1)) or is_fullname_token(m.group(1))):
            return True
    return False


def author_run_end(parts, start=0):
    """parts[start:]에서 앞에서부터 저자로 볼 수 있는 토큰 수(끝 인덱스). 확신이 없으면 start.

    문맥까지 본다 — 저자 목록은 보통 **2명 이상**이거나, 마지막 저자가 제목과 붙어 있다
    ("Hwang JH, Lee CS. Malaria-induced …"). 저자로 보이는 토큰이 딱 하나뿐이고 그 뒤에
    제목이 붙어 있지도 않으면, '성 이니셜' 두 낱말일 때만 저자로 본다.
    그보다 길면 "Serum Vitamin D" 같은 제목일 수 있으므로 저자로 판정하지 않는다.
    """
    end = start
    while end < len(parts) and looks_like_author(parts[end]):
        end += 1
    if end == start:
        return start
    if end - start >= 2:
        return end
    if end < len(parts) and has_glued_author_prefix(parts[end].strip()):
        return end
    return end if len(parts[start].split()) <= 2 else start
