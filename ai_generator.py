"""
AI 문서 생성 - Claude(Anthropic) 및 Gemini(Google) 지원.
"""
import re
from typing import Callable, Optional


DOC_TYPE_PROMPTS = {
    "보고서": "업무 보고서 형식으로 작성하세요. 제목, 개요, 주요 내용, 결론으로 구성하세요.",
    "계획서": "사업/업무 계획서 형식으로 작성하세요. 목적, 추진 배경, 세부 계획, 기대 효과를 포함하세요.",
    "회의록": "회의록 형식으로 작성하세요. 일시, 참석자, 안건, 논의 내용, 결정 사항, 후속 조치를 포함하세요.",
    "제안서": "제안서 형식으로 작성하세요. 제안 배경, 현황 분석, 제안 내용, 기대 효과, 추진 일정을 포함하세요.",
    "공문": "공문 형식으로 작성하세요. 수신, 제목, 본문, 끝 문구를 포함하며 정중하고 격식체로 작성하세요.",
    "보도자료": "보도자료 형식으로 작성하세요. 핵심 내용을 앞에 배치하고 상세 내용, 인용구, 배경 정보 순으로 작성하세요.",
    "기안문": "기안문 형식으로 작성하세요. 기안 목적, 추진 근거, 세부 내용, 행정 사항을 포함하세요.",
    "자유형식": "적절한 문서 형식으로 자연스럽게 작성하세요.",
}

