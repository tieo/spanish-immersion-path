# Would a learner understand this word on first hearing?

The learner speaks German and English and is learning Spanish. The batch is a JSON array
of flashcards. Each item has:

- `key`: copy it unchanged into your output
- `word`: the Spanish word or fixed expression, nouns with their article
- `meaning`: its English meaning on the card
- `example`: a sentence it is heard in, the word in `<b>…</b>`

Decide whether the card is `obvious`: a learner who knows English and German but this
word not would still understand it right away in that sentence, from its sound and
spelling, because it is the same word in English or German with at most regular Spanish
endings and spelling (turístico, información, posible, el hotel, la televisión, el
Kindergarten). It is not obvious when:

- the shared word means something else here or in general (embarazada is pregnant, not
  embarrassed; actual is current; la librería is a bookshop; constipado has a cold),
- the resemblance only shows in writing or only to someone who knows Latin or French,
  or is distant (el ayuntamiento, la ventana, aprovechar),
- it is a fixed expression whose whole meaning does not follow from obvious words.

Write a JSON array with exactly one object per input item, same order, with the fields
`key` and `obvious` (true or false).
