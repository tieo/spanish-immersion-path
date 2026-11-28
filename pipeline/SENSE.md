# Does each example use the expression in the card's sense?

The batch is a JSON array of flashcards for fixed Spanish expressions. Each item has:

- `key`: copy it unchanged into your output
- `expression`: the expression the card teaches
- `meaning`: its English meaning on the card
- `examples`: sentences from videos in which the expression's words occur, marked with
  `<b>…</b>`; the first is the card's main example

The words of an expression often also occur together without forming it: "en funciones"
is the expression (acting, interim) in "la jefa de turno en funciones", but only the words
"in functions" in "almacenar HTML en funciones" or "se viene en funciones" (with shows).
Captions cut sentences off, so judge from what is there.

For each item, say for every example, in order, whether it uses the expression in the
sense of `meaning` (true) or not (false). Write a JSON array with exactly one object per
input item, same order, with the fields `key` and `fits` (an array of true/false, one per
example).
