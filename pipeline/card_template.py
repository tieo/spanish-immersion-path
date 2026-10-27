"""How a word card looks: the one template of the note type "Spanish Immersion Word".

pipeline/deck.py builds the deck with it, and the learner's app (server/collection.py)
brings the note type in the learner's collection up to it, so a change here reaches the
cards already in Anki without rebuilding the deck.

A verb that the example uses pronominally (ponerse for poner) shows that form and its
sense above the plain meaning. The front shows the word with its pronunciation, written (IPA) and spoken (Spain),
and the sentence it was heard in; the back adds the Latin American recording, the
meaning, the translation and the links to the video.
"""

TEMPLATE_NAME = "Spanish to English"

FRONT = (
    '<div class="word">{{Word}}</div>'
    '{{#IPA}}<div class="ipa">{{IPA}}</div>{{/IPA}}{{AudioSpain}}'
    '<div class="example">{{Example}}</div>'
)

BACK = (
    '<div class="word">{{Word}}</div>'
    '{{#IPA}}<div class="ipa">{{IPA}}</div>{{/IPA}}{{AudioLatinAmerica}}'
    '<div class="pos">{{PartOfSpeech}}{{#HeardAs}} · heard as {{HeardAs}}{{/HeardAs}}</div>'
    '<div class="meaning">{{Meaning}}</div>'
    '<div class="example">{{Example}}</div>'
    '<div class="example-en">{{ExampleEnglish}}</div>'
    '<div class="source">{{Source}}</div>'
    '{{#MoreExamples}}<details class="more"><summary>{{HeardIn}}</summary>'
    '{{MoreExamples}}</details>{{/MoreExamples}}'
)

CSS = """
.card { font-family: system-ui, sans-serif; font-size: 22px; text-align: center;
        color: #222; background: #fafafa; }
.word { font-size: 40px; font-weight: 600; margin: 12px 0 4px; }
.pos { font-size: 15px; color: #888; }
.ipa { font-size: 19px; color: #555; margin-bottom: 4px; font-family: "Charis SIL", "Doulos SIL", "Noto Sans", serif; }
.ipa small { font-size: 12px; color: #999; font-family: system-ui, sans-serif; }
.example { font-size: 20px; margin-top: 18px; color: #333; }
.example b { color: #c0392b; }
.meaning { font-size: 28px; margin: 14px 0; }
.meaning .pron { margin-bottom: 4px; }
.meaning .pron span { color: #c0392b; font-weight: 600; margin-right: 6px; }
.meaning .plain { font-size: 18px; color: #888; }
.example-en { font-size: 18px; color: #555; font-style: italic; }
.source { font-size: 14px; margin-top: 18px; }
.source a { color: #2980b9; }
.more { font-size: 16px; margin-top: 16px; text-align: left; }
.more summary { font-size: 15px; color: #2980b9; cursor: pointer; text-align: center; }
.more div { margin: 6px 0; }
.more b { color: #c0392b; }
.more a { color: #2980b9; font-size: 13px; }
.nightMode .card, .card.nightMode { color: #eee; background: #222; }
.nightMode .example { color: #ddd; }
.nightMode .example-en { color: #aaa; }
.nightMode .ipa { color: #bbb; }
.nightMode .meaning .pron span { color: #e8705f; }
"""
