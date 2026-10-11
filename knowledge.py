# Собирает постоянную часть базы знаний AlmaU для system prompt.
# Она одинакова для всех пользователей и кэшируется на стороне Anthropic.
# Подробные данные конкретных программ добавляются к каждому вопросу отдельно (см. catalog.py).
import re
from pathlib import Path

from catalog import compact_catalog
from universities import compact_catalog as other_unis_catalog

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_markdown(name: str) -> str:
    text = (KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
    # Убираем HTML-комментарии с подсказками для заполнения.
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def build_knowledge_text() -> str:
    return (
        "<almau_common>\n" + load_markdown("almau_common.md") + "\n</almau_common>\n\n"
        "<almau_catalog>\nКраткий список всех программ бакалавриата "
        "(код | название | название на казахском | срок | предметы ЕНТ и цена в год | траектории):\n"
        + compact_catalog() + "\n</almau_catalog>\n\n"
        "<almau_graduate>\n" + load_markdown("graduate_programs.md") + "\n</almau_graduate>\n\n"
        "<almau_admission>\n" + load_markdown("admission.md") + "\n</almau_admission>\n\n"
        "<almau_grants>\n" + load_markdown("grants_2026.md") + "\n</almau_grants>\n\n"
        "<other_universities>\nДругие вузы в базе (данные из справок команды Pro4U, октябрь 2026; "
        "подробности о программе — в <program_details>):\n\n" + other_unis_catalog() + "\n</other_universities>"
    )
