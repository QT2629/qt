# Загружает базу знаний AlmaU из папки knowledge/ и превращает её в текст для Claude.
# Чтобы обновить данные — отредактируйте файлы в knowledge/ и перезапустите бота.
import json
import re
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_programs() -> list[dict]:
    path = KNOWLEDGE_DIR / "programs.json"
    programs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(programs, list):
        raise ValueError("knowledge/programs.json должен содержать список [ ... ]")
    return programs


def load_admission_info() -> str:
    text = (KNOWLEDGE_DIR / "admission.md").read_text(encoding="utf-8")
    # Убираем HTML-комментарии с подсказками для заполнения.
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def build_knowledge_text() -> str:
    programs = load_programs()
    admission = load_admission_info()

    programs_text = (
        json.dumps(programs, ensure_ascii=False, indent=1)
        if programs
        else "ДАННЫХ О ПРОГРАММАХ ПОКА НЕТ. На вопросы о конкретных программах, баллах "
        "и стоимости отвечай, что информация уточняется, и направляй в приёмную комиссию."
    )
    admission_text = admission or (
        "ДАННЫХ О ПОСТУПЛЕНИИ ПОКА НЕТ. На вопросы о сроках, документах и грантах "
        "направляй в приёмную комиссию."
    )
    return (
        "<almau_programs>\n" + programs_text + "\n</almau_programs>\n\n"
        "<almau_admission>\n" + admission_text + "\n</almau_admission>"
    )
