# SedLite Stream Editor

An implementation of a useful subset of `sed`, written in Python with nothing but the standard library. The script is parsed once into a list of command objects, then applied to each input line as it is read — the input is never stored.

This was an individual coursework project for **Software Construction** during my postgraduate study at the University of New South Wales. The specification defined the required behaviour by a reference implementation rather than prose, so most of the work was reading `sed` closely enough to match it exactly — including its error messages and exit statuses.

## What it does

```
usage: sedlite [-i] [-n] [-f <script-file> | <sed-command>] [<files>...]
```

| Command | What it does |
| --- | --- |
| `q` | Quit — and it stops *reading* input, not merely printing it |
| `p` | Print the pattern space |
| `d` | Delete: cancel the automatic output and end this line, so anything written after it is never reached |
| `s` | Substitute, with `g`, arbitrary delimiters, `\1`–`\9` backreferences and `&` |
| `a` `i` `c` | Append, insert, change text |
| `:` `b` `t` | Label, unconditional branch, branch-if-substituted |

Addresses may be a line number, `$`, a `/regex/`, or a range of two of those. `-n` suppresses the automatic output, `-f` reads the script from a file, and `-i` edits files in place. A script beginning with `#n` implies `-n`, as in real `sed`.

Several input files are read as **one stream**, so line numbers and `$` run across all of them rather than restarting per file — except under `-i`, where each file is edited independently and both the numbering and any open range reset.

## It runs the classic sed showcase scripts

The three scripts under `tests/` are the sort of thing `sed` is famous for — reversing a line, converting decimal to binary, spelling out digits — written with labels and branches. They are also **GNU** `sed` syntax, which the BSD `sed` shipped with macOS rejects outright:

```console
$ printf 'hello world\n' | python3 sedlite.py -f tests/rev.script
dlrow olleh
$ printf 'hello world\n' | sed -f tests/rev.script
sed: 10: tests/rev.script: \2 not defined in the RE

$ echo 15 | python3 sedlite.py -f tests/decimal2binary.script
1111
$ echo 15 | sed -f tests/decimal2binary.script
sed: 13: tests/decimal2binary.script: \1 not defined in the RE

$ echo 1010 | python3 sedlite.py -n -f tests/binary2words.script
1010 in words is:
one
zero
...
```

## Design notes

**One line of look-ahead is what makes `$` possible.** `preread()` is a generator that holds a single line back and yields `(line, is_last_line)` pairs. That is the entire mechanism: the last line is known one line early, so `$` can be answered without ever buffering the input. Memory stays constant no matter how large the input is.

**The script is scanned character by character, not split.** `Parser` walks the script text with an explicit pointer, because `sed` scripts cannot be tokenised by splitting: the `s` command takes an arbitrary delimiter, `a`/`i`/`c` swallow text to end of line, `#` comments run to end of line, and commands may be separated by `;` *or* newline. `clean()` skips separators and comments between commands; `delspace()` skips whitespace inside one.

**Labels are resolved before anything runs.** After parsing, `find_labels()` builds the label table and every `b`/`t` is checked against it. A branch to a label that does not exist is a script error reported up front, not a surprise on line 4000.

**In-place editing is atomic.** `-i` writes to a `NamedTemporaryFile` created **in the same directory as the original**, then `os.replace()`s it over the target. Same directory means same filesystem, which means the rename cannot fail part-way and leave a half-written file where the original used to be.

**Errors flush stdout first.** `terminate()` calls `sys.stdout.flush()` before writing to stderr, so the diagnostic appears after the output it belongs after rather than racing ahead of it through a different buffer.

**Empty matches follow the sed rule, not Python's.** In `s///g`, an empty match immediately following a previous match does not count — otherwise a pattern such as `s/x*/-/g` produces a different result from `sed`.

## Requirements

Python 3.9 or newer. Nothing to install.

`dash` is needed to run the test scripts (`/bin/dash` on macOS; `apt install dash` on Debian/Ubuntu).

## Run

```bash
python3 sedlite.py '3q' file.txt              # quit after line 3
python3 sedlite.py -n '/error/p' log.txt      # print only matching lines
python3 sedlite.py 's|/usr/bin|/usr/local/bin|g' paths.txt
python3 sedlite.py -i 's/colour/color/g' *.txt
seq 1 20 | python3 sedlite.py '10,$d'         # keep the first nine lines
```

## Test

`t.sh` is self-contained and runs anywhere — 71 cases whose expected values come from the specification's examples or were worked out by hand from `sed` semantics:

```bash
sh t.sh          # pass/fail summary
sh t.sh -v       # also list the cases that passed
```

The ten `test?.sh` scripts are the submitted suite, and they work differently. Each case runs **twice** — once against `sedlite.py`, once against the course's reference implementation invoked as `2041 sedlite` — and passes only if stdout, stderr *and* exit status all agree. The specification defined correct behaviour *as* that reference rather than in prose, which is why the suite is built this way.

The consequence is that these scripts need the university's lab machines. Anywhere else, `2041` does not exist and every case reports as failed **on the reference side, not on ours**:

```console
$ dash test0.sh
  stderr: expected [test0.sh: 31: 2041: not found] got []
  status: expected [127] got [0]
```

`t.sh` exists precisely so that something can be run without it. Each `test?.sh` states in its header what it checks and why:

| Script | Area |
| --- | --- |
| `test0` | `q` — its addresses, its interaction with `-n`, and that it stops reading |
| `test1` | `p` and `-n` are independent: `p` always prints, `-n` only disables the automatic output |
| `test2` | `d` cancels output and ends the line, so later commands are unreachable |
| `test3` | `s` basics: which match is replaced, the `g` modifier, restricting addresses |
| `test4` | `s` delimiters and escaping — any non-whitespace delimiter, backslashes surviving |
| `test5` | Several commands in one script: separators, ordering, `#` to end of line |
| `test6` | `-f` and multiple input files read as one stream |
| `test7` | `$` and ranges — a range ends only on a *later* line |
| `test8` | Error handling: message on stderr, stdout empty, exit status 1 — all three compared |
| `test9` | `a`, `i`, `c`, branching with `b`/`t`, and `-i` |

## Known limitations

- **Only the subset above is implemented.** No hold space (`h`/`H`/`x`/`g`/`G`), no `y`, no `w`/`r`, no `N`/`D`/`P`, no `!` negation, no `0,/re/` address form.
- **Regexes are Python's, not POSIX BRE.** Most everyday patterns behave the same, but the syntaxes are not identical — `\+` and `\?` in particular mean different things.
- **`-i` keeps no backup suffix.** `sed -i.bak` has no equivalent here.
- **The program name in messages is hard-coded** to `sedlite` rather than taken from `argv[0]`, which the specification permits.

## Project structure

```
sedlite.py            # the whole implementation: Parser, Command, execute, cache-free streaming
t.sh                  # development comparison harness, expected values from the spec or hand-worked
test-helper-lib.sh    # shared assertions for the test scripts below
test0.sh .. test9.sh  # the submitted suite, one area each
tests/                # sample sed scripts used for the demos above
```

## License

[MIT](LICENSE)

## Author

**Tianshu Shen** — this was an individual assignment, written and tested by me.