CLAUDE_MODELS = [
    ("claude-opus-4-7", "Claude Opus 4.7 (최고 품질)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (빠름)"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (경량)"),
]

GEMINI_MODELS = [
    ("gemini-2.5-pro", "Gemini 2.5 Pro (최고 품질)"),
    ("gemini-2.0-flash", "Gemini 2.0 Flash (빠름)"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro"),
]

OPENROUTER_MODELS = [
    ("anthropic/claude-opus-4", "Claude Opus 4 (최고 품질)"),
    ("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5 (빠름)"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("openai/gpt-4o", "GPT-4o"),
    ("openai/gpt-4o-mini", "GPT-4o Mini (경량)"),
    ("deepseek/deepseek-r1", "DeepSeek R1"),
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B"),
]


def _build_system_prompt(doc_type: str, template_text: str) -> str:
    doc_guide = DOC_TYPE_PROMPTS.get(doc_type, DOC_TYPE_PROMPTS["자유형식"])
    base = (
        "당신은 전문 문서 작성 보조 AI입니다. "
        "한국어로 작성하며, 격식체(합쇼체)를 기본으로 합니다. "
        f"{doc_guide}\n\n"
        "중요 규칙:\n"
        "- 결과물은 순수 문서 내용만 출력하세요. 설명이나 메타 텍스트는 제외합니다.\n"
        "- 한글 문서에 바로 붙여넣기 할 수 있는 형태로 작성하세요.\n"
        "- 날짜, 서명란 등 구체적인 정보가 없으면 [날짜], [성명] 등으로 표시하세요.\n"
    )
    if template_text and template_text.strip():
        base += f"\n\n[템플릿 구조 참고]\n{template_text[:2000]}"
    return base


def _build_user_prompt(input_type: str, input_data: str,
                       doc_type: str, extra_instructions: str) -> str:
    prompts = {
        "keywords": f"다음 키워드를 바탕으로 {doc_type}을 작성하세요:\n\n키워드: {input_data}",
        "data": f"다음 데이터/정보를 바탕으로 {doc_type}을 작성하세요:\n\n{input_data}",
        "text": f"다음 텍스트를 바탕으로 완성된 {doc_type}으로 발전시켜 작성하세요:\n\n{input_data}",
    }
    prompt = prompts.get(input_type, prompts["text"])
    if extra_instructions.strip():
        prompt += f"\n\n추가 지시사항: {extra_instructions}"
    return prompt


def _parse_field_response(raw: str, fields: list[str]) -> dict[str, str]:
    result = {}
    pattern = r'FIELD:(\w+)\nCONTENT:\n(.*?)\nEND'
    for m in re.finditer(pattern, raw, re.DOTALL):
        result[m.group(1)] = m.group(2).strip()
    if not result:
        for f in fields:
            result[f] = raw.strip()
    return result


# ── Claude (Anthropic) ───────────────────────────────────────────────────────

class ClaudeGenerator:
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-4-7"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def _use_thinking(self) -> bool:
        return self.model in ("claude-opus-4-7", "claude-sonnet-4-6")

    def generate_streaming(
        self,
        doc_type: str,
        input_type: str,
        input_data: str,
        template_text: str = "",
        extra_instructions: str = "",
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        system = _build_system_prompt(doc_type, template_text)
        user = _build_user_prompt(input_type, input_data, doc_type, extra_instructions)
        kwargs = dict(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if self._use_thinking():
            kwargs["thinking"] = {"type": "adaptive"}

        full_text = []
        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                full_text.append(text)
                if on_chunk:
                    on_chunk(text)
        return "".join(full_text)

    def fill_template_fields(
        self,
        template_text: str,
        fields: list[str],
        doc_type: str,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> dict[str, str]:
        fields_list = "\n".join(f"- {{{{{f}}}}}: {f} 내용" for f in fields)
        system = (
            "당신은 문서 작성 전문가입니다. 템플릿의 각 필드에 들어갈 내용을 생성합니다. "
            "반드시 아래 형식으로만 응답하세요:\nFIELD:필드명\nCONTENT:\n내용\nEND\n\n"
            "각 필드마다 위 형식을 반복합니다."
        )
        user = (
            f"문서 유형: {doc_type}\n작성 맥락: {context}\n\n"
            f"[템플릿]\n{template_text[:1500]}\n\n"
            f"[채워야 할 필드들]\n{fields_list}\n\n각 필드의 적절한 내용을 생성해주세요."
        )
        kwargs = dict(
            model=self.model,
            max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if self._use_thinking():
            kwargs["thinking"] = {"type": "adaptive"}

        chunks = []
        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                if on_chunk:
                    on_chunk(text)
        return _parse_field_response("".join(chunks), fields)

    def suggest_doc_type(self, input_data: str) -> str:
        resp = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=50,
            messages=[{"role": "user", "content": (
                f"다음 내용으로 만들기 적합한 문서 유형을 하나만 답하세요.\n"
                f"선택지: 보고서, 계획서, 회의록, 제안서, 공문, 보도자료, 기안문, 자유형식\n\n"
                f"내용: {input_data[:300]}"
            )}],
        )
        answer = resp.content[0].text.strip()
        for t in DOC_TYPE_PROMPTS:
            if t in answer:
                return t
        return "자유형식"


# ── Gemini (Google) ──────────────────────────────────────────────────────────

class GeminiGenerator:
    def __init__(self, api_key: str, model: str = "gemini-2.5-pro"):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate_streaming(
        self,
        doc_type: str,
        input_type: str,
        input_data: str,
        template_text: str = "",
        extra_instructions: str = "",
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        from google.genai import types
        system = _build_system_prompt(doc_type, template_text)
        user = _build_user_prompt(input_type, input_data, doc_type, extra_instructions)

        full_text = []
        for chunk in self.client.models.generate_content_stream(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=4096,
            ),
        ):
            if chunk.text:
                full_text.append(chunk.text)
                if on_chunk:
                    on_chunk(chunk.text)
        return "".join(full_text)

    def fill_template_fields(
        self,
        template_text: str,
        fields: list[str],
        doc_type: str,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> dict[str, str]:
        from google.genai import types
        fields_list = "\n".join(f"- {{{{{f}}}}}: {f} 내용" for f in fields)
        system = (
            "당신은 문서 작성 전문가입니다. 템플릿의 각 필드에 들어갈 내용을 생성합니다. "
            "반드시 아래 형식으로만 응답하세요:\nFIELD:필드명\nCONTENT:\n내용\nEND\n\n"
            "각 필드마다 위 형식을 반복합니다."
        )
        user = (
            f"문서 유형: {doc_type}\n작성 맥락: {context}\n\n"
            f"[템플릿]\n{template_text[:1500]}\n\n"
            f"[채워야 할 필드들]\n{fields_list}\n\n각 필드의 적절한 내용을 생성해주세요."
        )
        chunks = []
        for chunk in self.client.models.generate_content_stream(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=3000,
            ),
        ):
            if chunk.text:
                chunks.append(chunk.text)
                if on_chunk:
                    on_chunk(chunk.text)
        return _parse_field_response("".join(chunks), fields)

    def suggest_doc_type(self, input_data: str) -> str:
        from google.genai import types
        resp = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=(
                f"다음 내용으로 만들기 적합한 문서 유형을 하나만 답하세요.\n"
                f"선택지: 보고서, 계획서, 회의록, 제안서, 공문, 보도자료, 기안문, 자유형식\n\n"
                f"내용: {input_data[:300]}"
            ),
            config=types.GenerateContentConfig(max_output_tokens=50),
        )
        answer = resp.text.strip()
        for t in DOC_TYPE_PROMPTS:
            if t in answer:
                return t
        return "자유형식"


# ── OpenRouter ────────────────────────────────────────────────────────────────

class OpenRouterGenerator:
    def __init__(self, api_key: str, model: str = "anthropic/claude-opus-4"):
        from openai import OpenAI
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model

    def generate_streaming(
        self,
        doc_type: str,
        input_type: str,
        input_data: str,
        template_text: str = "",
        extra_instructions: str = "",
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        system = _build_system_prompt(doc_type, template_text)
        user = _build_user_prompt(input_type, input_data, doc_type, extra_instructions)

        full_text = []
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=4096,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_text.append(text)
                if on_chunk:
                    on_chunk(text)
        return "".join(full_text)

    def fill_template_fields(
        self,
        template_text: str,
        fields: list[str],
        doc_type: str,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> dict[str, str]:
        fields_list = "\n".join(f"- {{{{{f}}}}}: {f} 내용" for f in fields)
        system = (
            "당신은 문서 작성 전문가입니다. 템플릿의 각 필드에 들어갈 내용을 생성합니다. "
            "반드시 아래 형식으로만 응답하세요:\nFIELD:필드명\nCONTENT:\n내용\nEND\n\n"
            "각 필드마다 위 형식을 반복합니다."
        )
        user = (
            f"문서 유형: {doc_type}\n작성 맥락: {context}\n\n"
            f"[템플릿]\n{template_text[:1500]}\n\n"
            f"[채워야 할 필드들]\n{fields_list}\n\n각 필드의 적절한 내용을 생성해주세요."
        )
        chunks = []
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=3000,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                chunks.append(text)
                if on_chunk:
                    on_chunk(text)
        return _parse_field_response("".join(chunks), fields)

    def suggest_doc_type(self, input_data: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": (
                f"다음 내용으로 만들기 적합한 문서 유형을 하나만 답하세요.\n"
                f"선택지: 보고서, 계획서, 회의록, 제안서, 공문, 보도자료, 기안문, 자유형식\n\n"
                f"내용: {input_data[:300]}"
            )}],
            max_tokens=50,
        )
        answer = resp.choices[0].message.content.strip()
        for t in DOC_TYPE_PROMPTS:
            if t in answer:
                return t
        return "자유형식"


# ── Factory ──────────────────────────────────────────────────────────────────

def create_generator(provider: str, api_key: str, model: str):
    """provider: 'claude' | 'gemini' | 'openrouter'"""
    if provider == "gemini":
        return GeminiGenerator(api_key=api_key, model=model)
    elif provider == "openrouter":
        return OpenRouterGenerator(api_key=api_key, model=model)
    else:
        return ClaudeGenerator(api_key=api_key or None, model=model)


# 하위 호환 alias
AiGenerator = ClaudeGenerator
