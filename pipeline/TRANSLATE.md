# Translating one vocabulary batch

The batch is a JSON array of Spanish words heard in Spanish immersion videos on YouTube
(Easy Spanish, Dreaming Spanish, Spanish After Hours: native speakers from Spain and Latin
America, from beginner to advanced level). Each item has:

- `key`: "lemma|POS", copy it unchanged into your output
- `lemma`: the dictionary form spaCy produced, lowercase, sometimes wrong
- `pos`: spaCy part of speech (NOUN, VERB, AUX, ADJ, ADV, ADP, PRON, DET, CCONJ, SCONJ)
- `forms`: the inflected forms actually heard, most frequent first
- `example_es`: one stretch of speech where the word occurs, the occurrence in `<b>…</b>`.
  It comes from automatic speech recognition: lowercase, no punctuation, sometimes cut
  mid-sentence, accents occasionally missing.

Write a JSON array with exactly one object per input item, same order, to the output path
given in your task, with these fields:

- `key`: unchanged.
- `keep`: `false` if the item is not a real Spanish word (speech-recognition garbage), a
  proper noun or name, an English word, a pure interjection, or a lemma so wrong that the
  correct word cannot be recovered from `forms` and `example_es`; otherwise `true`.
- `word`: the correct dictionary headword with proper accents and spelling. Fix spaCy
  errors (e.g. "estár" -> "estar", a noun lemmatised to the wrong gender). Nouns get their
  article: "el día", "la mano", "el/la estudiante" for common gender, "los/las" only for
  plural-only words. Adjectives in masculine singular. Verbs in the infinitive; a verb used
  only reflexively gets "-se" ("acostarse"). If `forms` show that the series really uses a
  different word than the lemma (e.g. lemma "ir" from "fue" meaning "was"), set `word` to
  the word actually meant.
- `meaning`: a short English gloss, at most about 6 words, for the sense used in
  `example_es` first; add a second common sense after "; " only if it is frequent. Mark
  regional words: "(Spain)", "(Latin America)", "(Mexico)", "(Colombia)", "(Argentina)".
- `example_en`: a natural English translation of `example_es` as a whole, with the
  English equivalent of the bold word in `<b>…</b>`. Where the Spanish snippet is
  fragmentary, translate the fragment faithfully; do not invent missing context.

Rules: output must be valid JSON (UTF-8, no comments, no trailing commas). Do not skip or
merge items. Do not add fields. Accuracy over speed: if a gloss is uncertain, choose the
meaning that fits `example_es`.
