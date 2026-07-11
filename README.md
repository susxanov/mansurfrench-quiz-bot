# Mansur French Quiz Bot v3.0

## Production behavior

- Monday to Saturday; Sunday off.
- Morning review at 09:00 Europe/Paris: 3 questions, A1–A2.
- Evening review at 19:30 Europe/Paris: 3 questions, B1–B2.
- The bot sends the questions privately to the administrator first.
- Publication to `@mansurfrench` happens only after pressing **Подтвердить**.
- Each block contains:
  1. Russian → French translation;
  2. verb conjugation in context;
  3. rotating lexicon or grammar/pronouns.
- 12 lexical themes rotate.
- Questions are independently reviewed before storage.
- Exact duplicates are blocked across the whole database.
- Correct answers are programmatically rotated across positions.
- No `Exercice`, numbering, or generator labels are allowed in poll questions.
- Telegram quiz explanations are included.

## Railway variables

Use the variables from `.env.example`.
Keep the existing PostgreSQL service and set its `DATABASE_URL`.

## Admin commands

- `/status`
- `/prepare morning`
- `/prepare evening`
- `/pending`
- `/pause`
- `/resume`

## Weekend production-cycle test

- `/force morning` — runs the complete A1–A2 approval flow even on Saturday/Sunday.
- `/force evening` — runs the complete B1–B2 approval flow even on Saturday/Sunday.
- These commands are admin-only and do not change the Monday–Saturday scheduler.
- The regenerate button preserves force mode during the weekend test.
