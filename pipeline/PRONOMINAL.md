# Is the card's verb used pronominally in its example?

The batch is a JSON array of Spanish verb cards. Each item has:

- `key`: copy it unchanged into your output
- `verb`: the card's verb in the infinitive
- `example`: the example sentence, the verb occurrence the card is about in `<b>…</b>`
- `senses`: the verb's pronominal senses from Wiktionary (may be empty)

Decide whether that occurrence is pronominal: the verb is used with a pronoun that
refers to its own subject, written onto the verb or before it, possibly before a verb
it depends on ("no **te** vuelvas a **poner** ..." is ponerse; "**me** lo imaginaba"
is imaginarse; "se alimenta de hormigas" is alimentarse). These are NOT pronominal:
passive or impersonal "se" ("se cobran nueve dólares", "no se puede"), a pronoun that is
the object or indirect object of someone else's action ("te demandan", "nos han estado
sometiendo", "se la tacha de ..." where se stands for le).

Write a JSON array with exactly one object per input item, same order, to the output
path given in your task:

- `key`: unchanged.
- `pronominal`: true or false.
- When true, also:
  - `form`: the pronominal infinitive ("ponerse").
  - `sense`: the 0-based index of the fitting entry in `senses`, or null when none fits.
  - `gloss`: a short English gloss of this use, at most about 6 words, fitting the
    example ("to set oneself (goals)"); when `sense` is given, base it on that sense.
  - `pronoun`: the pronoun word exactly as written in the example when it stands apart
    from the verb ("te"), or null when it is written onto the verb ("ponerte").

Rules: valid JSON (UTF-8, no comments). Do not skip or merge items. When unsure whether a
"se" is reflexive or passive/impersonal, answer false.
