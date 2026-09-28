# Загружает базу знаний AlmaU из папки knowledge/ и превращает её в текст для Claude.
# Чтобы обновить данные — отредактируйте файлы в knowledge/ и перезапустите бота.
import json
import re
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_programs() -> list[dict]:
    """Каждая программа — отдельный JSON-файл в папке knowledge/programs/."""
    programs = []
    for path in sorted((KNOWLEDGE_DIR / "programs").glob("*.json")):
        programs.append(json.loads(path.read_text(encoding="utf-8")))
    return programs


def load_markdown(name: str) -> str:
    text = (KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
    # Убираем HTML-комментарии с подсказками для заполнения.
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def build_knowledge_text() -> str:
    programs = load_programs()
    common = load_markdown("almau_common.md")
    graduate = load_markdown("graduate_programs.md")
    admission = load_markdown("admission.md")

    programs_text = (
        json.dumps(programs, ensure_ascii=False, separators=(",", ":"))
        if programs
        else "ДАННЫХ О ПРОГРАММАХ ПОКА НЕТ. На вопросы о конкретных программах, баллах "
        "и стоимости отвечай, что информация уточняется, и направляй в приёмную комиссию."
    )
    admission_text = admission or (
        "ДАННЫХ О ПОСТУПЛЕНИИ ПОКА НЕТ. На вопросы о сроках, документах и грантах "
        "направляй в приёмную комиссию."
    )
    return (
        "<almau_common>\n" + common + "\n</almau_common>\n\n"
        "<almau_programs>\n" + programs_text + "\n</almau_programs>\n\n"
        "<almau_graduate>\n" + graduate + "\n</almau_graduate>\n\n"
        "<almau_admission>\n" + admission_text + "\n</almau_admission>"
    )
