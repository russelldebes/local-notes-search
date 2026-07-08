# Note conventions (example)

Copy this file to `conventions.md` and edit it to describe how *you* structure
your notes:

    cp conventions.example.md conventions.md

`conventions.md` is gitignored — it's personal to your vault and never gets
committed. Its contents are appended to the answer-mode system prompt, so the
model interprets your notes the way you actually write them. Keep it short and
concrete; everything you add here is sent with every question.

Delete this example text and replace it with your own. The block below is a
sample of the maintainer's convention — useful as a template:

---

- I keep a large note called **"Working Notes"** that is a running journal.
- New entries are added at the **top**, so the note is in reverse-chronological
  order (most recent day first).
- Each entry is dated. Under a day's date I often have two sections:
  - **Yesterday** — a recap of what I actually did the day before.
  - **Today** — what I plan/planned to do that day.
- So "Yesterday"/"Today" are relative to that entry's date, not to now. When I
  ask what I did on a given day, prefer the "Today" section of that day's entry
  (what I set out to do) and the "Yesterday" section of the *next* day's entry
  (the recap of that same day).
