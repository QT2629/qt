# Битва идей: много копий Claude развивают твою идею, сильнейшие выживают
# (эволюция), потом турнир на выбывание и финал перед жюри.
#
# Запуск:
#   python battle.py "моя идея"
#   python battle.py --file idea.txt
#   python battle.py "моя идея" --agents 100 --generations 3
#   python battle.py "моя идея" --dry-run       (только оценка стоимости, без запросов)
#
# Нужен ANTHROPIC_API_KEY — в файле .env или в переменных окружения.
# Результат: папка battle_results/<дата-время>/ с report.md и ideas.json.
import argparse
import asyncio
import json
import os
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# $ за 1M токенов: (вход, выход)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
}

# Модели, для которых включаем автоматическую запасную модель при отказе
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

# Роли тех, кто придумывает версии идеи
PERSONAS = [
    "опытный предприниматель, запустивший 5 бизнесов",
    "маркетолог, который умеет продавать что угодно",
    "инженер, думающий о том, как это реально построить",
    "инвестор венчурного фонда",
    "будущий клиент, который платит своими деньгами",
    "скептик, который ищет, почему всё провалится, и чинит это",
    "дизайнер продукта, помешанный на удобстве",
    "специалист по продажам B2B",
    "блогер с большой аудиторией",
    "экономист, считающий юнит-экономику",
    "человек из другой страны, смотрящий на рынок со стороны",
    "студент, который хочет заработать без стартового капитала",
]

# Дополнительные углы, чтобы версии не были одинаковыми
ANGLES = [
    "сделай это как можно дешевле на старте",
    "сделай премиальную версию для богатых клиентов",
    "сделай версию для бизнеса (B2B), а не для людей",
    "добавь онлайн-составляющую или приложение",
    "сделай так, чтобы клиенты сами приводили новых клиентов",
    "сделай модель подписки",
    "найди неочевидную целевую аудиторию",
    "сделай версию, которую можно запустить за 2 недели",
    "сделай версию, которую можно масштабировать на другие страны",
    "объедини идею с партнёрством с крупной компанией",
    "убери всё лишнее и оставь самое ядро",
    "сделай самую смелую версию, которую никто не ожидает",
]

# Жюри финала
JURY = [
    "инвестор, который решает, вложить ли свои деньги",
    "будущий клиент, который решает, заплатить ли",
    "опытный предприниматель-скептик, видевший сотни провалов",
]

CRITERIA = (
    "реалистичность запуска, потенциал дохода или пользы, отличие от конкурентов, "
    "понятность первых шагов. Не выбирай версию за длину текста или красивые слова"
)

FORMAT = (
    "Ответь строго в формате:\n"
    "НАЗВАНИЕ: <короткое название, до 8 слов>\n"
    "<описание, 120–200 слов: для кого, что именно делаем, как зарабатываем, "
    "почему это сработает, первый шаг>"
)


@dataclass
class Idea:
    id: int
    title: str
    text: str
    origin: str
    generation: int
    wins: list[str] = field(default_factory=list)

    def show(self) -> str:
        return f"{self.title}\n{self.text}"


class OutOfIdeas(Exception):
    """Все запросы на создание версий провалились."""


