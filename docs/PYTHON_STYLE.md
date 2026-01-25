# Python Style Guide

Complete reference for active ruff rules in this project.

**Active rule groups:** E, W, F, I, UP, S, A, ARG, B, C4, EM, ISC, INP, N, PERF, PIE, PL, PT, PTH, RET, RUF, SLF, TC

**Legend:** `[fix]` = has auto-fix available

---

## Table of Contents

1. [E - pycodestyle errors](#e---pycodestyle-errors)
2. [W - pycodestyle warnings](#w---pycodestyle-warnings)
3. [F - Pyflakes](#f---pyflakes)
4. [I - isort](#i---isort)
5. [UP - pyupgrade](#up---pyupgrade)
6. [S - Security (bandit)](#s---security-bandit)
7. [A - flake8-builtins](#a---flake8-builtins)
8. [ARG - Unused arguments](#arg---unused-arguments)
9. [B - flake8-bugbear](#b---flake8-bugbear)
10. [C4 - flake8-comprehensions](#c4---flake8-comprehensions)
11. [EM - Exception messages](#em---exception-messages)
12. [ISC - Implicit string concat](#isc---implicit-string-concat)
13. [INP - Namespace packages](#inp---namespace-packages)
14. [N - pep8-naming](#n---pep8-naming)
15. [PERF - Performance](#perf---performance)
16. [PIE - Misc lints](#pie---misc-lints)
17. [PL - Pylint](#pl---pylint)
18. [PT - pytest](#pt---pytest)
19. [PTH - pathlib](#pth---pathlib)
20. [RET - Returns](#ret---returns)
21. [RUF - Ruff-specific](#ruf---ruff-specific)
22. [SLF - Private access](#slf---private-access)
23. [TC - Type checking](#tc---type-checking)
24. [Test-specific rules](#test-specific-rules)

---

## E - pycodestyle errors

Semantic code style rules. Formatting rules (E1, E2, E3) are handled by `ruff format`.

### Imports (E4xx)

| Rule | Description |
|------|-------------|
| E402 | module-import-not-at-top-of-file |

### Line length (E5xx)

| Rule | Description |
|------|-------------|
| E501 | line-too-long (120 chars in this project) |

### Statements (E7xx)

```python
# E711 - none comparison [fix]
if x == None:  # Wrong
if x is None:  # Correct

# E712 - true/false comparison [fix]
if x == True:   # Wrong
if x:           # Correct

# E721 - type comparison
if type(x) == int:      # Wrong
if isinstance(x, int):  # Correct

# E722 - bare except
try:
    ...
except:  # Wrong - catches everything including KeyboardInterrupt
    ...
except Exception:  # Correct
    ...

# E731 - lambda assignment [fix]
f = lambda x: x + 1  # Wrong
def f(x): return x + 1  # Correct

# E741 - ambiguous variable name
l = 1  # Wrong - looks like 1
O = 0  # Wrong - looks like 0
I = 1  # Wrong - looks like l
```

### Critical (E9xx)

| Rule | Description |
|------|-------------|
| E902 | io-error |
| E999 | syntax-error |

---

## W - pycodestyle warnings

| Rule | Description |
|------|-------------|
| W505 | doc-line-too-long |
| W605 | invalid-escape-sequence [fix] |

```python
# W605 - invalid escape sequence
path = "C:\new\folder"   # Wrong - \n is newline
path = r"C:\new\folder"  # Correct - raw string
path = "C:\\new\\folder" # Correct - escaped
```

---

## F - Pyflakes

Core checks for undefined names, unused imports/variables.

### Imports (F4xx)

```python
# F401 - unused import [fix]
import os  # Wrong if os is never used

# F403 - import star
from module import *  # Wrong - unclear what's imported

# F405 - undefined from import star
from module import *
print(undefined_name)  # May be from *, hard to trace
```

### Format strings (F5xx)

```python
# F501-F509: % formatting errors
"Hello %s %s" % (name,)  # Wrong - missing argument

# F521-F525: .format() errors
"{} {}".format(x)  # Wrong - missing argument

# F541 - f-string without placeholders [fix]
f"Hello world"  # Wrong - no {} placeholders
"Hello world"   # Correct
```

### Variables (F8xx)

```python
# F811 - redefined while unused [fix]
def foo(): pass
def foo(): pass  # Wrong - first foo never used

# F821 - undefined name
print(undefined_variable)  # Error

# F841 - unused variable [fix]
x = compute()  # Wrong if x never used
_ = compute()  # Correct - explicit discard
```

---

## I - isort

Import order: stdlib → third-party → local. Also handled by `ruff format`.

| Rule | Description |
|------|-------------|
| I001 | unsorted-imports [fix] |
| I002 | missing-required-import [fix] |

---

## UP - pyupgrade

Modernize code for Python 3.11+.

### Type annotations (UP006, UP007) [fix]

```python
# Wrong - old style
from typing import List, Optional, Dict, Tuple, Set

def process(
    items: List[str],
    mapping: Dict[str, int],
    result: Optional[str],
) -> Tuple[int, ...]: ...

# Correct - Python 3.9+
def process(
    items: list[str],
    mapping: dict[str, int],
    result: str | None,
) -> tuple[int, ...]: ...
```

### super() (UP008) [fix]

```python
# Wrong
class Child(Parent):
    def __init__(self):
        super(Child, self).__init__()

# Correct
class Child(Parent):
    def __init__(self):
        super().__init__()
```

### Other common rules

| Rule | Wrong | Correct |
|------|-------|---------|
| UP004 | `class C(object):` | `class C:` |
| UP010 | `from __future__ import ...` | Remove (Py3.11+) |
| UP015 | `open(f, "r")` | `open(f)` |
| UP018 | `str("text")` | `"text"` |
| UP032 | `"{}".format(x)` | `f"{x}"` |
| UP034 | `(x + y)` when unneeded | `x + y` |

---

## S - Security (bandit)

### Assertions (S101)

```python
# Wrong in production - stripped with -O flag
def validate(user_id):
    assert user_id > 0  # S101

# Correct
def validate(user_id):
    if user_id <= 0:
        raise ValueError("user_id must be positive")
```

**Note:** S101 is disabled in tests.

### Hardcoded secrets (S105-S107)

```python
# Wrong
password = "secret123"  # S105
connect(password="secret")  # S106
def login(password="default"):  # S107
    ...

# Correct
password = os.environ["PASSWORD"]
connect(password=get_password())
```

### Subprocess (S603, S607)

```python
# S603 - subprocess without shell check
# S607 - partial executable path

subprocess.run(["git", "status"])  # Flagged

# In production, be explicit or add noqa:
subprocess.run(
    ["/usr/bin/git", "status"],  # Full path
    check=True,
)
```

**Note:** S603, S607 are disabled in tests.

### Other security rules

| Rule | Issue |
|------|-------|
| S102 | exec() usage |
| S108 | Hardcoded /tmp path |
| S110 | try/except/pass (swallows errors) |
| S301 | pickle usage (deserialization attack) |
| S307 | eval() usage |
| S324 | Insecure hash (MD5, SHA1) |
| S506 | unsafe YAML load |
| S608 | SQL injection risk |

---

## A - flake8-builtins

Don't shadow Python builtins.

| Rule | Description |
|------|-------------|
| A001 | builtin-variable-shadowing |
| A002 | builtin-argument-shadowing |
| A003 | builtin-attribute-shadowing |
| A004 | builtin-import-shadowing |

```python
# Wrong
list = [1, 2, 3]        # A001 - shadows list()
id = 42                 # A001 - shadows id()
def func(type): ...     # A002 - shadows type()
class C:
    dict = {}           # A003 - shadows dict()

# Correct
items = [1, 2, 3]
item_id = 42
def func(type_name): ...
class C:
    mapping = {}
```

Common builtins to avoid: `list`, `dict`, `set`, `str`, `int`, `id`, `type`, `input`, `format`, `filter`, `map`, `open`, `file`, `dir`, `help`, `len`, `min`, `max`, `sum`, `any`, `all`

---

## ARG - Unused arguments

| Rule | Description |
|------|-------------|
| ARG001 | unused-function-argument |
| ARG002 | unused-method-argument |
| ARG003 | unused-class-method-argument |
| ARG004 | unused-static-method-argument |
| ARG005 | unused-lambda-argument |

```python
# Wrong
def process(data, unused_config):  # ARG001
    return data

# Correct - prefix with underscore
def process(data, _unused_config):
    return data

# Or remove if not needed
def process(data):
    return data
```

**Note:** ARG is disabled in tests (fixtures often appear unused).

---

## B - flake8-bugbear

Catches likely bugs and design problems.

### Mutable defaults (B006, B008)

```python
# B006 - mutable default argument
def append_to(item, target=[]):  # Wrong - shared list!
    target.append(item)
    return target

def append_to(item, target=None):  # Correct
    if target is None:
        target = []
    target.append(item)
    return target

# B008 - function call in default
def fetch(url, timeout=time.time()):  # Wrong - called once at definition
    ...

def fetch(url, timeout=None):  # Correct
    if timeout is None:
        timeout = time.time()
```

### Loop issues (B007, B020, B023)

```python
# B007 - unused loop variable [fix]
for i in range(10):  # Wrong if i unused
    print("hello")

for _ in range(10):  # Correct
    print("hello")

# B020 - loop variable overrides iterator
for items in items:  # Wrong - shadows
    ...

# B023 - function captures loop variable
funcs = []
for i in range(3):
    funcs.append(lambda: i)  # Wrong - all return 2

funcs = []
for i in range(3):
    funcs.append(lambda i=i: i)  # Correct - capture by value
```

### Exception handling (B904)

```python
# B904 - raise without from inside except
try:
    ...
except KeyError:
    raise ValueError("bad key")  # Wrong - loses traceback

try:
    ...
except KeyError as e:
    raise ValueError("bad key") from e  # Correct
```

### Other B rules

| Rule | Description |
|------|-------------|
| B002 | `++x` doesn't increment (unary + twice) |
| B003 | Assignment to `os.environ` (use indexing) |
| B009 | `getattr(x, "attr")` → `x.attr` [fix] |
| B010 | `setattr(x, "attr", v)` → `x.attr = v` [fix] |
| B011 | `assert False` → `raise AssertionError` [fix] |
| B017 | `pytest.raises(Exception)` too broad |
| B018 | Useless expression (no effect) |
| B905 | `zip()` without `strict=True` [fix] |

---

## C4 - flake8-comprehensions

Simplify comprehensions and generators.

```python
# C400 - unnecessary generator in list() [fix]
list(x for x in items)  # Wrong
[x for x in items]      # Correct

# C401 - unnecessary generator in set() [fix]
set(x for x in items)  # Wrong
{x for x in items}     # Correct

# C402 - unnecessary generator in dict() [fix]
dict((k, v) for k, v in items)  # Wrong
{k: v for k, v in items}        # Correct

# C408 - unnecessary dict/list/tuple call [fix]
dict()   # Wrong
{}       # Correct
list()   # Wrong
[]       # Correct

# C411 - unnecessary list() around list comprehension [fix]
list([x for x in items])  # Wrong
[x for x in items]        # Correct

# C416 - unnecessary comprehension [fix]
[x for x in items]  # Wrong if just copying
list(items)         # Correct

# C417 - unnecessary map [fix]
list(map(str, items))   # Wrong
[str(x) for x in items] # Correct
```

---

## EM - Exception messages

Avoid inline strings in exceptions for better tracebacks.

```python
# EM101 - raw string in exception [fix]
raise ValueError("invalid input")

# EM102 - f-string in exception [fix]
raise ValueError(f"invalid: {value}")

# EM103 - .format() in exception [fix]
raise ValueError("invalid: {}".format(value))

# Correct pattern for all:
msg = f"invalid: {value}"
raise ValueError(msg)
```

---

## ISC - Implicit string concat

Catches accidental string concatenation.

```python
# ISC002 - implicit concat across lines (intentional is OK)
x = (
    "hello "
    "world"  # OK for long strings
)

# ISC003 - explicit string concat could be implicit
"hello " + "world"  # Flagged - can be implicit concat
```

---

## INP - Namespace packages

| Rule | Description |
|------|-------------|
| INP001 | implicit-namespace-package (missing `__init__.py`) |

Every Python package directory needs `__init__.py` (even if empty).

---

## N - pep8-naming

### Classes and functions

```python
# N801 - class names should be PascalCase
class my_class: ...    # Wrong
class MyClass: ...     # Correct

# N802 - function names should be snake_case
def myFunction(): ...  # Wrong
def my_function(): ... # Correct

# N803 - argument names should be snake_case
def func(myArg): ...   # Wrong
def func(my_arg): ...  # Correct
```

### Methods

```python
# N804 - first arg of classmethod should be cls [fix]
@classmethod
def method(self): ...  # Wrong
def method(cls): ...   # Correct

# N805 - first arg of method should be self [fix]
def method(this): ...  # Wrong
def method(self): ...  # Correct
```

### Variables and constants

```python
# N806 - variable in function should be lowercase
def func():
    MyVar = 1  # Wrong
    my_var = 1 # Correct

# Module-level constants should be UPPER_CASE
max_retries = 3  # Wrong
MAX_RETRIES = 3  # Correct
```

### Exceptions (N818)

```python
# N818 - exception name should end in Error
class InvalidInput(Exception): ...   # Wrong
class InvalidInputError(Exception): ... # Correct
```

---

## PERF - Performance

```python
# PERF101 - unnecessary list cast in iteration [fix]
for x in list(items):  # Wrong
for x in items:        # Correct

# PERF102 - incorrect dict iterator [fix]
for k in dict.keys():   # Wrong (if only need keys)
for k in dict:          # Correct

for k, v in dict.items():  # Correct when need both

# PERF203 - try/except in loop (slow)
for item in items:
    try:
        process(item)
    except ValueError:
        pass
# Consider: batch processing or moving try outside

# PERF401 - manual list comprehension [fix]
result = []
for x in items:
    result.append(x * 2)  # Wrong

result = [x * 2 for x in items]  # Correct

# PERF403 - manual dict comprehension [fix]
result = {}
for k, v in items:
    result[k] = v * 2

result = {k: v * 2 for k, v in items}  # Correct
```

---

## PIE - Misc lints

```python
# PIE790 - unnecessary pass/... [fix]
def func():
    pass  # Wrong if there's other code

# PIE794 - duplicate class field [fix]
class C:
    x = 1
    x = 2  # Wrong - duplicate

# PIE796 - non-unique enum values
class Status(Enum):
    A = 1
    B = 1  # Wrong - duplicate value

# PIE800 - unnecessary spread [fix]
{**{"a": 1}}  # Wrong
{"a": 1}      # Correct

# PIE804 - unnecessary dict kwargs [fix]
func(**{"key": value})  # Wrong
func(key=value)         # Correct

# PIE807 - reimplemented container builtin [fix]
lambda: []  # Wrong
list        # Correct

# PIE808 - unnecessary range start [fix]
range(0, 10)  # Wrong
range(10)     # Correct

# PIE810 - multiple startswith/endswith [fix]
x.startswith("a") or x.startswith("b")  # Wrong
x.startswith(("a", "b"))                # Correct
```

---

## PL - Pylint

Large rule set split into: PLC (convention), PLE (error), PLR (refactor), PLW (warning).

### PLC - Convention

```python
# PLC0415 - import outside top level
def func():
    import os  # Wrong (except in .github/scripts/ and tests)

# PLC1802 - len-test [fix]
if len(items) > 0:  # Wrong
if len(items):      # Wrong
if items:           # Correct (use truthiness)

# PLC2801 - unnecessary dunder call [fix]
x.__str__()  # Wrong
str(x)       # Correct
```

### PLE - Errors (critical)

```python
# PLE0101 - return in __init__
class Bad:
    def __init__(self):
        return self  # Wrong

# PLE0302 - unexpected special method signature
class Bad:
    def __len__(self, x):  # Wrong - __len__ takes no args
        return 0

# PLE1142 - await outside async
def sync():
    await coro()  # Wrong

# PLE0643 - potential index error
items = [1, 2]
x = items[5]  # Wrong - IndexError
```

### PLR - Refactor

```python
# PLR0124 - comparison with itself
if x == x:  # Wrong (always True except NaN)

# PLR1701 - repeated isinstance [fix]
isinstance(x, int) or isinstance(x, str)  # Wrong
isinstance(x, (int, str))                 # Correct

# PLR1711 - useless return [fix]
def func():
    ...
    return None  # Wrong - implicit

# PLR1714 - repeated equality [fix]
if x == 1 or x == 2 or x == 3:  # Wrong
if x in {1, 2, 3}:              # Correct

# PLR2004 - magic value (disabled in tests)
if retries > 3:      # Wrong
MAX_RETRIES = 3
if retries > MAX_RETRIES:  # Correct

# PLR5501 - collapsible else-if [fix]
if a:
    pass
else:
    if b:  # Wrong
        pass

if a:
    pass
elif b:  # Correct
    pass

# PLR6104 - non-augmented assignment [fix]
x = x + 1  # Wrong
x += 1     # Correct
```

### PLW - Warnings

```python
# PLW0120 - useless else on loop [fix]
for item in items:
    if found:
        break
else:
    pass  # Wrong if else does nothing

# PLW1510 - subprocess.run without check [fix]
subprocess.run(["cmd"])              # Wrong
subprocess.run(["cmd"], check=True)  # Correct

# PLW1514 - unspecified encoding [fix]
open("file.txt")                      # Wrong
open("file.txt", encoding="utf-8")    # Correct

# PLW2901 - redefined loop name
for i in range(10):
    for i in range(5):  # Wrong - shadows outer i
        pass
```

---

## PT - pytest

### Fixtures

```python
# PT001 - unnecessary parentheses [fix]
@pytest.fixture()     # Wrong
@pytest.fixture       # Correct

# PT003 - extraneous scope [fix]
@pytest.fixture(scope="function")  # Wrong - default
@pytest.fixture                    # Correct

# PT022 - useless yield fixture [fix]
@pytest.fixture
def fix():
    yield value  # Wrong if no teardown

@pytest.fixture
def fix():
    return value  # Correct
```

### Assertions

```python
# PT009 - use pytest assertion [fix]
self.assertEqual(a, b)  # Wrong (unittest style)
assert a == b           # Correct

# PT011 - raises too broad
with pytest.raises(Exception):  # Wrong
    ...
with pytest.raises(ValueError, match="pattern"):  # Correct
    ...

# PT015 - assert always false
assert False  # Wrong - use pytest.fail()
pytest.fail("reason")  # Correct

# PT018 - composite assertion [fix]
assert a and b  # Wrong - unclear which failed
assert a
assert b        # Correct
```

### Marks

```python
# PT023 - incorrect mark parentheses [fix]
@pytest.mark.slow()  # Wrong if no args
@pytest.mark.slow    # Correct
```

---

## PTH - pathlib

Replace `os.path` with `pathlib.Path`.

| Wrong (os.path) | Correct (pathlib) |
|-----------------|-------------------|
| `os.path.join(a, b)` | `Path(a) / b` |
| `os.path.exists(p)` | `Path(p).exists()` |
| `os.path.isdir(p)` | `Path(p).is_dir()` |
| `os.path.isfile(p)` | `Path(p).is_file()` |
| `os.path.basename(p)` | `Path(p).name` |
| `os.path.dirname(p)` | `Path(p).parent` |
| `os.path.splitext(p)` | `Path(p).suffix` / `.stem` |
| `os.getcwd()` | `Path.cwd()` |
| `os.makedirs(p)` | `Path(p).mkdir(parents=True)` |
| `open(p)` | `Path(p).open()` or `Path(p).read_text()` |

```python
# Wrong
import os
path = os.path.join(dir, "file.txt")
if os.path.exists(path):
    with open(path) as f:
        data = f.read()

# Correct
from pathlib import Path
path = Path(dir) / "file.txt"
if path.exists():
    data = path.read_text()
```

---

## RET - Returns

```python
# RET502 - implicit return value [fix]
def func():
    if condition:
        return value
    return  # Wrong - inconsistent

def func():
    if condition:
        return value
    return None  # Correct - explicit

# RET503 - implicit return (UNFIXABLE - can break generators)
def func():
    if condition:
        return value
    # Wrong - missing return/raise for some paths

# RET504 - unnecessary assign [fix]
def func():
    result = compute()
    return result  # Wrong

def func():
    return compute()  # Correct

# RET505-508 - superfluous else after return/raise/continue/break [fix]
def func():
    if condition:
        return x
    else:        # Wrong - else unnecessary
        return y

def func():
    if condition:
        return x
    return y     # Correct
```

---

## RUF - Ruff-specific

### Common rules

```python
# RUF001-003 - ambiguous unicode (Cyrillic о vs Latin o)
name = "Вася"  # OK - intentional Cyrillic
nаme = "x"     # Wrong - Cyrillic 'а' in identifier

# RUF005 - collection concatenation [fix]
[1] + [2] + [3]  # Wrong
[1, 2, 3]        # Correct

# RUF010 - explicit f-string conversion [fix]
f"{x!s}"  # Wrong if x is already str
f"{x}"    # Correct

# RUF013 - implicit Optional [fix]
def func(x: int = None):  # Wrong
def func(x: int | None = None):  # Correct

# RUF015 - unnecessary allocation for first element [fix]
list(x)[0]  # Wrong
next(iter(x))  # Correct

# RUF100 - unused noqa [fix]
x = 1  # noqa: F841  # Wrong if F841 not triggered

# RUF027 - missing f-string syntax [fix]
"{x} + {y}"   # Wrong - probably meant f-string
f"{x} + {y}"  # Correct
```

### Dataclass rules

| Rule | Description |
|------|-------------|
| RUF008 | mutable-dataclass-default |
| RUF009 | function-call-in-dataclass-default |

```python
# Wrong
@dataclass
class Config:
    items: list = []  # RUF008 - mutable default

# Correct
@dataclass
class Config:
    items: list = field(default_factory=list)
```

---

## SLF - Private access

| Rule | Description |
|------|-------------|
| SLF001 | private-member-access |

```python
# Wrong in production
obj._private_attr
obj._private_method()

# Correct
obj.public_attr
obj.public_method()
```

**Note:** SLF001 is disabled in tests.

---

## TC - Type checking

Move type-only imports into `TYPE_CHECKING` block.

```python
# TC001 - first-party import only for types [fix]
# TC002 - third-party import only for types [fix]
# TC003 - stdlib import only for types [fix]

# Wrong - Path only used in type hints
from pathlib import Path

def process(path: Path) -> None:
    print(str(path))

# Correct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

def process(path: "Path") -> None:  # String annotation
    print(str(path))
```

**Exception:** Keep import outside if used at runtime:
```python
from pathlib import Path  # Needed at runtime

def process(path: Path) -> None:
    return Path(path).exists()  # Runtime usage
```

**Note:** TC rules are in `unfixable` - auto-fix disabled because it can break runtime.

---

## Test-specific rules

In `**/tests/**/*.py`, these rules are **disabled**:

| Rule    | Reason                                 |
|---------|----------------------------------------|
| S101    | `assert` is standard in tests          |
| S603    | subprocess calls common in tests       |
| S607    | partial executable paths OK            |
| PLR2004 | magic numbers OK in assertions         |
| ARG     | unused fixture args are normal         |
| SLF001  | testing internals needs private access |
| PLC0415 | late imports for test isolation        |

In `.github/scripts/*.py`:

| Rule    | Reason                              |
|---------|-------------------------------------|
| PLC0415 | late imports for package structure  |
| S603    | subprocess calls are intentional    |
