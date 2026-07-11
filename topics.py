LEXICAL_TOPICS = [
    "Административные процедуры и документы",
    "Больница, врач и аптека",
    "Стоматолог и запись на приём",
    "Парикмахерская и уход за собой",
    "Отпуск, каникулы и путешествия",
    "Париж: транспорт, районы и повседневная жизнь",
    "Ницца: море, погода и отдых",
    "Булочная: багет, круассан и заказ",
    "Сыр, рынок и продукты",
    "Жильё, аренда и бытовые проблемы",
    "Работа, вакансии и собеседование",
    "Ресторан, кафе и покупки",
]

PRONOUN_TOPICS = [
    "COD: le, la, les",
    "COI: lui, leur",
    "Pronoms EN et Y",
    "DONT",
    "AUQUEL, DUQUEL и формы",
    "Относительные местоимения qui, que, où",
    "Двойные местоимения",
    "Артикли: défini, indéfini, partitif, contracté",
]


def working_day_index(target_date) -> int:
    start = target_date.replace(month=1, day=1)
    days = (target_date - start).days + 1
    count = 0
    for offset in range(days):
        current = start.fromordinal(start.toordinal() + offset)
        if current.weekday() < 6:
            count += 1
    return count


def third_question_plan(target_date, session: str) -> tuple[str, str]:
    index = working_day_index(target_date)
    # Alternate lexicon and grammar/pronouns across weekdays.
    if index % 2 == 1:
        topic = LEXICAL_TOPICS[(index - 1 + (0 if session == "morning" else 5)) % len(LEXICAL_TOPICS)]
        return "lexicon", topic
    topic = PRONOUN_TOPICS[(index - 1 + (0 if session == "morning" else 3)) % len(PRONOUN_TOPICS)]
    return "grammar_pronouns", topic
