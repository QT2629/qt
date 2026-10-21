# Собирает постоянную часть базы знаний для system prompt: все вузы на равных.
# Она одинакова для всех пользователей и кэшируется на стороне Anthropic.
# Подробные данные конкретных программ добавляются к каждому вопросу отдельно (см. universities.py).
import re
from pathlib import Path

from universities import compact_catalog

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_markdown(name: str) -> str:
    text = (KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
    # Убираем HTML-комментарии с подсказками для заполнения.
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def almau_details() -> str:
    """Подробности AlmaU (учебные планы, магистратура, документы) — добавляются к вопросу, только когда речь об AlmaU,
    чтобы в общих советах у AlmaU не было «лишнего веса» перед другими вузами."""
    return (load_markdown("almau_common.md") + "\n\n" + load_markdown("graduate_programs.md") + "\n\n"
            + load_markdown("admission.md"))


def build_knowledge_text() -> str:
    return (
        "<universities>\nВсе вузы в базе (программы и подробности — в <program_details> к каждому вопросу):\n\n"
        + compact_catalog() + "\n</universities>\n\n"
        "<grants_2026>\n" + load_markdown("grants_2026.md") + "\n</grants_2026>\n\n"
        "<admission_basics>\nОбщее для всех вузов: документы и сроки поступления\n\n"
        + load_markdown("static/documents_ru.md") + "\n\n" + load_markdown("static/dates_ru.md") + "\n</admission_basics>"
    )
