# Mark the word in a translated sentence

The batch is a JSON array of example sentences from Spanish videos. Each item has:

- `key`: copy it unchanged into your output
- `sentence_es`: the Spanish sentence, with the word or expression a flashcard teaches in `<b>…</b>`
- `sentence_en`: its English translation, without that marking

For each item, return `sentence_en` with `<b>…</b>` around the English words that
translate the bold Spanish words, and change nothing else: every other character stays
as it is. Where the translation has no words for it, return `sentence_en` unchanged.

Write a JSON array with exactly one object per input item, same order, with the fields
`key` and `sentence_en`.
