"""AI 오류 문구를 처음 쓰는 사람도 알아듣는 말로 바꾼다.

explain(msg) → Help(무슨 일인지, 어떻게 하면 되는지, 고칠 곳)
  fix: "key"(API 키 다시 넣기) / "login"(구독 다시 로그인·설치) / "tokens"(출력 길이 설정) /
       "model"(모델 바꾸기) / "connect"(연결 방법 고르기) / ""(설정할 것 없음)
"""
import re
from dataclasses import dataclass


@dataclass
class Help:
    title: str
    how: str
    fix: str = ""


# (찾을 말들, 제목, 할 일, 고칠 곳) — 위에서부터 먼저 맞는 것을 쓴다
_RULES = [
    (r"API 키가 없|API 키를 먼저|키를 먼저",
     "AI 연결이 아직 안 되어 있어요.", "Claude·ChatGPT 구독이나 API 키 중 가지고 있는 것으로 연결해 주세요.", "connect"),
    (r"\[401\]|unauthori[sz]ed|invalid.{0,20}(api.?key|x-api-key|authentication)|incorrect api key|api key not valid|API_KEY_INVALID",
     "API 키가 틀렸거나 지워진 키예요.", "키를 받은 곳에서 키를 다시 복사해 붙여 넣어 주세요. 앞뒤에 빈칸이 들어가지 않았는지도 확인해 주세요.", "key"),
    (r"not logged in|please run /login|login|로그인|auth(entication)? (required|failed)|OAuth|token (has )?expired",
     "구독 계정 로그인이 풀렸어요.", "[다시 설정하기]를 누르면 로그인 창이 열립니다. 로그인만 다시 하면 됩니다.", "login"),
    (r"찾을 수 없습니다|실행할 수 없습니다|not recognized|No such file",
     "Claude Code/Codex 프로그램을 찾지 못했어요.", "[다시 설정하기]를 누르면 설치와 로그인을 자동으로 다시 합니다.", "login"),
    (r"credit balance|insufficient_quota|billing|quota|결제|payment required|\[402\]",
     "AI 사용 금액(크레딧)이 모자라요.", "키를 받은 사이트에서 결제 정보나 남은 금액을 확인해 주세요. 구독 계정으로 바꿔 쓰는 방법도 있어요.", "connect"),
    (r"\[429\]|rate.?limit|too many requests|usage limit|limit reached|RESOURCE_EXHAUSTED",
     "잠깐 사이에 너무 많이 요청했어요.", "1~2분 기다렸다가 다시 해 주세요. 구독은 정해진 사용량을 다 쓰면 몇 시간 뒤에 풀립니다.", ""),
    (r"overloaded|\[529\]|\[50[0234]\]|server error|unavailable",
     "AI 회사 서버가 지금 붐벼요.", "잠시 뒤에 다시 해 주세요. 계속 안 되면 설정에서 다른 모델을 골라 보세요.", "model"),
    (r"model.{0,40}(not found|does not exist|not supported|invalid)|\[404\]",
     "고른 모델 이름을 AI가 알아듣지 못했어요.", "설정에서 [목록 갱신]을 누른 뒤 목록에 있는 모델로 골라 주세요.", "model"),
    (r"잘렸을 수|max_tokens|maximum.{0,20}tokens|context.{0,10}(length|window)|too long|prompt is too long",
     "글이 너무 길어서 AI가 다 쓰지 못했어요.", "설정의 '최대 출력 토큰'을 늘리거나, 참고 자료를 줄여서 다시 해 주세요.", "tokens"),
    (r"대기 시간|timed? ?out|timeout",
     "AI 답이 너무 오래 걸려서 멈췄어요.", "다시 해 보거나, 설정에서 '응답 대기 시간'을 늘려 주세요.", "tokens"),
    (r"연결하지 못했|ConnectionError|Name or service not known|getaddrinfo|SSL|Max retries|network",
     "인터넷에 연결하지 못했어요.", "인터넷이 되는지 확인해 주세요. 학교망에서 막혀 있으면 정보부에 'AI 사이트 접속'을 문의해 주세요.", ""),
    (r"응답 형식 오류|JSON|응답이 비어",
     "AI가 엉뚱한 형식으로 답했어요.", "한 번 더 해 보세요. 자주 그러면 설정에서 더 좋은 모델을 골라 주세요.", "model"),
]


def explain(msg: str) -> Help | None:
    """알아들을 수 있는 오류면 Help, 모르는 오류면 None (원래 문구를 그대로 보여 준다)."""
    for pattern, title, how, fix in _RULES:
        if re.search(pattern, msg or "", re.I):
            return Help(title, how, fix)
    return None