class Arena:
    def __init__(self, idea: str, worker: str, judge: str, concurrency: int):
        self.idea = idea
        self.worker = worker
        self.judge = judge
        self.client = anthropic.AsyncAnthropic(max_retries=5, timeout=600.0)
        self.sem = asyncio.Semaphore(concurrency)
        self.ideas: list[Idea] = []
        self.cost = 0.0
        self.calls = 0
        self.failed = 0
        self.log: list[str] = []

    # --- запросы к Claude ---

    async def ask(self, model: str, prompt: str, effort: str) -> str:
        params = dict(
            model=model,
            max_tokens=16000,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
        )
        async with self.sem:
            try:
                if model in FALLBACK_MODELS:
                    response = await self.client.beta.messages.create(
                        **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                    )
                else:
                    response = await self.client.messages.create(**params)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                    anthropic.NotFoundError, anthropic.BadRequestError):
                raise  # ключ или модель неверные — продолжать бессмысленно
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                # SDK уже повторил запрос несколько раз; пропускаем этот вызов
                self.failed += 1
                print(f"\n  ! запрос не удался: {e}", file=sys.stderr)
                return ""
        self.calls += 1
        price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])
        usage = response.usage
        self.cost += (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
        if response.stop_reason == "refusal":
            self.failed += 1
            return ""
        return "".join(b.text for b in response.content if b.type == "text").strip()

    async def run_all(self, label: str, coros: list) -> list:
        """Запускает запросы параллельно и показывает прогресс."""
        done = 0
        total = len(coros)

        async def track(coro):
            nonlocal done
            result = await coro
            done += 1
            print(f"\r  {label}: {done}/{total}   (потрачено ~${self.cost:.2f})", end="", flush=True)
            return result

        results = await asyncio.gather(*(track(c) for c in coros))
        print()
        return results

    # --- создание версий ---

    def add_idea(self, raw: str, origin: str, generation: int) -> Idea | None:
        if not raw:
            return None
        match = re.search(r"НАЗВАНИЕ:\s*(.+)", raw)
        if match:
            title = match.group(1).strip().strip("*")
            text = raw[match.end():].strip()
        else:
            title, text = raw.split("\n", 1)[0][:80], raw
        idea = Idea(len(self.ideas) + 1, title, text, origin, generation)
        self.ideas.append(idea)
        return idea

    async def generate(self, count: int) -> list[Idea]:
        async def one():
            persona = random.choice(PERSONAS)
            angle = random.choice(ANGLES)
            prompt = (
                f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
                f"Ты — {persona}. Предложи свою, самую сильную версию развития этой идеи.\n"
                f"Дополнительный угол: {angle}.\n"
                "Не пересказывай исходную идею — улучши её и сделай конкретной.\n\n" + FORMAT
            )
            raw = await self.ask(self.worker, prompt, "low")
            return self.add_idea(raw, f"создана: {persona}; угол: {angle}", 1)

        ideas = await self.run_all("Создание версий", [one() for _ in range(count)])
        return [i for i in ideas if i]

    async def offspring(self, survivors: list[Idea], count: int, generation: int) -> list[Idea]:
        async def crossover(a: Idea, b: Idea):
            prompt = (
                f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
                "Две сильные версии её развития прошли отбор:\n\n"
                f"[A]\n{a.show()}\n\n[B]\n{b.show()}\n\n"
                "Создай новую версию, которая объединяет лучшее из обеих в одну цельную идею "
                "(не просто склейку двух текстов) и сильнее каждой из них.\n\n" + FORMAT
            )
            raw = await self.ask(self.worker, prompt, "low")
            return self.add_idea(raw, f"скрещивание #{a.id} + #{b.id}", generation)

        async def mutation(a: Idea):
            prompt = (
                f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
                f"Эта версия её развития прошла отбор:\n\n{a.show()}\n\n"
                "Найди её самое слабое место и создай улучшенную версию, которая его устраняет. "
                "Можешь смело изменить одну ключевую деталь: аудиторию, модель дохода, "
                "канал продаж или формат.\n\n" + FORMAT
            )
            raw = await self.ask(self.worker, prompt, "low")
            return self.add_idea(raw, f"мутация #{a.id}", generation)

        coros = []
        for _ in range(count):
            if len(survivors) >= 2 and random.random() < 0.5:
                coros.append(crossover(*random.sample(survivors, 2)))
            else:
                coros.append(mutation(random.choice(survivors)))
        children = await self.run_all(f"Поколение {generation}: потомки", coros)
        return [c for c in children if c]

    # --- отбор ---

    async def select(self, population: list[Idea], group_size: int, generation: int) -> list[Idea]:
        """Делит версии на группы, из каждой группы выживает одна."""
        population = population[:]
        random.shuffle(population)
        groups = [population[i:i + group_size] for i in range(0, len(population), group_size)]

        async def judge_group(group: list[Idea]) -> Idea:
            if len(group) == 1:
                return group[0]
            listing = "\n\n".join(f"[{n}] {idea.show()}" for n, idea in enumerate(group, 1))
            prompt = (
                f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
                f"Ниже {len(group)} версий её развития. Выбери ОДНУ самую сильную. "
                f"Критерии: {CRITERIA}.\n\n{listing}\n\n"
                "Кратко (2–3 предложения) объясни выбор. "
                "Последней строкой напиши: ПОБЕДИТЕЛЬ: <номер>"
            )
            raw = await self.ask(self.worker, prompt, "medium")
            match = re.findall(r"ПОБЕДИТЕЛЬ:\s*\[?(\d+)", raw)
            if match and 1 <= int(match[-1]) <= len(group):
                winner = group[int(match[-1]) - 1]
            else:
                winner = random.choice(group)  # судья не ответил — выбираем случайно
            winner.wins.append(f"поколение {generation}: лучшая в группе из {len(group)}")
            return winner

        return await self.run_all(f"Поколение {generation}: отбор", [judge_group(g) for g in groups])

    # --- турнир ---

    def match_prompt(self, a: Idea, b: Idea, role: str | None = None) -> str:
        who = f"Ты — {role}. " if role else ""
        return (
            f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
            f"{who}Две версии её развития сражаются в турнире. Выбери более сильную. "
            f"Критерии: {CRITERIA}.\n\n[A]\n{a.show()}\n\n[B]\n{b.show()}\n\n"
            "Кратко (3–5 предложений) объясни выбор. Последней строкой напиши: ПОБЕДИТЕЛЬ: A или ПОБЕДИТЕЛЬ: B"
        )

    @staticmethod
    def parse_ab(raw: str) -> str | None:
        match = re.findall(r"ПОБЕДИТЕЛЬ:\s*\[?([AB])", raw)
        return match[-1] if match else None

    async def match(self, a: Idea, b: Idea, round_name: str) -> Idea:
        if random.random() < 0.5:  # случайный порядок, чтобы судья не выбирал по позиции
            a, b = b, a
        raw = await self.ask(self.judge, self.match_prompt(a, b), "medium")
        choice = self.parse_ab(raw) or random.choice("AB")
        winner, loser = (a, b) if choice == "A" else (b, a)
        winner.wins.append(f"{round_name}: победила #{loser.id}")
        self.log.append(f"- {round_name}: **#{winner.id} {winner.title}** победила #{loser.id} {loser.title}")
        return winner

    async def final(self, a: Idea, b: Idea) -> tuple[Idea, list[str]]:
        async def juror(role: str):
            x, y = (a, b) if random.random() < 0.5 else (b, a)
            raw = await self.ask(self.judge, self.match_prompt(x, y, role), "high")
            choice = self.parse_ab(raw) or random.choice("AB")
            winner = x if choice == "A" else y
            reason = re.sub(r"\n?ПОБЕДИТЕЛЬ:.*", "", raw).strip()
            return winner, f"**{role}** → #{winner.id}: {reason}"

        votes = await self.run_all("Финал: жюри", [juror(r) for r in JURY])
        a_votes = sum(1 for w, _ in votes if w is a)
        winner, loser = (a, b) if a_votes * 2 > len(votes) else (b, a)
        winner.wins.append(f"финал: победила #{loser.id} ({max(a_votes, len(votes) - a_votes)}:{min(a_votes, len(votes) - a_votes)})")
        self.log.append(f"- Финал: **#{winner.id} {winner.title}** победила #{loser.id} {loser.title}")
        return winner, [reason for _, reason in votes]

    async def tournament(self, players: list[Idea]) -> tuple[Idea, Idea | None, list[str]]:
        players = players[:]
        random.shuffle(players)
        round_no = 1
        while len(players) > 2:
            name = f"Раунд {round_no}"
            self.log.append(f"\n**{name}** ({len(players)} участников)")
            bye = players.pop() if len(players) % 2 else None
            pairs = [(players[i], players[i + 1]) for i in range(0, len(players), 2)]
            players = await self.run_all(f"Турнир, {name.lower()}", [self.match(a, b, name) for a, b in pairs])
            if bye:
                bye.wins.append(f"{name}: прошла без боя")
                self.log.append(f"- {name}: #{bye.id} {bye.title} проходит без боя")
                players.append(bye)
            round_no += 1
        if len(players) == 1:
            return players[0], None, []
        self.log.append("\n**Финал** (жюри из 3 судей)")
        winner, verdicts = await self.final(*players)
        runner_up = players[0] if players[1] is winner else players[1]
        return winner, runner_up, verdicts

    async def summary(self, winner: Idea) -> str:
        prompt = (
            f"Исходная идея пользователя:\n<idea>\n{self.idea}\n</idea>\n\n"
            f"Эта версия победила в турнире среди {len(self.ideas)} версий:\n\n{winner.show()}\n\n"
            "Напиши итог для автора идеи:\n"
            "1. Суть победившей версии в 2–3 предложениях.\n"
            "2. Почему она сильнее исходной идеи.\n"
            "3. Три главных риска и как их снизить.\n"
            "4. Первые 3 конкретных шага на ближайшие 2 недели."
        )
        return await self.ask(self.judge, prompt, "high")


def estimate(agents: int, generations: int, group: int, worker: str, judge: str) -> tuple[int, float]:
    """Грубая оценка числа запросов и стоимости (токены вместе с размышлениями модели)."""
    survivors = -(-agents // group)

    def cost(model: str, calls: int, tokens_in: int, tokens_out: int) -> float:
        price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])
        return calls * (tokens_in * price_in + tokens_out * price_out) / 1_000_000

    gen_calls = agents
    select_calls = generations * survivors
    child_calls = (generations - 1) * (agents - survivors)
    match_calls = max(survivors - 2, 0)
    final_calls = len(JURY) + 1
    total = (
        cost(worker, gen_calls, 400, 1200)
        + cost(worker, select_calls, 2000, 1000)
        + cost(worker, child_calls, 900, 1200)
        + cost(judge, match_calls, 1000, 1500)
        + cost(judge, final_calls, 1000, 2500)
    )
    return gen_calls + select_calls + child_calls + match_calls + final_calls, total


