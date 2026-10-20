# Cutting one batch of examples to whole sentences

The batch is a JSON array of transcript excerpts from Spanish immersion videos on YouTube
(native speakers from Spain and Latin America). Each item has:

- `key`: "lemma|POS" of a vocabulary card, copy it unchanged into your output
- `transcript`: about a minute of speech around one occurrence of the card's word, which
  is marked `<b>…</b>`. Most transcripts come from automatic speech recognition:
  lowercase, without punctuation, accents occasionally missing or wrong words heard.

Write a JSON array with exactly one object per input item, same order, to the output path
given in your task, with these fields:

- `key`: unchanged.
- `sentence_es`: the sentence the bold word belongs to, as the speaker said it, with
  proper capitalisation, punctuation (¿…?, ¡…!, commas, full stop) and accents. Rules:
  - Quote the transcript word for word: the same words in the same order, none added,
    dropped, merged, split or reordered, even where the speaker repeats a word or breaks
    off. Only case, accents and punctuation change; a word you would correct otherwise
    stays as it is.
  - Keep the bold word's `<b>…</b>` around the same word.
  - Start where the sentence starts and end where it ends, even if that lies outside
    what a short excerpt would show. A sentence of fewer than five words takes the next
    (or the previous) sentence along, so the example says something.
  - Spoken sentences run on with "y", "pero", "entonces": cut them at a natural point,
    before a new main clause, so the result stays under about 30 words.
- `sentence_en`: a natural English translation of `sentence_es`, the English equivalent of
  the bold word in `<b>…</b>`. Translate all of it, nothing left out, nothing added.

Rules: output must be valid JSON (UTF-8, no comments, no trailing commas). Do not skip or
merge items.
