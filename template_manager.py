"""
Template management: create, list, load HWP templates with {{field}} markers.
"""
import json
import os
import re
import struct
import zlib
from pathlib import Path
from typing import Optional


TEMPLATES_DIR = Path(__file__).parent / "templates"
META_FILE = TEMPLATES_DIR / "meta.json"

# Built-in template definitions (plain text, no HWP required)
BUILTIN_TEMPLATES = {
    "보고서_기본": {
        "name": "보고서 (기본)",
        "doc_type": "보고서",
        "description": "일반 업무 보고서 템플릿",
        "content": """{{제목}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
보 고 서
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ 보고 일자: {{보고일자}}
□ 보고 부서: {{부서명}}
□ 보고 자:  {{보고자}}

1. 개요
{{개요}}

2. 주요 내용
{{주요내용}}

3. 향후 계획
{{향후계획}}

4. 결론
{{결론}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "계획서_기본": {
        "name": "계획서 (기본)",
        "doc_type": "계획서",
        "description": "사업/업무 계획서 템플릿",
        "content": """{{제목}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
업무 계획서
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ 작성일: {{작성일}}
□ 담당자: {{담당자}}
□ 부  서: {{부서명}}

1. 추진 배경 및 목적
{{추진배경}}

2. 현황 분석
{{현황분석}}

3. 세부 추진 계획
{{세부계획}}

4. 소요 예산
{{소요예산}}

5. 기대 효과
{{기대효과}}

6. 추진 일정
{{추진일정}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "회의록_기본": {
        "name": "회의록 (기본)",
        "doc_type": "회의록",
        "description": "표준 회의록 템플릿",
        "content": """회 의 록

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
□ 회의명:   {{회의명}}
□ 일  시:   {{일시}}
□ 장  소:   {{장소}}
□ 참석자:   {{참석자}}
□ 작성자:   {{작성자}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【 안 건 】
{{안건}}

【 논의 내용 】
{{논의내용}}

【 결정 사항 】
{{결정사항}}

【 후속 조치 】
{{후속조치}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "제안서_기본": {
        "name": "제안서 (기본)",
        "doc_type": "제안서",
        "description": "사업 제안서 템플릿",
        "content": """{{제안서제목}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
제 안 서
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ 제안일: {{제안일}}
□ 제안자: {{제안자}}
□ 수  신: {{수신자}}

1. 제안 배경
{{제안배경}}

2. 현황 및 문제점
{{현황문제점}}

3. 제안 내용
{{제안내용}}

4. 기대 효과
{{기대효과}}

5. 소요 비용 및 일정
{{비용일정}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "공문_기본": {
        "name": "공문 (기본)",
        "doc_type": "공문",
        "description": "표준 공문 템플릿",
        "content": """수  신: {{수신}}
참  조: {{참조}}
제  목: {{제목}}

{{본문내용}}

끝.

{{작성기관}}
{{담당자직책}} {{담당자성명}} (인)
연락처: {{연락처}}
""",
    },
    "빈문서": {
        "name": "빈 문서",
        "doc_type": "자유형식",
        "description": "템플릿 없이 자유롭게 생성",
        "content": "{{전체내용}}",
    },
}


class TemplateManager:
    def __init__(self):
        TEMPLATES_DIR.mkdir(exist_ok=True)
        self._meta: dict = self._load_meta()

    def _load_meta(self) -> dict:
        if META_FILE.exists():
            try:
                return json.loads(META_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {}

    def _save_meta(self):
        META_FILE.write_text(json.dumps(self._meta, ensure_ascii=False, indent=2), encoding='utf-8')

    def list_templates(self) -> list[dict]:
        templates = []
        # Built-in
        for key, t in BUILTIN_TEMPLATES.items():
            templates.append({
                "id": key,
                "name": t["name"],
                "doc_type": t["doc_type"],
                "description": t["description"],
                "builtin": True,
                "path": None,
            })
        # User templates from files
        for hwp_path in sorted(TEMPLATES_DIR.glob("*.hwp")):
            tid = hwp_path.stem
            meta = self._meta.get(tid, {})
            templates.append({
                "id": tid,
                "name": meta.get("name", tid),
                "doc_type": meta.get("doc_type", "자유형식"),
                "description": meta.get("description", ""),
                "builtin": False,
                "path": str(hwp_path),
            })
        # User plain text templates
        for txt_path in sorted(TEMPLATES_DIR.glob("*.txt")):
            tid = txt_path.stem
            meta = self._meta.get(tid, {})
            templates.append({
                "id": tid,
                "name": meta.get("name", tid),
                "doc_type": meta.get("doc_type", "자유형식"),
                "description": meta.get("description", ""),
                "builtin": False,
                "path": str(txt_path),
            })
        return templates

    def get_template(self, template_id: str) -> dict:
        """Return template dict with 'content' and 'fields' populated."""
        # Built-in
        if template_id in BUILTIN_TEMPLATES:
            t = BUILTIN_TEMPLATES[template_id].copy()
            t["fields"] = self._extract_fields(t["content"])
            t["id"] = template_id
            t["builtin"] = True
            return t

        # File-based
        meta = self._meta.get(template_id, {})
        txt_path = TEMPLATES_DIR / f"{template_id}.txt"
        hwp_path = TEMPLATES_DIR / f"{template_id}.hwp"

        if txt_path.exists():
            content = txt_path.read_text(encoding='utf-8')
        elif hwp_path.exists():
            content = self._read_hwp_text(str(hwp_path))
        else:
            raise FileNotFoundError(f"템플릿을 찾을 수 없습니다: {template_id}")

        return {
            "id": template_id,
            "name": meta.get("name", template_id),
            "doc_type": meta.get("doc_type", "자유형식"),
            "description": meta.get("description", ""),
            "content": content,
            "fields": self._extract_fields(content),
            "builtin": False,
        }

    def save_template(self, name: str, doc_type: str, content: str,
                      description: str = "") -> str:
        """Save a new plain-text template. Returns template_id."""
        # Slugify name for filename
        tid = re.sub(r'[^\w가-힣]', '_', name).strip('_') or "template"
        # Avoid collisions
        base = tid
        i = 1
        while (TEMPLATES_DIR / f"{tid}.txt").exists() or tid in BUILTIN_TEMPLATES:
            tid = f"{base}_{i}"; i += 1

        path = TEMPLATES_DIR / f"{tid}.txt"
        path.write_text(content, encoding='utf-8')
        self._meta[tid] = {"name": name, "doc_type": doc_type, "description": description}
        self._save_meta()
        return tid

    def delete_template(self, template_id: str) -> bool:
        if template_id in BUILTIN_TEMPLATES:
            return False
        deleted = False
        for ext in (".txt", ".hwp"):
            p = TEMPLATES_DIR / f"{template_id}{ext}"
            if p.exists():
                p.unlink(); deleted = True
        if template_id in self._meta:
            del self._meta[template_id]
            self._save_meta()
        return deleted

    def apply_fields(self, template_content: str, field_values: dict[str, str]) -> str:
        """Replace {{field}} with values."""
        result = template_content
        for key, value in field_values.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        return result

    @staticmethod
    def _extract_fields(content: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r'\{\{(\w+)\}\}', content)))

    @staticmethod
    def _read_hwp_text(path: str) -> str:
        """Read text from HWP file without COM."""
        try:
            from hwp_controller import HwpFileReader
            reader = HwpFileReader(path)
            return reader.read_all_text()
        except Exception:
            return ""