def write_report(arena: Arena, winner: Idea, runner_up: Idea | None, verdicts: list[str],
                 summary: str, history: list[list[Idea]]) -> Path:
    folder = Path("battle_results") / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Битва идей",
        "",
        f"**Исходная идея:** {arena.idea}",
        "",
        f"Версий создано: {len(arena.ideas)} · запросов: {arena.calls} · "
        f"неудачных: {arena.failed} · стоимость: ~${arena.cost:.2f}",
        f"Модели: создание и отбор — `{arena.worker}`, турнир и финал — `{arena.judge}`",
        "",
        f"## 🏆 Победитель: #{winner.id} {winner.title}",
        "",
        winner.text,
        "",
        f"*Происхождение:* {winner.origin}",
        "",
        "*Путь к победе:*",
        *[f"- {w}" for w in winner.wins],
        "",
        "## Итог и первые шаги",
        "",
        summary or "(не удалось получить итог)",
    ]
    if runner_up:
        lines += ["", f"## 🥈 Второе место: #{runner_up.id} {runner_up.title}", "", runner_up.text]
    if verdicts:
        lines += ["", "## Мнения жюри в финале", ""] + [f"- {v}" for v in verdicts]
    lines += ["", "## Турнирная сетка", *arena.log]
    for n, survivors in enumerate(history, 1):
        lines += ["", f"## Выжившие в поколении {n}", ""]
        lines += [f"- #{i.id} {i.title} — *{i.origin}*" for i in survivors]
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "ideas.json").write_text(
        json.dumps([asdict(i) for i in arena.ideas], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


async def run(args, idea: str) -> None:
    arena = Arena(idea, args.worker, args.judge, args.concurrency)

    print(f"\n🧬 Эволюция: {args.agents} версий, {args.generations} поколения")
    population = await arena.generate(args.agents)
    if not population:
        raise OutOfIdeas()
    history = []
    for generation in range(1, args.generations + 1):
        survivors = await arena.select(population, args.group, generation)
        history.append(survivors)
        print(f"  выжило: {len(survivors)}")
        if generation == args.generations:
            break
        children = await arena.offspring(survivors, args.agents - len(survivors), generation + 1)
        population = survivors + children

    print(f"\n⚔️  Турнир: {len(survivors)} участников")
    winner, runner_up, verdicts = await arena.tournament(survivors)

    print("\n📝 Итоговый разбор победителя")
    summary = await arena.summary(winner)

    folder = write_report(arena, winner, runner_up, verdicts, summary, history)
    print("\n" + "=" * 60)
    print(f"🏆 ПОБЕДИТЕЛЬ: {winner.title}\n")
    print(winner.text)
    if summary:
        print("\n" + summary)
    print("=" * 60)
    print(f"\nПотрачено: ~${arena.cost:.2f} · запросов: {arena.calls} · неудачных: {arena.failed}")
    print(f"Полный отчёт: {folder / 'report.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Битва идей: эволюция + турнир копий Claude")
    parser.add_argument("idea", nargs="?", help="твоя идея (в кавычках)")
    parser.add_argument("--file", help="прочитать идею из текстового файла")
    parser.add_argument("--agents", type=int, default=100, help="сколько версий в поколении (по умолчанию 100)")
    parser.add_argument("--generations", type=int, default=3, help="сколько поколений эволюции (по умолчанию 3)")
    parser.add_argument("--group", type=int, default=5, help="из группы такого размера выживает одна (по умолчанию 5)")
    parser.add_argument("--worker", default="claude-haiku-5-5", help="модель для создания и отбора версий")
    parser.add_argument("--judge", default="claude-opus-5-5", help="модель для турнира и финала")
    parser.add_argument("--concurrency", type=int, default=10, help="сколько запросов одновременно")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    parser.add_argument("--dry-run", action="store_true", help="только показать оценку стоимости")
    args = parser.parse_args()

    if args.file:
        idea = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.idea:
        idea = args.idea.strip()
    else:
        idea = input("Опиши свою идею: ").strip()
    if not idea:
        sys.exit("Идея не задана.")
    if args.agents < 2 or args.generations < 1 or args.group < 2:
        sys.exit("Нужно: --agents от 2, --generations от 1, --group от 2.")

    calls, cost = estimate(args.agents, args.generations, args.group, args.worker, args.judge)
    print(f"Идея: {idea}")
    print(f"Версий: {args.agents}, поколений: {args.generations}, выживает 1 из {args.group}")
    print(f"Модели: создание/отбор — {args.worker}, турнир/финал — {args.judge}")
    print(f"Примерно запросов: {calls}, стоимость: ~${cost:.2f} (оценка, может отличаться в 2 раза)")
    if args.dry_run:
        return

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Не найден ANTHROPIC_API_KEY. Добавь его в файл .env или выполни: export ANTHROPIC_API_KEY=sk-ant-...")
    if not args.yes and input("Запустить? [y/N] ").strip().lower() not in ("y", "yes", "д", "да"):
        return

    try:
        asyncio.run(run(args, idea))
    except anthropic.AuthenticationError:
        sys.exit("\nНеверный ANTHROPIC_API_KEY.")
    except (anthropic.NotFoundError, anthropic.BadRequestError, anthropic.PermissionDeniedError) as e:
        sys.exit(f"\nОшибка API (проверь название модели и доступ): {e}")
    except OutOfIdeas:
        sys.exit("\nНе удалось создать ни одной версии — проверь интернет и ключ.")
    except KeyboardInterrupt:
        sys.exit("\nОстановлено.")


if __name__ == "__main__":
    main()
