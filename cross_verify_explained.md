# cross_verify.py explained, line by line

This file walks through `cross_verify.py` from the top to the bottom, in the same order as the code.
Every statement is explained. Lines that belong together (for example the three lines of one `if`) are explained together.

How to read it: each function has a short "what it is for", then a list. Each item is a line of code, followed by what it does.

---

## 0. The big picture (read this first, 3 minutes)

You give the program a **base** (the value you trust, for example the name the user typed) and one or more
**candidates** (the same value read from other documents). It answers, for every candidate: green, yellow or red.

```
your request (list of checks)
        |
  read_checks ........ checks the shape of the request
        |
  for every check:  parse_value(base)            -> parsed base          (parse_name / parse_dob / parse_address)
  for every candidate:
        parse_value(candidate)                    -> parsed candidate
        COMPARERS[type](base, candidate)          -> outcome: a list of REASONS + highlight spans
        decide(outcome)                           -> the colour: the worst severity among the reasons
        build_result(...)                         -> the dictionary you receive
        |
  roll_up ............ the worst comparison speaks for the field, and for the whole report
```

Words used in the code:

| Word | Meaning |
|---|---|
| base | the trusted value |
| candidate | the same value taken from another document |
| token | one word (or one initial) of a name or address, with its position in the original text |
| norm | the cleaned, lower-case form of a token, used for comparing |
| reason | one finding, such as `TOKEN_ORDER_DIFFERENT`. Each reason has a severity: info, warn or fail |
| flag | the colour: `green`, `yellow` or `red`. It is the worst severity among the reasons |
| outcome | what a `compare_*` function returns: reasons, spans |
| span | `(start, end, kind)`: a piece of the original text and how to colour it |
| cfg | the loaded configuration (the JSON file plus some lookup tables the code builds from it) |
| kind | the sort of value inside a type: `pan` for an `id`, `gender` for a `text` |

---

## 1. The top of the file

### Lines 1-23: the docstring

```python
"""cross_verify - compare a trusted value with the same value in other documents.
...
"""
```

- A text between triple quotes as the very first statement is the **module docstring**. It is shown by `help(cross_verify)` and does nothing when the program runs.
- It describes the four steps (parse, compare, decide, build), the three colours, where the settings live, and what to install.

### Lines 25-47: the `HOW TO RUN` comment block

- Every line that starts with `#` is a comment. Python ignores it completely.
- It shows how to start the program from the command line: `python cross_verify.py -i input.json`, with `--compact` for one line of output and `--config` for another settings file. `-i -` means "read the input from the keyboard or a pipe".
- It also shows the shape of `input.json`: a `checks` list, each check with `field`, `type`, `base` and `candidates`.

### Imports

| Line | What it does |
|---|---|
| `from __future__ import annotations` | Type hints are stored as text and not evaluated. This allows modern hints such as `str | None` and `list[Json]`. It must come before the other imports. |
| `import argparse` | Reads the command line (`-i`, `--config` ...). Used only in `main`. |
| `import datetime as dt` | Dates. `dt.date`, `dt.datetime`, `dt.date.today()`. |
| `import hashlib` | Makes a short fingerprint (hash) of the settings, so every report says which settings it used. |
| `import json` | Reads the settings file and the input file, and prints the report. |
| `import logging` | Writes log lines (counts only, never your values). |
| `import os` | Environment variables (`CROSS_VERIFY_CONFIG_PATH`) and the `PathLike` type. |
| `import re` | Regular expressions: find labels, dates, pincodes, words. |
| `import sys` | Standard input and standard error. |
| `import unicodedata` | Unicode helpers: remove accents, convert Indian digits to 0-9. |
| `import uuid` | Makes a random request id when you do not give one. |
| `from collections.abc import Mapping, Sequence` | Only used in type hints: "a dict-like thing", "a list-like thing". |
| `from pathlib import Path` | File paths. |
| `from typing import Any` | The type hint "anything". |
| `from rapidfuzz.distance import OSA` | The only outside library. `OSA.distance(a, b)` counts how many single-letter edits turn `a` into `b`. An edit is an insert, a delete, a replace, or swapping two neighbouring letters. |

### Module variables

- `log = logging.getLogger("cross_verify")`: the logger this module writes to. It does not set up any output itself. The program that uses it decides where logs go.
- `Json = dict[str, Any]`: a short name for "a dictionary with text keys". Used everywhere in the hints.
- `Span = tuple[int, int, str]`: `(start, end, kind)`. A piece of the original text, from character `start` up to `end`, with a colour `kind` such as `match` or `conflict`.

### The four error classes

```python
class CrossVerifyError(Exception): ...
class ConfigError(CrossVerifyError): ...
class InputError(CrossVerifyError, ValueError): ...
class ModeNotImplementedError(CrossVerifyError, NotImplementedError): ...
```

- `CrossVerifyError` is the parent of every error this module raises, so you can catch them all with one `except`.
- `ConfigError`: the settings file is missing, unreadable or incomplete.
- `InputError`: your **request** is malformed (for example no `type`, or an empty `candidates` list). It is also a `ValueError`. A bad *value* (blank, unreadable date) is never an error: it becomes a red result.
- `ModeNotImplementedError`: the settings ask for `hybrid` or `llm`, which are not built yet. It is also a `NotImplementedError`.
- Each class has only a docstring as its body, because no extra code is needed.

---

## 2. Section 1: the reasons table

### `REASONS`

```python
REASONS: dict[str, str] = { "EXACT": "info", "TOKEN_ORDER_DIFFERENT": "warn", "DATE_DIFFERENT": "fail", ... }
```

- A dictionary: **reason code -> severity**.
- **Severity** decides the colour: `info` keeps it green, `warn` makes it yellow, `fail` makes it red. The colour of a comparison is the **worst** severity among its reasons.
- This table is the rulebook of the program. The meaning of every code:

| Code | Severity | When it appears |
|---|---|---|
| `EXACT` | info | the two raw texts are identical (after trimming spaces) |
| `NORMALIZED_EQUAL` | info | the texts differ, but are equal after clean-up (case, punctuation, date format) |
| `HONORIFIC_IGNORED` | info | a leading title (Mr, Dr, Shri) was skipped |
| `CARE_OF_REMOVED` | info | an "S/O Ramesh" part of a name, or an "S/O ..." line of an address, was removed |
| `LABEL_STRIPPED` | info | a label such as `Name:`, `DOB:`, `Address:` was removed |
| `POSSIBLE_TYPO` | info | two dates differ by exactly one digit (only a hint, the result is red anyway) |
| `TOKEN_ORDER_DIFFERENT` | warn | same name words, different order |
| `INITIAL_EXPANDED` | warn | an initial stands for a full word (`J` and `Jayakumar`) |
| `EXTRA_INITIALS` | warn | the candidate has initials the base does not |
| `MISSING_INITIALS` | warn | the candidate lacks initials the base has |
| `EXTRA_TOKEN` | warn | the candidate has an extra full word |
| `MISSING_TOKEN` | warn | the candidate lacks a full word |
| `SPACING_DIFFERENCE` | warn | one word on one side, two on the other (`Nishanthkumar`, `Nishanth Kumar`) |
| `SPELLING_VARIANT` | warn | a small spelling difference in an address word (names are never forgiven a spelling difference) |
| `NON_LATIN_TEXT_IGNORED` | warn | part of the text is in another script and was dropped |
| `INCOMPLETE_ADDRESS` | warn | a part of the address exists on one side only |
| `NUMBER_SUBSET` | warn | one address has an extra number, or `12` against `12/3` |
| `PINCODE_NEAR` | warn | pincodes agree on the first three digits and nothing else disagrees |
| `WORDS_PARTIAL` | warn | some place words differ, but enough of them match |
| `DIFFERENCE_UNCLASSIFIED` | warn | safety net: the values differ in a way no rule explained |
| `MISSING_VALUE` | fail | the candidate is empty, `None` or `N/A` |
| `BASE_MISSING` | fail | the base is empty |
| `UNPARSEABLE` | fail | nothing readable could be found |
| `UNSUPPORTED_SCRIPT` | fail | the text is entirely in another script |
| `TOO_LONG` | fail | too many characters or words |
| `DATE_IMPLAUSIBLE` | fail | a date in the future, or older than `max_age` |
| `INTERNAL_ERROR` | fail | an unexpected error was caught |
| `TOKEN_CONFLICT` | fail | a name word was replaced by a different word |
| `INSUFFICIENT_NAME` | fail | too little of the name to decide (for example one initial) |
| `NO_ANCHOR_MATCH` | fail | neither pincode nor house number matches |
| `DATE_DIFFERENT` | fail | two readable dates differ |
| `PINCODE_MISMATCH` | fail | pincodes differ |
| `CITY_MISMATCH` | fail | cities differ |
| `NUMBER_MISMATCH` | fail | house or street numbers differ |
| `WORDS_MISMATCH` | fail | place words do not match |

### The small constant tables

