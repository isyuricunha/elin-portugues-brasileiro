# Elin PT-BR Style Sheet (DRAFT - pending Yuri's review)

## Voice

- Brazilian Portuguese, natural and contemporary, but with a
  medieval-fantasy period feel. No modern slang, no anglicisms where a
  good PT word exists ("clique" style UI verbs are fine when the
  original is UI text).
- Address the player as "você". NPCs vary by personality; the tone
  columns in chara_talk encode personality, match each one's register.
- Item and skill names: short, punchy, game-feel first. Descriptions:
  flavor-forward, faithful to the original's wit.

## Humor policy (Yuri's standing rule)

- Jokes are translated at FULL strength: deadpan absurdity, crude bits,
  innuendo, dark humor. Never soften, never explain, never drop a
  punchline. If a joke is untranslatable, rebuild one of equivalent
  force rather than flattening it.

## Names and proper nouns

- Character, deity, city and zone proper names stay in the original
  (Palmia, Lumiest, Nefu, Ylva, Elea...) unless the official/community
  PT-BR convention says otherwise (see GLOSSARY.md).
- Titles and ranks are translated (guard captain, elder, ...).
- Elona legacy references keep Elona's established PT-BR community
  terms where they exist.

## Typography and mechanics

- Preserve every token exactly: `{...}` brace tags, `#tag` codes, `\n`,
  `+N` template slots, `@speaker` directive lines (never translated).
- PT-BR punctuation rules apply to prose; keep ASCII where the source
  uses ASCII, use proper accents (UTF-8, proven safe by the reference).
- Numbers, hotkeys and formatting inside strings stay untouched.
- Line counts per file never change; trailing spaces and file-internal
  blank-line rhythm are preserved.
