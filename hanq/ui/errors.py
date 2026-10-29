"""AI 오류 창: 쉬운 말로 무슨 일인지 알려 주고, [다시 설정하기]로 고칠 곳에 바로 데려간다."""
from tkinter import messagebox

from ..ai.explain import explain
from .dialogs import ask_choice


def show_ai_error(app, title: str, msg: str):
    h = explain(msg)
    if h is None:
        messagebox.showerror(title, msg[:800], parent=app)
        return
    options = [("detail", "자세한 오류 보기", "normal"), ("close", "닫기", "normal")]
    if h.fix:
        options.append(("fix", "다시 설정하기", "primary"))
    while True:
        pick = ask_choice(app, title, h.title, options, h.how)
        if pick == "detail":
            messagebox.showinfo("자세한 오류", msg[:1500], parent=app)
            continue
        if pick == "fix":
            go_fix(app, h.fix)
        return


def chat_text(msg: str) -> str:
    """대화창에 남길 한두 줄."""
    h = explain(msg)
    return f"오류: {msg[:300]}" if h is None else f"{h.title} {h.how}"


def needs_fix(msg: str) -> bool:
    h = explain(msg)
    return bool(h and h.fix)


def go_fix(app, fix: str):
    tab = app.settings_tab
    provider = app.ai_config().provider
    if fix == "key" and provider in tab._cli:   # 구독 방식에서 '키 오류'는 로그인이 풀린 것
        fix = "login"
    if fix == "connect" or (fix == "login" and provider not in tab._cli):
        from .connect import ConnectDialog
        ConnectDialog(app)
        return
    app.nb.select(app.tab_cfg)
    if fix == "key":
        tab.focus_api_key()
    elif fix == "login":
        tab.start_cli_setup(provider)
    else:   # tokens / model: AI 설정 화면
        tab.show("ai")
        app.status("AI 설정 화면입니다. 모델이나 '최대 출력 토큰', '응답 대기 시간'을 바꿔 보세요.")