- `FLAG_OF_SEVERITY = {"info": "green", "warn": "yellow", "fail": "red"}`: turns a severity into a colour.
- `FLAG_RANK = {"green": 0, "yellow": 1, "red": 2}`: a number per colour, so "the worst" can be found with `max`.
- `STATUS_OF_FLAG = {"green": "match", "yellow": "warning", "red": "mismatch"}`: the second name of each colour, returned as `status`.
- `MODES = ("fuzzy", "hybrid", "llm")`: the modes the settings may name. Only `fuzzy` is built.
- `FIELD_TYPES = ("name", "dob", "address")`: the allowed values of `type`.
- `ENV_CONFIG_PATH = "CROSS_VERIFY_CONFIG_PATH"`: the name of the environment variable that can point to another settings file.
- `DEFAULT_CONFIG_NAME = "cross_verify_config.json"`: the settings file that sits next to the code.

### `add_reason(reasons, cfg, code, message)`

What it is for: add one reason to a list, but only once per code.

- `if any(r["code"] == code for r in reasons): return`: if a reason with this code is already in the list, do nothing. This is why a code never appears twice.
- `severity = cfg["severity_overrides"].get(code, REASONS[code])`: look up the code in the rulebook. If the settings file says "treat this code as info/warn/fail", use that instead. This is how you change a colour rule without touching the code.
- `reasons.append({...})`: store a dictionary with `code`, `severity` and `message` (text for people).

---

## 3. Section 2: configuration

(In the code this part sits between `add_reason` and the "3. Text helpers" banner. Its own banner comment is not in the file at the moment, so it is easy to miss.)

### `_REQUIRED`

- A long text of setting paths such as `limits.max_checks` or `name.honorifics`, turned into a list with `.split()` (split on whitespace). Each path means "inside `limits`, the key `max_checks`".
- `# noqa: SIM905` tells the code checker to accept the `.split()` on a fixed text.
- It is the list of **every setting the code reads**. If one is missing the program stops at start-up.

### `_has(cfg, path)`

- `node: Any = cfg`: start at the top of the settings.
- `for key in path.split("."):`: take the path one key at a time (`limits`, then `max_checks`).
- `if not isinstance(node, dict) or key not in node: return False`: if we are not in a dictionary, or the key is absent, the setting is missing.
- `node = node[key]`: go one level deeper.
- `return True`: every key was found.

### `check_config(cfg)`

What it is for: stop at start-up with a clear message, instead of failing in the middle of a request.

- `errors = [f"{path}: missing" for path in _REQUIRED if not _has(cfg, path)]`: one message for every missing setting.
- `if not errors:`: only if nothing is missing, run the deeper checks (they read settings that must exist).
- `if cfg["mode"] not in MODES:` adds an error when the mode is not one of the three names.
- `errors += [... for k, v in cfg["severity_overrides"].items() if k not in REASONS or v not in FLAG_OF_SEVERITY]`: every override must name a real reason code and a valid severity.
- `if errors: raise ConfigError("invalid configuration: " + "; ".join(errors))`: if there is any problem, stop and list all of them together.

### `_phrase_regex(phrases)`

What it is for: turn a list of words or phrases into a piece of regular expression.

- `sorted(phrases, key=len, reverse=True)`: longest phrase first, so "date of birth" is tried before "dob".
- `re.escape(p)`: make special characters such as `.` or `/` literal.
- `.replace(r"\ ", r"\s+")`: an escaped space becomes "one or more white-space characters", so a phrase still matches when the text has two spaces.
- `"|".join(...)`: join the alternatives with `|` (which means "or" in a regular expression).

### `load_config(path=None)`

What it is for: find, read and check the settings file.

- `target = Path(path or os.environ.get(ENV_CONFIG_PATH) or Path(__file__).with_name(DEFAULT_CONFIG_NAME))`: choose the file in this order: the `path` you passed, else the environment variable, else `cross_verify_config.json` in the same folder as the code (`__file__` is the code's own path).
- `try: cfg = json.loads(target.read_text(encoding="utf-8"))`: read the file as text and convert the JSON text into Python dictionaries.
- `except FileNotFoundError as exc: raise ConfigError(...) from exc`: no such file: raise our own error with a clear message. `from exc` keeps the original error attached.
- `except (OSError, ValueError) as exc:` other read problems, or text that is not JSON (`json` raises `ValueError` for that).
- `if not isinstance(cfg, dict): raise ConfigError(...)`: the JSON must be an object `{...}`, not a list.
- `return prepare_config(cfg)`: check it and build the lookup tables.

### `prepare_config(raw)`

What it is for: validate the settings and build the ready-to-use tables the code needs, so this work happens once.

- `cfg: Json = json.loads(json.dumps(raw))`: make a private deep copy by turning it into JSON text and back. This also fails early if the settings contain something that is not plain JSON, and means later changes to your original dictionary cannot affect the program.
- `check_config(cfg)`: validate (see above).
- `cfg["config_hash"] = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:12]`: a fingerprint of the settings: write them as text with sorted keys, hash it with SHA-256, keep the first 12 characters. Any change to a setting changes the hash.
- `name, addr = cfg["name"], cfg["address"]`: short names for two sections.
- `cities = {fold(city): fold(city) for city in addr["cities"]}` and the next loop: the same idea for cities: every city and alias maps to the main city name (`bangalore` -> `bengaluru`).
- `cfg["_rt"] = {...}`: "runtime" tables, built once:
  - `"placeholders"`: the set of texts that mean "no value" (`n/a`, `nil` ...), folded.
  - `"care_of"`: a regular expression that finds markers such as `s/o`, `d/o`, `c/o`. `(?<![a-z0-9])` means "not directly after a letter or digit", `(?![a-z0-9])` means "not directly before one", and `re.I` ignores case.
  - `"name_label"`, `"address_label"`: regular expressions that match a label at the start of the text (`Name:`) followed by `:`, `-` or `–`.
  - `"dob_label"`: the same for date labels, but it may appear anywhere, and the separator is optional (`DOB 12/03/1998`).
  - `"honorifics"`: the set of titles.
  - `"ignored_words"`: address words that carry no information (generic words and label words such as `road`, `flat`).
  - `"descriptors"`: words such as `cross`, `main`, `sector` that are followed or preceded by a number.
  - `"abbreviations"`: `rd -> road` and so on.
  - `"cities"`: the map built above.
  - `"max_city_words"`: the number of words in the longest city name (for example 3 for a three-word name), so the address code knows how many words to try together.
- `return cfg`: the settings, ready to use.

---

## 4. Section 3: text helpers (used by every field type)

### `_WORD`

```python
_WORD = re.compile(r"(?:[^\W_]|[\u0300-\u036f])+(?:['\u2019](?:[^\W_]|[\u0300-\u036f])+)*")
```

- A regular expression that finds one "word": letters and digits (`[^\W_]` means "a word character that is not an underscore") or accent marks (`\u0300-\u036f`), one or more of them.
- After that, it may continue with an apostrophe (`'` or the curly `’`) and more letters, so `O'Brien` is one word.
- `re.compile` prepares the pattern once, so it is fast when used many times.

### `fold(text)`

What it is for: make text comparable. `"José"` and `"JOSE"` both become `"jose"`.

- `text.casefold()`: a strong lower-case that also handles special letters (`ß` becomes `ss`).
- `unicodedata.normalize("NFKD", ...)`: splits accented letters into the plain letter plus an accent mark (`é` becomes `e` and a separate accent), and turns "compatibility" characters (full-width letters, ligatures) into plain ones.
- The `return "".join(ch for ch in decomposed if ...)` keeps a character only if `not unicodedata.combining(ch)` (it is not an accent mark) and `unicodedata.category(ch) not in ("Cf", "Cc")` (it is not an invisible format character such as a zero-width space, and not a control character).

### `has_foreign_letters(text)`

- `any(ch.isalpha() and ord(ch) > 0x24F for ch in text)`: true if any character is a letter whose code number is above `0x24F`, the end of the Latin letters. Hindi, Tamil and other scripts have higher numbers. Version 1 does not support them.

### `ascii_digits(text)`

- For each character: if its Unicode category is `"Nd"` (a decimal digit in any script) it is replaced by `str(unicodedata.decimal(ch))`, the ordinary 0-9 digit. Other characters stay.
- The text keeps the **same length**, which matters because highlight positions must still point at the original text.

### `is_missing(value, cfg)`

- `if value is None: return True`: `None` means no value.
- `return isinstance(value, str) and fold(value).strip() in cfg["_rt"]["placeholders"] | {""}`: for text, fold it, trim spaces, and check whether it is empty or one of the placeholder texts (`n/a`, `nil`, `-` ...). The `| {""}` adds the empty text to the placeholder set. For any other type (a number, a date) the answer is "not missing".

### `show(value)`

What it is for: the text that is shown back as `raw`, or `None` if the value is not text, a number, or a date.

- `if isinstance(value, dt.datetime): return value.date().isoformat()`: a date-and-time becomes `YYYY-MM-DD` text. (`datetime` is checked first because it is also a kind of `date`.)
- `if isinstance(value, (dt.date, str)): return value if isinstance(value, str) else value.isoformat()`: text stays as it is, a date becomes `YYYY-MM-DD`.
- `if isinstance(value, (int, float)) and not isinstance(value, bool):` numbers are accepted, but `True`/`False` are refused (in Python a `bool` is also an `int`).
- `return str(int(value)) if float(value).is_integer() else str(value)`: `1998.0` becomes `"1998"`, other numbers become their text.
- `return None`: anything else (lists, dictionaries, bytes, objects).

### `build_segments(raw, spans)`

What it is for: cut the original text into pieces, each tagged for colouring. Joining all the pieces gives back exactly the original text.

- `out = []` and `pos = 0`: the pieces so far, and how far into the text we have got.
- `for start, end, kind in sorted(s for s in spans if 0 <= s[0] < s[1] <= len(raw)):` go through the spans in order, ignoring any that are empty or outside the text.
- `if start < pos: continue`: this span overlaps one already used; skip it.
- `if start > pos: out.append(_piece(raw, pos, start, None))`: there is untagged text between the last piece and this span; add it as a plain piece.
- `out.append(_piece(raw, start, end, kind))` and `pos = end`: add the tagged piece and move on.
- After the loop, `if pos < len(raw): ...` adds any plain text left at the end.

### `_piece(raw, start, end, kind)`

- `text = raw[start:end]`: cut that part of the text.
- Returns `{"text", "start", "end", "kind"}`. If `kind` is `None` it becomes `"text"`, or `"space"` when the piece is only spaces.

### `word_relation(a, b, min_length, table)`

What it is for: decide how two cleaned words relate. Returns `("exact", 1.0)`, `("spelling", similarity)` or `None` (not related). It is used for **address words only**. Names are compared letter for letter and do not use it.

- `if a == b: return "exact", 1.0`: identical words.
- `longest = max(len(a), len(b))`: the longer word's length.
- `allowed = max((edits for min_len, edits in table if longest >= min_len), default=0)`: how many letter edits are allowed. `table` looks like `[[5, 1], [8, 2]]`: from 5 letters, 1 edit; from 8 letters, 2 edits. `default=0` means no edits for shorter words.
- `distance = OSA.distance(a, b)`: the number of edits between the words.
- `if min(len(a), len(b)) >= min_length and 0 < distance <= allowed:` both words must be long enough (short words must match exactly), there must be at least one edit (zero was handled above), and no more than allowed.
- `return "spelling", 1.0 - distance / longest`: the similarity, for example `residency` and `residence` have 1 edit over 9 letters.
- `return None`: not related.

### `pair_up(left, right, relate)`

What it is for: match the words of two lists one to one, best matches first.

- `options = []` then two nested loops: for every word `a` in `left` (position `i`) and every word `b` in `right` (position `j`), call `relate(a, b)`.
- `if found: options.append((-found[1], abs(i - j), i, j, found[0]))`: keep related pairs as `(minus similarity, position distance, i, j, kind)`. The minus makes the best similarity sort first. The position distance breaks ties in favour of words at similar places.
- `pairs, used_left, used_right = [], set(), set()`: the result and the words already used.
- `for neg_sim, _, i, j, kind in sorted(options):` take options from best to worst.
- `if i not in used_left and j not in used_right:` use an option only if neither word is taken. Then both are marked used and `pairs.append((i, j, kind, -neg_sim))` stores it with the similarity restored.
- `return sorted(pairs)`: sorted by position of the left word.

### `make_outcome(reasons, exact, base, cand, **extra)`

What it is for: every `compare_*` function returns the same shape, built here.

- Returns a dictionary with: the `reasons` found; `exact` (are the values provably equal); the cleaned text of the base and the candidate; `base_spans` and `cand_spans`, which start as a copy of each side's `ignored` parts (`[*base["ignored"]]` copies the list so the original is not changed); and any `**extra` items the caller passes.

### `failure(code, message)`

- Returns `{"ok": False, "code": code, "message": message}`. Every `parse_*` function returns this when the value cannot be used. `"ok": False` is how the rest of the code recognises it.

---

## 5. Section 4: names

### `_VOWELS = set("aeiou")`

- The vowels, as a set. Used to detect initials that were written together (see `parse_name`).

### `parse_name(raw, cfg, side)`

What it is for: turn a name text into a list of cleaned words, each remembering where it was in the original text. `side` is `"base"` or `"candidate"` and is used in messages.

- `rt, nc = cfg["_rt"], cfg["name"]`: the lookup tables and the name settings.
- `reasons: list[Json] = []` and `ignored: list[Span] = []`: reasons found while cleaning, and parts of the text that were skipped.
- `start, end = 0, len(raw)`: the part of the text to read. It may shrink below.
- `label = rt["name_label"].match(raw)`: does the text begin with a label such as `Name:`?
- `if label:` then `ignored.append((0, label.end(), "ignored"))` (remember the label as skipped text), `start = label.end()` (start reading after it) and `add_reason(... "LABEL_STRIPPED" ...)`.
- `care = rt["care_of"].search(raw, start)`: look for `S/O`, `D/O`, `W/O` ... after the start.
- `if care:` the rest of the text, from the marker to the end, is skipped: `ignored.append((care.start(), len(raw), "ignored"))`, `end = care.start()`, reason `CARE_OF_REMOVED`. So `"Nishanth S/O Ramesh"` keeps only `Nishanth`.
- `words: list[Json] = []` and `foreign = False`: the words found, and whether any was in another script.
- `for match in _WORD.finditer(raw, start, end):` go through every word-like piece between `start` and `end`.
- `if has_foreign_letters(match.group()):` a word in another script: set `foreign = True`, remember it as ignored text, and `continue` to the next word.
- `norm = "".join(ch for ch in fold(match.group()) if ch.isalpha())`: clean the word (lower case, no accents) and keep **letters only**. A digit inside a word (`Nish4nth`) is treated as OCR noise and dropped; so are apostrophes.
- `if norm: words.append({"norm": norm, "start": match.start(), "end": match.end()})`: keep the word with its place in the original text. A "word" made only of digits becomes empty and is skipped.
- `while len(words) > 1:` loop that removes **leading titles**. It runs only while more than one word is left, so a title is never the only word removed.
- `if words[0]["norm"] in rt["honorifics"]:` the first word is a title from the config list (Mr, Dr, Shri ...). Words such as `Sri` and `Kumari` are not in the list, so they stay part of the name.
- Inside: the title is remembered as ignored text, a `HONORIFIC_IGNORED` reason is added, and `words.pop(0)` removes it. `else: break` stops at the first word that is not a title.
- `tokens: list[Json] = []` and `for word in words:`: build the final token list.
- The long `if` finds **initials written together**, like `JS`: the word has 2 to 3 letters (`2 <= len(norm) <= 3`), is plain ASCII (`norm.isascii()`), has no vowel (`not _VOWELS & set(norm)`: the intersection with the vowels is empty), and its length in the original text equals its cleaned length (`word["end"] - word["start"] == len(norm)`), so each letter maps to one character of the original.
- If so, `tokens += [{...} for k, ch in enumerate(norm)]` replaces the word with one token per letter (`J` and `S`), each with its own position (`word["start"] + k`). Otherwise `tokens.append(word)` keeps it.
- `if foreign and not tokens: return failure("UNSUPPORTED_SCRIPT", ...)`: everything was in another script.
- `if not tokens: return failure("UNPARSEABLE", ...)`: no name found at all.
- `if len(tokens) > nc["max_tokens"]: return failure("TOO_LONG", ...)`: too many words.
- `if foreign: add_reason(... "NON_LATIN_TEXT_IGNORED" ...)`: some other-script text was dropped, but a name remains.
- The final `return {...}`: `"ok": True`, the original `raw` text, the `tokens`, the `ignored` parts, the `reasons`, and `normalized`, the tokens joined with spaces (shown to the user as the cleaned name).

### `_is_initial(token)`

- `len(token["norm"]) == 1`: a one-letter token is an initial.

### `_join_neighbours(mine, other)`

What it is for: `Nishanth Kumar` against `Nishanthkumar`. If two neighbouring words of one name, written together, form a word of the other name, join them.

- `words = {t["norm"] for t in other}`: the set of words of the other name.
- `out = []` and `i = 0`: the result, and a position.
- `while i < len(mine):` walk through the words.
- `a, b = mine[i], mine[i + 1] if i + 1 < len(mine) else None`: the current word, and the next one if there is one.
- `if b and a["norm"] + b["norm"] in words and a["norm"] not in words and b["norm"] not in words:` the two words, glued, are a word of the other name, and neither of them is a word there on its own.
- Then `out.append({... "joined": True})` stores one joined token (from the start of `a` to the end of `b`, marked `joined`), and `i += 2` skips both.
- Otherwise `out.append(a)` keeps the word and `i += 1` moves on.

### `_match_initials(b, c, used_b, used_c)`

What it is for: pair the initials of the two names. `b` and `c` are the token lists; `used_b`/`used_c` are the positions already matched to words (this function adds to them).

- `pairs = []` and the inner function `take(i, j, kind)`: records a pair and marks both positions as used.
- First loop (`for i ... for j ...`): an initial of the base and the **same letter** in the candidate: `kind = "initial_exact"`. The test `b[i]["norm"] == c[j]["norm"]` with `_is_initial(b[i])` means the candidate token is the same single letter.
- Second loop: a base initial still unused looks for an unused **candidate word** that starts with that letter (`J` and `jayakumar`): `kind = "initial_expanded"`, then `break` so one initial matches one word.
- Third loop: the same the other way round: a candidate initial and a base word.
- `return pairs`.

### `_crossing(pairs)`

- `pairs` are `(base position, candidate position)`. Returns the base positions of pairs that **cross** another pair: `i < i2 and j > j2` (this one is earlier in the base but later in the candidate) or the opposite. For `[(0, 1), (1, 0)]` the answer is `{0, 1}`: both words moved.

### `_name_reasons(reasons, m, b, c, cfg)`

What it is for: turn the pairing result `m` into reasons.

- `m["moved"]` not empty -> `TOKEN_ORDER_DIFFERENT`; any `initial_expanded` pair -> `INITIAL_EXPANDED`.
- `words_b` / `words_c`: the unmatched **full words** of the base and of the candidate (initials are left out).
- `if m["left_b"] and m["left_c"]:` **both sides** have leftovers: a word was replaced by a different word. `left_b`/`left_c` are the leftovers as text, and a `TOKEN_CONFLICT` reason is added. Then `return` (nothing else to say).
- Otherwise only one side has leftovers:
  - `if words_b:` `MISSING_TOKEN` (the candidate lacks words).
  - `if words_c:` `EXTRA_TOKEN` (the candidate has extra words).
  - `if len(m["left_b"]) > len(words_b):` there are leftovers on the base side that are initials: `MISSING_INITIALS`.
  - `if len(m["left_c"]) > len(words_c):` the same for the candidate: `EXTRA_INITIALS`.
- `if not m["words"] and len(m["initials"]) < cfg["name"]["initials_only_min"]:` no full word matched and too few initials matched (for example the candidate is just `N`): `INSUFFICIENT_NAME`.

### `compare_names(base, cand, cfg, today)`

What it is for: compare two parsed names and return an outcome. (`today` is not used here; all `compare_*` functions share one signature.)

- `b, c = base["tokens"], cand["tokens"]`: shortcuts for the token lists.
- `reasons = [*base["reasons"], *cand["reasons"]]`: start with the reasons found while parsing each side.
- `if [t["norm"] for t in b] == [t["norm"] for t in c]:` **the cleaned words are identical, in the same order.**
  - `code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"`: exact if the original texts match, otherwise "equal after clean-up".
  - `add_reason(...)`, `out = make_outcome(reasons, True, base, cand)` (`exact` is true).
  - `out["base_spans"] += [(t["start"], t["end"], "match") for t in b]`, and the same for the candidate: every word is highlighted as a match.
  - `return out`.
- `b, c = _join_neighbours(b, c), _join_neighbours(c, b)`: join words that were split on one side only, in both directions. Then, if any token is marked `joined`, add `SPACING_DIFFERENCE`.
- `def relate(x, y):` a small function used by `pair_up`: two words are related only when they are equal (`("exact", 1.0)`), any other pair gives `None`. So names are compared letter for letter: `Vinay` and `Vijay` never pair, and neither do `Nishanth` and `Nishant`.
- `full_b`, `full_c`: the positions of the full words (not initials) on each side.
- `found = pair_up([...norms of full words of b], [...norms of c], relate)`: pair up the full words. Positions in `found` are positions **within the full-word lists**.
- `words = [(full_b[i], full_c[j], kind, sim) ...]`: convert them back to positions in the whole token lists.
- `used_b, used_c = {w[0] for w in words}, {w[1] for w in words}`: the tokens already used.
- `initials = _match_initials(b, c, used_b, used_c)`: pair the initials (this also adds to `used_b` and `used_c`).
- `m: Json = {...}`: the pairing result: `words`, `initials`, `left_b` and `left_c` (every position not used), and `moved` (the crossing pairs).
- `_name_reasons(reasons, m, b, c, cfg)`: add the reasons.
- `out = make_outcome(reasons, False, base, cand)`: build the outcome. `exact` is `False` here.
- `conflict = bool(m["left_b"] and m["left_c"])`: true when both sides have leftovers.
- The inner function `mark(bi, ci, kind)`: adds a highlight span for the base word `bi` and/or the candidate word `ci`.
- The four loops that follow: word pairs are `moved` (if crossed) or `match`; initial pairs are `match` or `initial`; leftovers are `conflict` when `conflict` is true, otherwise `missing` (base side) or `extra` (candidate side).
- `return out`.

---

## 6. Section 5: dates of birth

The rule: a date of birth is written **day, month, year**, in that order. The month may be a number or a name, and the year has four digits. The result is **green only when the day, month and year are all equal. Every other case is red.** A date is never yellow. (A year-first date such as `1998-03-12` is also read, because a four-digit first number cannot be mistaken for a day.)

### Constants and patterns

- `_MONTHS`: month names and short names to numbers (`"mar": 3`, `"march": 3`, `"sept": 9` ...).
- `_SEP = r"[\s\-/.,]*"`: "zero or more separators": space, `-`, `/`, `.`, `,`.
- `_NUMERIC`: three numbers split by the **same** separator. `(\d{1,4})` first number (1 to 4 digits), `\s*([/\-.])\s*` a separator (kept as group 2), `(\d{1,2})` second number, `\s*\2\s*` the **same separator again** (`\2` means "repeat group 2"), `(\d{1,4})` third number. `(?<!\d)` and `(?!\d)` mean "not glued to other digits". Matches `12-03-1998`, `12/03/1998`, `1998-03-12`.
- `_DAY_MONTH_NAME`: a day, an optional `st/nd/rd/th`, separators, a month **word** of 3 to 9 letters, an optional dot, separators, and a four-digit year. Matches `12 March 1998`, `12-Mar-1998`.
- `_PARTS = ("day", "month", "year")`: the three parts of a date, in the order they are shown.

### `_span(m, group, offset)`

- `m.start(group) + offset, m.end(group) + offset`: where one part of the match sits in the **original** text. The offset is the number of characters cut off in front (a label such as `DOB: `).

### `_build(year, month, day, spans, today, max_age)`

What it is for: turn the three numbers into a date, or an error.

- `when = dt.date(year, month, day)` inside `try`: Python builds the date. A day that does not exist (31 February, month 13) raises `ValueError`, and the function returns `{"error": "UNPARSEABLE"}`.
- `if when > today or year < today.year - max_age:` the date is in the future, or older than `max_age` years (110): `{"error": "DATE_IMPLAUSIBLE"}`.
- `return {"year": year, "month": month, "day": day, "spans": spans}`: a good date. `spans` holds the position of each part for highlighting.

### `_numeric_date(text, offset, today, max_age)`

What it is for: read `12-03-1998`, `12/03/1998`, `12.03.1998`, or year-first `1998-03-12`.

- `m = _NUMERIC.search(text)`: find three numbers split by the same separator. `if not m: return None` means "no numeric date here", so the next reader is tried.
- `first, last = len(m.group(1)), len(m.group(4))`: the number of digits in the first and the last number.
- `if first <= 2 and last == 4:` day, month, year: `groups = {"day": 1, "month": 3, "year": 4}` (the regex group number of each part).
- `elif first == 4 and last <= 2:` year, month, day: `groups = {"year": 1, "month": 3, "day": 4}`.
- `else: return None`: any other shape is not read. A two-digit year (`12-03-98`) ends here, and the result is red.
- `value = {...}` and `spans = {...}`: the number and the text position of each part, found with the group numbers.
- `return _build(...)`.

### `_named_month_date(text, offset, today, max_age)`

What it is for: read `12 March 1998`, `12th March, 1998`, `12-Mar-1998`.

- `for m in _DAY_MONTH_NAME.finditer(text):` look at every match of the pattern.
- `if m.group(2) in _MONTHS:` the word must really be a month name. Other words are skipped.
- `spans = {...}` and `return _build(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)), spans, today, max_age)`: year, month number, day.
- `return None` when no match holds a month name.

### `_read_date(text, offset, today, max_age)`

- `for reader in (_numeric_date, _named_month_date):` try the readers in this order.
- `if found: return found`: the first reader that gives something wins. An error result counts as something, so the search stops there.
- `return None`: no full date in the text.

### `_iso(found)`

- `f"{year:04d}-{month:02d}-{day:02d}"`: the date as `YYYY-MM-DD` (the `04d` and `02d` pad with zeros). This is the `normalized` text.

### `parse_dob(value, text, cfg, side, today)`

What it is for: read a date of birth. `value` is the original value (it may be a real date object) and `text` its text form.

- `reasons`, `ignored`, `max_age = cfg["dob"]["max_age"]`, and `found: Json | None` (a type note: `found` is a result or nothing).
- `if isinstance(value, dt.date):` a real date object: nothing to read. `day = value.date() if isinstance(value, dt.datetime) else value`, then `found = _build(day.year, day.month, day.day, {}, today, max_age)`. The empty `{}` means there are no text positions.
- `else:` it is text.
- `lowered = "".join(low if len(low := ch.lower()) == 1 else ch for ch in ascii_digits(text))`: first change any Indian-script digits to 0-9, then lower-case every character, but keep the character as it was if lower-casing would change its length. (`low := ...` stores the lower-case form in `low` inside the expression.) The length must not change so positions stay correct.
- `start = 0` and `label = cfg["_rt"]["dob_label"].search(lowered)`: look for `dob`, `date of birth` ... anywhere.
- `if label:` start reading after it (`start = label.end()`), remember it as ignored text, and add `LABEL_STRIPPED`.
- `found = _read_date(lowered[start:], start, today, max_age)`: read the part of the text after the label; `start` is passed as the offset.
- `if found is None: return failure("UNPARSEABLE", ...)`: no full date found (a year alone, a month and year, or a two-digit year all end here).
- `if "error" in found:` build a message ("is in the future or too far in the past", or "is not a real date") and return a failure with the error code.
- `return {...}`: `ok`, `raw`, then `**found` (the `year`, `month`, `day` and `spans`), `ignored`, `reasons`, and `normalized` (`_iso(found)`).

### `_digits(found)`

- `f"{year:04d}{month:02d}{day:02d}"`: the date as 8 digits, `YYYYMMDD`. Used to count how many digits differ.

### `compare_dobs(base, cand, cfg, today)`

What it is for: compare two parsed dates and produce an outcome. There are only two results: equal (green) or different (red).

- `reasons = [...]`: reasons from parsing both sides.
- `equal = {part: base[part] == cand[part] for part in _PARTS}`: for the day, the month and the year, are they equal?
- `same = all(equal.values())`: all three are equal.
- `if same:` reason `EXACT` (the text is identical) or `NORMALIZED_EQUAL` (written differently, for example `12/03/1998` and `12 March 1998`).
- `else:` some part differs.
  - `differing = [...]`: the names of the parts that differ.
  - `near = OSA.distance(_digits(base), _digits(cand)) == 1`: the eight-digit forms differ by exactly one digit.
  - `add_reason(... "DATE_DIFFERENT" ...)`: any difference in the day, month or year is a fail reason, so the colour is red.
  - `if near: add_reason(... "POSSIBLE_TYPO" ...)`: a hint for the reviewer. The colour is red either way.
- `out = make_outcome(reasons, same, base, cand)`: `exact` is true only when all three parts are equal.
- `out["components"] = []` and the `for part in _PARTS:` loop: build the day/month/year table and the highlight spans.
  - `kind = "match" if equal[part] else "conflict"`: each part is either equal or in conflict.
  - The two `if part in ...["spans"]` lines add the highlight span for that part, when its position is known (a date object has none).
  - `out["components"].append({...})`: one row of the table (`component`, `base`, `candidate`, `relation`).
- `return out`.

What you get for the base `12-03-1998`:

| Candidate | Result |
|---|---|
| `12-03-1998`, `12/03/1998`, `12 March 1998`, `12-Mar-1998`, `DOB: 12.03.1998`, `1998-03-12` | green, 100 |
| `03/12/1998` (day and month swapped) | red, 35 |
| `13-03-1998`, `12-04-1998`, `12-03-1999` | red, 40 |
| `12-03-98`, `03-1998`, `1998` | red, `UNPARSEABLE` (not a full date) |
| `31-02-1998` | red, `UNPARSEABLE` (no such day) |
| `12-03-2030` | red, `DATE_IMPLAUSIBLE` |

---

## 7. Section 6: addresses

An address is split into **four parts**, and each part is compared on its own:

1. **pincode** (6 digits),
2. **city** (found in the list of cities in the settings),
3. **numbers** (house or flat number such as `402` or `12/3`, and street numbers such as `2nd cross`, which become `cross:2`),
4. **place words** (`sai`, `residency`, `koramangala`).

### Patterns

- `_PINCODE = (?<!\d)([1-9]\d{2}) ?(\d{3})(?!\d)`: six digits, the first one not 0, with an optional single space after the first three (`560 034`), and not glued to other digits.
- `_ADDRESS_TOKEN = [^\W_]+(?:[/\-][^\W_]+)*`: a word of letters/digits, which may continue after a `/` or `-` (so `12-3/4` is one piece).
- `_SEGMENT = [^,;\n\r|]+`: a stretch of text without comma, semicolon, new line or `|`. An address "line".
- `_HOUSE_NUMBER = \d+[a-z]?(?:/\d+[a-z]?)*`: digits, maybe one letter, maybe more `/digits`: `402`, `12a`, `12/3`.
- `_ORDINAL = (\d+)(?:st|nd|rd|th)`: `2nd`, `5th`.

### `_number_of(norm, number_words)`

- `if norm.isdigit(): return str(int(norm))`: `"05"` becomes `"5"`.
- `ordinal = _ORDINAL.fullmatch(norm)` and `if ordinal: return str(int(ordinal.group(1)))`: `2nd` becomes `"2"`.
- `return str(number_words[norm]) if norm in number_words else None`: `second` becomes `"2"` using the table in the settings. Any other word gives `None` (not a number).

### `_address_tokens(text, regions, skip)`

What it is for: split the address into words, each with its position.

- `tokens = []` and `for start, end in regions:` go through each region of text that is allowed (care-of lines are not in the regions).
- `for m in _ADDRESS_TOKEN.finditer(text, start, end):` every piece in the region.
- `if skip and m.start() < skip[1] and m.end() > skip[0]: continue`: if the piece overlaps the pincode, skip it (the pincode is handled separately).
- `piece = m.group()` and `whole = fold(piece).replace("-", "/")`: the cleaned piece, with `-` turned into `/` so `4-5-6` and `4/5/6` are the same.
- `if "/" not in whole or _HOUSE_NUMBER.fullmatch(whole):` the piece has no `/`, or it is a house number like `12/3`: keep it as **one** token.
- Otherwise (like `anna-nagar`) the `for part in re.finditer(r"[^/\-]+", piece):` loop splits it into separate tokens, each with its own position (`m.start() + part.start()`).

### `parse_address(text, cfg, side)`

What it is for: turn an address text into pincode, city, numbers and words.

- `rt, ac = cfg["_rt"], cfg["address"]`; `reasons`; `ignored`.
- `digits = ascii_digits(text)`: the text with Indian-script digits turned into 0-9. It has the same length as the original, so all positions are valid for both.
- `start = 0`, `label = rt["address_label"].match(digits)`: does it begin with `Address:` or similar? If so, skip it (`start = label.end()`), remember it as ignored, and add `LABEL_STRIPPED`.
- `segments = [(m.start(), m.end()) for m in _SEGMENT.finditer(digits, start)]`: the address lines.
- `regions = []` then `for a, b in segments:`: decide which lines to keep.
- `care = rt["care_of"].match(digits, a + len(digits[a:b]) - len(digits[a:b].lstrip()), b)`: does this line begin (after any leading spaces) with `S/O`, `C/O` ...? The start position is moved past the spaces: `len(line) - len(line.lstrip())` is the number of leading spaces.
- `if care and len(segments) > 1:` there are several lines, so the whole care-of line is dropped: ignored text, reason `CARE_OF_REMOVED`.
- `elif care:` there is only one line, so only the marker itself is skipped (`ignored.append((care.start(), care.end(), ...))`) and the rest of the line is kept (`regions.append((care.end(), b))`).
- `else: regions.append((a, b))`: an ordinary line is kept.
- `pincode, pin_span = None, None`, then `for m in _PINCODE.finditer(digits):` for every six-digit number inside a kept region, store it. The **last** one wins, because a pincode is normally at the end. `m.group(1) + m.group(2)` joins `560` and `034` so `560 034` becomes `560034`.
- `tokens = [t for t in _address_tokens(digits, regions, pin_span) if t["norm"]]`: the words, leaving out empty ones.
- `foreign = [t for t in tokens if has_foreign_letters(t["norm"])]`, `tokens = [t for t in tokens if t not in foreign]`, `ignored += [...]`: take out words in other scripts and remember them as ignored.
- `if len(tokens) > ac["max_tokens"]: return failure("TOO_LONG", ...)`: too many words.
- `if foreign and not tokens and not pincode: return failure("UNSUPPORTED_SCRIPT", ...)`: nothing usable except other-script text.
- `if foreign: add_reason(... "NON_LATIN_TEXT_IGNORED" ...)`: some text was dropped.
- `for token in tokens: token["norm"] = rt["abbreviations"].get(token["norm"], token["norm"])`: expand abbreviations (`rd` becomes `road`, `nr` becomes `near`).
- **City**: `city, city_spans = None, []`, then `for size in range(rt["max_city_words"], 0, -1):` try the longest city names first (so `navi mumbai` is found before `mumbai`).
  - `hit = next((i for i in range(len(tokens) - size, -1, -1) if " ".join(t["norm"] for t in tokens[i : i + size]) in rt["cities"]), None)`: scan the words **from the end backwards**, joining `size` words, looking for one that is a known city or alias. `next(..., None)` returns the first hit or `None`.
  - `if hit is not None:` set `city` to the **main** name of that city (`bangalore` becomes `bengaluru`), remember the word positions, `del tokens[hit : hit + size]` removes the city words from the list so they are not counted as place words, and `break`.
- **Numbers and words**: `numbers, words, used = [], [], set()`; `used` holds positions already consumed.
- First loop (`for i, token in enumerate(tokens):`): numbered descriptors such as `2nd cross`, `cross 2`, `sector 5`.
  - `if token["norm"] in rt["descriptors"]:` the word is `cross`, `main`, `sector` ...
  - `for k in (i - 1, i + 1):` look at the word before it, then the word after it.
  - `value = _number_of(...) if 0 <= k < len(tokens) and k not in used else None`: if that neighbour exists and is unused, is it a number?
  - `if value:` store one item such as `{"value": "cross:2", ...}` with a position that spans both words, mark both as used, and `break`.
  - `used.add(i)`: the descriptor word is consumed even when it has no number, so it does not become a place word.
- Second loop (`for i, token in enumerate(tokens):`): everything not used.
  - `if i in used or norm in rt["ignored_words"]: continue`: skip consumed words and meaningless words (`road`, `flat`, state names ...).
  - `ordinal = _ORDINAL.fullmatch(norm)` and `if ordinal or _HOUSE_NUMBER.fullmatch(norm):` it is a number. `if sum(ch.isdigit() for ch in norm) <= 6:` numbers with more than six digits (phone numbers and the like) are ignored. Otherwise the value is stored (`2nd` stored as `2`).
  - `elif len(norm) > 2 and norm.isalpha():` a real word of three or more letters (two-letter words such as `KA` or `MG` say too little).
  - `stem = norm[:-1] if len(norm) > 4 and norm.endswith("s") and not norm.endswith("ss") else norm`: remove a plural `s` so `apartments` equals `apartment`. The word is stored with its `key` (the stem).
- `if not (pincode or city or numbers or words): return failure("UNPARSEABLE", ...)`: nothing recognisable.
- `parts = [...]` and the final `return {...}`: `ok`, `raw`, `pincode` and its position, `city` and its positions, `numbers`, `words`, `ignored`, `reasons`, and `normalized`, the parts joined with commas (the text shown to the user).

### `_spans(items)`

- `[(item["start"], item["end"]) for item in items]`: the positions of a list of items.

### `_single_status(base_value, cand_value)`

What it is for: compare one value that is either present or not: the pincode or the city.

- both `None` -> `"absent_both"` (nothing to compare);
- one `None` -> `"absent_one"` (one side lacks it);
- equal -> `"match"`; different -> `"mismatch"`.

### `_compare_lists(b_keys, c_keys, relate, min_coverage=None)`

What it is for: compare two lists of items (numbers, or place words) and say how well they agree.

- `pairs = pair_up(b_keys, c_keys, relate)`: pair the items one to one.
- `left_b`, `left_c`: the positions of base and candidate items that found no partner.
- `coverage = 2 * sum(p[3] for p in pairs) / (len(b_keys) + len(c_keys)) if b_keys or c_keys else 1.0`: how much of both lists was paired, as a fraction. 1.0 means everything. (With two empty lists, 1.0.)
- The `if/elif` chain gives the **status**:
  - both lists empty -> `absent_both`;
  - one list empty -> `absent_one`;
  - leftovers on **both** sides -> `partial` if `min_coverage` was given and `coverage` reaches it (place words), otherwise `mismatch`;
  - leftovers on **one** side -> `subset` (one side has extra items);
  - no leftovers -> `match` if every pair is `exact`, otherwise `partial` (a spelling difference, or `12` against `12/3`).
- Returns the status, the pairs and the leftovers.

### `_highlight_list(result, b_spans, c_spans, out)`

- For each pair: both items get `match` if the pair is exact, otherwise `spelling`.
- `conflict = result["status"] == "mismatch"`: leftovers are `conflict` when the status is mismatch, otherwise `missing` (base side) or `extra` (candidate side).
- It adds the spans to `out["base_spans"]` and `out["cand_spans"]`.

### `_ADDRESS_NOTES` and `_ADDRESS_PARTS`

- `_ADDRESS_NOTES` maps `(part, status)` to `(reason code, message)`. For example `("pincode", "near")` gives `PINCODE_NEAR`. A part that matches needs no reason, so `("pincode", "match")` is not in the table.
- `_ADDRESS_PARTS` gives each part a readable name for messages (`number` is "house or street numbers").

### `compare_addresses(base, cand, cfg, today)`

What it is for: compare two parsed addresses part by part.

- `ac = cfg["address"]`; `reasons = [...]` from parsing.
- The inner functions:
  - `number_relation(a, b)`: equal numbers are `exact`; if the part before the first `/` of one equals the other (`12` and `12/3`) the relation is `prefix`; otherwise unrelated. The `prefix_credit` setting (0.7) only makes exact matches be paired before prefix matches.
  - `word_rel(a, b)`: uses `word_relation` for place words (exact, or a small spelling difference).
- `numbers = _compare_lists(...)` and `text = _compare_lists(..., ac["text_min_coverage"])`: compare the numbers and the place words. For place words, a lot of overlap (60 percent) is still `partial`.
- `statuses = {...}`: the status of each of the four parts. The `"text"` entry says `"spelling"` when every word was paired but some by spelling (`status == "partial"` and no leftovers).
- `n = ac["pincode_near_prefix"]` (3): if the pincodes differ but share the **first three digits**, they are probably typed wrongly, not different places. `others = [...]`: the status of the other parts. If another part is a mismatch the pincode stays `mismatch`, otherwise it becomes `near`. So a near pincode is forgiven only when nothing else disagrees.
- `for part, status in statuses.items(): if (part, status) in _ADDRESS_NOTES: add_reason(reasons, cfg, *_ADDRESS_NOTES[part, status])`: add the reason for every part (the `*` unpacks the code and message).
- `present = {...}`: for each part, what the base has.
- `one_sided = [p for p, s in statuses.items() if s == "absent_one"]`: parts that exist on one side only.
- The loop `for side, lacking in (("candidate", ...), ("base", ...)):` builds a message such as "The candidate lacks the pincode." and adds `INCOMPLETE_ADDRESS`. (Because a code is only added once, only the first such message is kept.)
- `if not (statuses["pincode"] == "match" or any(pair[2] == "exact" for pair in numbers["pairs"])):` the **anchor rule**: the pincode must match, or at least one house number must match exactly. If not, `NO_ANCHOR_MATCH`: two addresses with no hard point in common cannot be tied together, even if the words look alike.
- `exact = all(s in ("match", "absent_both") for s in statuses.values())`: everything matched. Then the `EXACT` / `NORMALIZED_EQUAL` reason.
- **Highlights**: `kinds = {...}` maps a status to a span kind (`near` is shown as `spelling`). `pin_spans` is the pair of pincode positions. The loop over `("pincode", ...)` and `("city", ...)` adds the spans: `kinds.get(status, "missing")` for the base side and `"extra"` for the candidate side (used when the part exists on one side only).
- `_highlight_list(numbers, ...)` and `_highlight_list(text, ...)`: the spans of numbers and words.
- `values = {...}` and `out["components"] = [...]`: the table of the four parts (status, base value, candidate value) returned to the frontend.
- `return out`.

---

## 8. Sections 7 to 10: identity numbers, amounts, email, phone and short text

These five types were added after the walkthrough above was written, so they are described here by rule rather
than line by line. Each one follows the same shape as the three older types: a `parse_*` function that cleans
one value, and a `compare_*` function that turns the difference into reasons.

Every type takes an optional `kind`, which narrows what the value is. `"type": "pan"` is short for
`"type": "id", "kind": "pan"`. A kind that the settings do not describe is refused as a bad request.

### `id`: Aadhaar, PAN, passport, voter ID, driving licence

`parse_id` keeps only A-Z and 0-9, so spaces, dots and dashes never matter, and `*` is read as the mask letter
`X`. It then asks two questions: is the number **masked** (a run of four or more `X`, as a bureau prints
`XXXXXXXX1234`), and is it **full** (does it have the shape `id.patterns` gives for its kind).

`compare_ids` works down this list and stops at the first line that fits:

| Situation | Reason | Colour |
|---|---|---|
| both numbers whole, and the same | `EXACT` / `NORMALIZED_EQUAL` | green |
| the same text, but not shaped like a number of this kind | `ID_FORMAT_DOUBTFUL` | yellow |
| same length, and the same once look-alikes are folded (`I` and `1`, `O` and `0`) | `ID_OCR_VARIANT` | yellow |
| one side masked or partial, and the visible end agrees | `ID_MASKED` / `ID_PARTIAL` | yellow |
| one number is the tail of the other | `ID_PARTIAL` | yellow |
| anything else | `ID_DIFFERENT` (plus `POSSIBLE_TYPO` when one character apart) | red |

Green needs the whole number on both sides. A masked or partial number can never be green, because the hidden
part cannot be checked.

### `amount`

`parse_amount` reads one number, with Indian or western digit grouping (`12,50,000` and `1,250,000` both work),
a scale word that follows it (`12.5 lakh`, `5 cr`, `50k`) and a currency written anywhere in the text
(`amount.currencies`). Currencies are **never converted**: a rate is the caller's business, not this function's.

- the same number, and no currency doubt: green
- apart by no more than `amount.round_tolerance` (1.00 by default): `AMOUNT_ROUNDED`, yellow
- apart by no more than `amount.near_percent` (0 by default, so off): `AMOUNT_NEAR`, yellow
- only one side names a currency, and it is not `amount.default_currency`: `CURRENCY_ASSUMED`, yellow
- two different currencies: `CURRENCY_MISMATCH`, red
- any other difference: `AMOUNT_DIFFERENT`, red

### `email`

`parse_email` finds the address and lower-cases it. It also works out the **mailbox** it stands for: on the
domains in `email.ignore_dots_domains` the dots inside the name are dropped, and a `+tag` is cut off when
`email.ignore_tags` is true. The same address is green; the same mailbox written differently is
`EMAIL_ALIAS`, yellow; anything else is `EMAIL_DIFFERENT`, red.

### `phone`

`parse_phone` keeps the digits, then takes off a country code from `phone.country_codes` (as `+91`, `0091` or
a bare prefix when the length fits) or a single leading zero. `+91 98765 43210`, `09876543210` and
`9876543210` are therefore the same number, and green.

- one side names a country code that is not `phone.default_country`, the other names none:
  `PHONE_COUNTRY_ASSUMED`, yellow
- one number is the tail of the other, sharing at least `phone.min_visible_tail` digits: `PHONE_PARTIAL`, yellow
- two different country codes, or different digits: `PHONE_DIFFERENT`, red

### `text`: gender, relationship, nationality, and the names of bodies and courses

`parse_text` works in two ways at once.

1. **A known term.** When the kind has a word list in `text.vocabularies`, the whole cleaned phrase is looked
   up in it: `M` and `Male` both become the term `male`, `F/O` becomes `father`. When both sides have a term,
   only the terms are compared: equal is green, different is `TEXT_DIFFERENT`, red.
2. **Word by word.** Otherwise the text is split into words. A short form in `text.abbreviations` is expanded
   first, and it may stand for several words (`MS` becomes `master science`). The words in
   `text.ignored_words` (`of`, `the`, `at`) are dropped. The two word lists are then paired exactly as the
   place words of an address are, with a little room for spelling.

So `Anna University` and `Anna Univ.` are green, `University Anna` is `TOKEN_ORDER_DIFFERENT` (yellow),
`Anna Universty` is `SPELLING_VARIANT` (yellow), and `Madras University` is `WORDS_MISMATCH` (red).

## 9. Section 11: decide (reasons -> colour)

### `decide(outcome, cfg)`

What it is for: this is where the **colour is chosen**. It reads the reasons that a `compare_*` function found. Nothing else decides the colour: there is no score and no confidence.

- `reasons: list[Json] = list(outcome["reasons"])`: a copy, so the outcome is not changed.
- `flag = max((FLAG_OF_SEVERITY[r["severity"]] for r in reasons), key=FLAG_RANK.__getitem__, default="green")`: turn each reason into a colour, then take the **worst** one. `key=FLAG_RANK.__getitem__` makes `max` compare colours by their number (red 2 beats yellow 1 beats green 0). `default="green"` is used when there are no reasons.
- `if flag == "green" and not outcome["exact"] and all(REASONS[r["code"]] == "info" for r in reasons):` the **safety net**: the result is green but the comparison did not prove the values equal, and only harmless reasons exist. Add `DIFFERENCE_UNCLASSIFIED` and make it yellow. This stops a green that nobody can explain. (It looks at the severity in the `REASONS` table, so a `severity_overrides` entry that turns a reason into `info` still gives green.)
- `return {"flag": flag, "reasons": reasons}`.

### `build_result(source, source_id, base_raw, cand_raw, outcome, cfg)`

What it is for: build the dictionary that the caller receives for one candidate.

- `decision = decide(outcome, cfg)` and `flag = decision["flag"]`.
- `result: Json = {...}`:
  - `source`, `id`: the document name and its unique id (`bank#1`, `bank#2` if the name is used twice);
  - `raw`: the candidate text as sent; `normalized`: the cleaned text;
  - `status` (`match`, `warning`, `mismatch`) and `color`;
  - `needs_review`: true for anything that is not green;
  - `decided_by`: always `"fuzzy"` for now; `fuzzy`: the colour again, so a future `llm` block can sit next to it;
  - `reasons`: only `code`, `severity` and `message` of each;
  - `highlight`: the base and candidate text cut into pieces by `build_segments`, or an empty list when that text is `None`.
- `if outcome.get("components"): result["components"] = outcome["components"]`: dates and addresses add their part-by-part table.
- `return result`.

### `roll_up(items)`

What it is for: one comparison speaks for a group of comparisons (all candidates of a field, or all fields).

- `worst = max(items, key=lambda x: FLAG_RANK[x["color"]])`: the item with the worst colour.
- `return {"status": ..., "color": ..., "needs_review": any(...)}`: copy the status and colour of that worst item, and say needs review if any item needs it.

---

## 10. Section 12: verify (the request goes in, the report comes out)

### `COMPARERS`

- `{"name": compare_names, "dob": compare_dobs, "address": compare_addresses}`: which function compares which type. To add a new field type you would add a `parse_*`, a `compare_*` and one line here.

### `parse_value(field_type, value, cfg, side, today)`

What it is for: check a value, then hand it to the right parser.

- `if is_missing(value, cfg): return failure("BASE_MISSING" if side == "base" else "MISSING_VALUE", ...)`: empty, `None` or `N/A`.
- `text = show(value)` and `if text is None: return failure("UNPARSEABLE", ...)`: not text, number or date (a list, a dictionary, `True` ...).
- `if len(text) > cfg["limits"]["max_text_length"][field_type]: return failure("TOO_LONG", ...)`: longer than the limit for that field type (a protection against huge input).
- Then it calls `parse_name`, `parse_address`, or (the last line) `parse_dob`, which also receives the original `value` because a real date object is allowed.

### `compare_one(field_type, base, value, cfg, today)`

What it is for: compare the already parsed base with one candidate value.

- `cand = parse_value(field_type, value, cfg, "candidate", today)`: parse the candidate.
- `broken = base if not base["ok"] else cand if not cand["ok"] else None`: if the base failed to parse, use that failure; else if the candidate failed use that; else `None`.
- `if broken:` build a minimal outcome: one reason with the failure code (`MISSING_VALUE`, `UNPARSEABLE` ... all of them have severity `fail`), `exact` false, no cleaned text and no spans. This is how a missing or unreadable value becomes **red**.
- `result: Json = COMPARERS[field_type](base, cand, cfg, today)`: both parsed fine, so run the right comparer. `return result`.

### `_read_candidates(candidates, where, cfg)`

What it is for: tidy the candidates of one check.

- `if isinstance(candidates, Mapping): candidates = [{"source": k, "value": v} for k, v in candidates.items()]`: the shorthand `{"aadhaar": "...", "pan": "..."}` is turned into the long list form.
- `if not isinstance(candidates, list) or not candidates: raise InputError(...)`: it must be a non-empty list.
- `if len(candidates) > cfg["limits"]["max_candidates"]: raise InputError(...)`: not too many.
- `if not all(isinstance(c, Mapping) and isinstance(c.get("source"), str) and c["source"].strip() for c in candidates): raise InputError(...)`: every candidate must be an object with a non-empty `source` text.
- `names = [c["source"].strip() for c in candidates]`: the source names, trimmed.
- `seen: dict[str, int] = {}` and `items = []`: a counter per name, and the result.
- The loop `for name, candidate in zip(names, candidates, strict=True):` (`strict=True` makes sure both lists have the same length): `seen[name] = seen.get(name, 0) + 1` counts how many times this name was seen; `unique = f"{name}#{seen[name]}" if names.count(name) > 1 else name` gives `bank#1`, `bank#2` when the same source appears twice, otherwise the plain name.
- `items.append({"source": name, "id": unique, "value": candidate.get("value")})`: the tidy candidate. A missing `value` becomes `None` (and so a red `MISSING_VALUE` later). Any other key, such as an old `ocr_confidence`, is ignored.

### `read_checks(checks, cfg)`

What it is for: check the whole request. A wrong request raises `InputError`; a wrong value never does.

- `if isinstance(checks, Mapping) and "checks" in checks: checks = checks["checks"]`: accept both `[...]` and `{"checks": [...]}`.
- `if not isinstance(checks, list) or not checks: raise InputError(...)` and the check on `max_checks`.
- `clean = []` then `for n, check in enumerate(checks):` with `where = f"checks[{n}]"` so an error can say which check is wrong.
- `if not isinstance(check, Mapping): raise InputError(...)`.
- `field_type = str(check.get("type", "")).strip().lower().replace(" ", "_")`: read the type, tidy it. The next line maps `date_of_birth` and `birth_date` to `dob`.
- `if field_type not in FIELD_TYPES: raise InputError(...)`.
- `field` must be a non-empty text; `"base" not in check` raises (the key must be present, though its value may be `None`).
- `clean.append({...})`: the tidy check: `field`, `type`, `base` and the candidates from `_read_candidates`.

### `parse_safely(...)` and `compare_safely(...)`

What they are for: **one bad value must never stop the whole request.**

- `parse_safely`: calls `parse_value` inside `try`. On an unexpected error (`except Exception as exc`) it writes a log line with **only the error type and the field type** (`type(exc).__name__`), never the value, and returns `failure("INTERNAL_ERROR", ...)`.
- `compare_safely`: the same around `compare_one`. On error it logs the same way and returns an outcome with a single `INTERNAL_ERROR` reason, so the result is red.

### `run_checks(checks, cfg, request_id, today)`

What it is for: the whole job.

- `request_id = request_id or uuid.uuid4().hex[:12]`: use the given id or make a random 12-character one.
- `today = today or dt.date.today()`: dates are checked against today (a date of birth cannot be in the future). Tests pass a fixed `today`.
- `fields = []` and `counts = {"match": 0, "warning": 0, "mismatch": 0}`: the results and the totals.
- `for check in read_checks(checks, cfg):` for every check:
  - `base = parse_safely(check["type"], check["base"], cfg, "base", today)`: parse the base **once**, for all its candidates.
  - `comparisons = []`, then `for candidate in check["candidates"]:`
  - `outcome = compare_safely(...)`: compare.
  - `comparison = build_result(...)`: build the result (colour, status, reasons, highlights).
  - `counts[comparison["status"]] += 1` and `comparisons.append(comparison)`.
  - `fields.append({...})`: the field: its label, type, the base text and cleaned base text, the rolled-up colour of its worst comparison (`**roll_up(comparisons)`), and all comparisons.
- `log.info("verified request_id=%s checks=%d %s config=%s", ...)`: one log line with counts and the settings fingerprint. No values.
- `return {...}`: the report: `config_hash`, `config_label`, `mode` (always `"fuzzy"`), `request_id`, `overall` (the worst field plus the counts) and `fields`.

### `create_verifier(config=None, *, config_path=None)`

What it is for: the function you call first, once. It returns the `verify` function.

- `cfg = prepare_config(config) if config is not None else load_config(config_path)`: use a settings dictionary you pass in (handy for tests), or read the file.
- `mode = cfg["mode"]` and then one branch per mode:
  - `if mode == "fuzzy": engine = run_checks`: the rules in this file do the work.
  - `elif mode == "hybrid":` raises `ModeNotImplementedError("mode 'hybrid' is not developed yet; use 'fuzzy'")`. The comment marks where the future hybrid engine goes (fuzzy first, then an LLM review).
  - `elif mode == "llm":` raises `ModeNotImplementedError("mode 'llm' is not developed yet; use 'fuzzy'")`. The comment marks where the future AWS Bedrock engine goes.
  - `else:` a mode name that has no branch (the settings check should have caught it already) also raises.
  - These modes never silently fall back to fuzzy. When a mode is built later, its branch sets `engine` to a function with the same arguments as `run_checks` and the same report as the result.
- `def verify(checks, *, request_id=None, today=None):` the inner function. The `*` means `request_id` and `today` must be given by name. It calls `engine(checks, cfg, request_id, today)`.
- `return verify`: because `verify` remembers `cfg`, the settings are loaded once. It changes nothing outside itself, so it is safe to share between threads.

---

## 11. Section 13: the command line

### `read_env_file(path)`

- `values = {}`; `for line in Path(path).read_text(encoding="utf-8").splitlines():` read the file line by line.
- `key, sep, value = line.strip().partition("=")`: split at the first `=`. `sep` is `"="` if there was one, else empty.
- `if sep and key and not key.startswith("#"):` keep only real `KEY=value` lines (comments start with `#`).
- `values[key.strip()] = value.strip().strip("\"'")`: store it, trimming spaces and quotes.
- `return values`.

### `main(argv=None)`

What it is for: `python cross_verify.py -i input.json`.

- `parser = argparse.ArgumentParser(...)` and the four `add_argument` lines: `--input`/`-i` (required: a file, or `-` for standard input), `--config` (another settings file), `--env-file` (default `.env`), `--compact` (one line of output).
- `args = parser.parse_args(argv)`: read the command line.
- `if Path(args.env_file).is_file():` and the loop: if a `.env` file exists, copy each `KEY=value` into the environment with `os.environ.setdefault` (a value you already set in the environment wins).
- `logging.basicConfig(level=os.environ.get("CROSS_VERIFY_LOG_LEVEL", "INFO").upper(), stream=sys.stderr)`: show log lines on the screen's error stream at the chosen level.
- `try:` then `source = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8")`: the keyboard or a file. `with source:` closes it afterwards. `report = create_verifier(config_path=args.config)(json.load(source))`: read the JSON, create the verifier, run it. (The `# noqa: SIM115` comment on that line only quiets the code checker.)
- `except (CrossVerifyError, OSError, ValueError) as exc:` any of our errors, a file problem, or bad JSON: print `error: ...` on the error stream and `return 2`.
- `print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))`: print the report; `ensure_ascii=False` keeps non-English text readable.
- `return 0`: success.

### The last two lines

- `if __name__ == "__main__": raise SystemExit(main())`: when the file is run directly (not imported), run `main()` and use its return value (0 or 2) as the exit code.

---

## 12. Three worked examples (real values from the code)

### A name: `kumar sam` against `sam kumar`

1. `parse_name` gives base tokens `kumar` (0-5) and `sam` (6-9); candidate tokens `sam` (0-3) and `kumar` (4-9).
2. `compare_names`: the cleaned lists differ, so it goes on. `pair_up` pairs `kumar` with `kumar` and `sam` with `sam` (both `exact`, similarity 1.0). No leftovers.
3. `_crossing`: base position 0 pairs with candidate position 1, and base position 1 with candidate position 0: they cross, so `moved` holds both. Reason: `TOKEN_ORDER_DIFFERENT` (warn, structural).
4. `decide`: the worst severity is warn, so **yellow**.
5. The highlight kinds are `moved` for all words.
6. Result: **yellow**, reasons `TOKEN_ORDER_DIFFERENT`, `needs_review` true.

### A date: `12-03-1998` against `03/12/1998`

1. `parse_dob` reads both with `_numeric_date`, always day first. The base is day 12, month 3, year 1998. The candidate is day 3, month 12, year 1998.
2. `compare_dobs`: the day (12 and 3) and the month (3 and 12) differ, the year is equal. `same` is false.
3. Reason: `DATE_DIFFERENT` (fail). The digit strings `19980312` and `19981203` differ by more than one digit, so there is no `POSSIBLE_TYPO`.
4. `decide`: a fail reason makes it **red**.
5. The day and month are marked `conflict`, the year `match`.
6. Result: **red**, reasons `DATE_DIFFERENT`.

### An address: the base against `12, 5th Main, Indiranagar, Bengaluru 560038`

1. Base: pincode `560034`, city `bengaluru` (from `Bangalore`), numbers `cross:2` and `402`, words `sai residency koramangala`.
2. Candidate: pincode `560038`, city `bengaluru`, numbers `main:5` and `12`, words `indiranagar`.
3. Statuses: pincode `mismatch` (the first three digits agree, but other parts disagree, so it is **not** forgiven as `near`), city `match`, number `mismatch`, text `mismatch`.
4. Reasons: `PINCODE_MISMATCH`, `NUMBER_MISMATCH`, `WORDS_MISMATCH`, and `NO_ANCHOR_MATCH` (neither pincode nor a number matches).
5. `decide`: fail -> **red**.
6. Result: **red**, with all four reasons above.

---

## 13. Where do I change what?

| I want to... | Change this |
|---|---|
| change a colour rule for one reason (for example extra initials become green) | `severity_overrides` in `cross_verify_config.json`: `{"EXTRA_INITIALS": "info"}` |
| allow more spelling mistakes in addresses | `address.edit_allowance` |
| change the shape a PAN or Aadhaar must have | `id.patterns` and `id.lengths` |
| change which characters count as look-alikes | `id.lookalikes` |
| add a currency symbol or a word like lakh | `amount.currencies`, `amount.scales` |
| allow amounts a little apart to be yellow | `amount.round_tolerance`, `amount.near_percent` |
| add a country dialling code | `phone.country_codes` |
| add a short form such as Univ or MBA | `text.abbreviations` |
| add a word to a list such as gender or relationship | `text.vocabularies` |
| change how far back a birth date may be | `dob.max_age` |
| add a city or an alias | `address.cities` |
| add an address abbreviation | `address.abbreviations` |
| add a new reason code | the `REASONS` table, then add the reason where the rule applies |
| add a new field type | a new `parse_*`, a new `compare_*`, one line in `COMPARERS`, and the type in `FIELD_TYPES` |
| point to another settings file | `--config`, or the environment variable `CROSS_VERIFY_CONFIG_PATH` |
