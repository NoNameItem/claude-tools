# Python CI Workflows Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create GitHub Actions CI workflows for Python packages with lint, format, typecheck, and test jobs.

**Architecture:** Caller workflow (ci.yml) triggers on PR/push, validates commits, detects changed packages via detect_changes.py, then calls reusable workflow (_reusable-python-ci.yml) for each package. Reusable workflow has lint job (single Python version) and test job (matrix of Python versions).

**Tech Stack:** GitHub Actions, uv, ruff, ty, pytest, astral-sh/setup-uv

---

## Task 1: Add changed_files to detect_changes.py

**Files:**
- Modify: `.github/scripts/detect_changes.py`
- Modify: `.github/scripts/tests/test_detect_changes.py`

**Step 1: Write failing test for build_changed_files_map**

```python
# Add to .github/scripts/tests/test_detect_changes.py

class TestBuildChangedFilesMap:
    """Tests for build_changed_files_map function."""

    def test_single_package(self) -> None:
        """Should group files by package."""
        from ..detect_changes import build_changed_files_map

        files = ["packages/statuskit/src/foo.py", "packages/statuskit/tests/test_foo.py"]
        result = build_changed_files_map(files)
        assert result == {"statuskit": files}

    def test_repo_level_files(self) -> None:
        """Should group repo-level files under 'repo' key."""
        from ..detect_changes import build_changed_files_map

        files = ["pyproject.toml", ".github/scripts/validate.py"]
        result = build_changed_files_map(files)
        assert result == {"repo": files}

    def test_mixed_files(self) -> None:
        """Should separate package and repo-level files."""
        from ..detect_changes import build_changed_files_map

        files = [
            "packages/statuskit/src/foo.py",
            "packages/statuskit/README.md",
            "pyproject.toml",
        ]
        result = build_changed_files_map(files)
        assert result == {
            "statuskit": ["packages/statuskit/src/foo.py", "packages/statuskit/README.md"],
            "repo": ["pyproject.toml"],
        }

    def test_multiple_packages(self) -> None:
        """Should group files by their respective packages."""
        from ..detect_changes import build_changed_files_map

        files = [
            "packages/statuskit/src/foo.py",
            "packages/another/src/bar.py",
        ]
        result = build_changed_files_map(files)
        assert result == {
            "statuskit": ["packages/statuskit/src/foo.py"],
            "another": ["packages/another/src/bar.py"],
        }

    def test_empty_list(self) -> None:
        """Should return empty dict for empty input."""
        from ..detect_changes import build_changed_files_map

        result = build_changed_files_map([])
        assert result == {}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py::TestBuildChangedFilesMap -v`
Expected: FAIL with "cannot import name 'build_changed_files_map'"

**Step 3: Implement build_changed_files_map function**

Add to `.github/scripts/detect_changes.py` after imports:

```python
def build_changed_files_map(changed_files: list[str]) -> dict[str, list[str]]:
    """Group changed files by project.

    Returns ALL files without extension filtering.
    Filtering (.py etc.) happens on consumer side (workflow).

    Args:
        changed_files: List of file paths relative to repo root.

    Returns:
        Dict mapping project name to list of files.
        Repo-level files are under "repo" key.
    """
    from .projects import get_project_from_path

    result: dict[str, list[str]] = {}

    for file_path in changed_files:
        project_name = get_project_from_path(file_path)
        key = project_name if project_name else "repo"

        if key not in result:
            result[key] = []
        result[key].append(file_path)

    return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py::TestBuildChangedFilesMap -v`
Expected: PASS

**Step 5: Write failing test for changed_files in DetectionResult**

```python
# Add to TestDetectionResultJson class in test_detect_changes.py

    def test_json_has_changed_files(self, temp_repo: Path) -> None:
        """Should include changed_files in JSON output."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        output = result.to_json()
        data = json.loads(output)
        assert "changed_files" in data
        assert data["changed_files"] == {"statuskit": ["packages/statuskit/src/module.py"]}
```

**Step 6: Run test to verify it fails**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py::TestDetectionResultJson::test_json_has_changed_files -v`
Expected: FAIL with "KeyError: 'changed_files'"

**Step 7: Add changed_files to DetectionResult and detect_changes**

Modify DetectionResult dataclass:

```python
@dataclass
class DetectionResult:
    """Result of change detection."""

    projects: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    has_packages: bool = False
    has_plugins: bool = False
    has_repo_level: bool = False
    tooling_changed: bool = False
    matrix: dict = field(default_factory=lambda: {"include": []})
    all_packages_matrix: dict = field(default_factory=lambda: {"include": []})
    changed_files: dict[str, list[str]] = field(default_factory=dict)  # NEW

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "projects": self.projects,
                "packages": self.packages,
                "plugins": self.plugins,
                "has_packages": self.has_packages,
                "has_plugins": self.has_plugins,
                "has_repo_level": self.has_repo_level,
                "tooling_changed": self.tooling_changed,
                "matrix": self.matrix,
                "all_packages_matrix": self.all_packages_matrix,
                "changed_files": self.changed_files,  # NEW
            }
        )
```

Add at end of detect_changes function, before `return result`:

```python
    result.changed_files = build_changed_files_map(changed_files)

    return result
```

**Step 8: Run all detect_changes tests**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py -v`
Expected: All PASS

**Step 9: Lint Python files**

Run:
```bash
uv run ruff format .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
uv run ruff check --fix .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
```
Expected: Files formatted, no unfixable errors

**Step 10: Commit**

```bash
git add .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
git commit -m "$(cat <<'EOF'
feat(ci): add changed_files map to detect_changes output

Adds build_changed_files_map function that groups changed files by
project name. Used by reusable CI workflow for targeted linting.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create _reusable-python-ci.yml workflow

**Files:**
- Create: `.github/workflows/_reusable-python-ci.yml`

**Step 1: Create the reusable workflow file**

```yaml
# .github/workflows/_reusable-python-ci.yml
name: Python CI (Reusable)

on:
  workflow_call:
    inputs:
      package:
        description: 'Package name (e.g., statuskit)'
        required: true
        type: string
      package-path:
        description: 'Path to package (e.g., packages/statuskit)'
        required: true
        type: string
      python-versions:
        description: 'JSON array of Python versions'
        required: true
        type: string
      changed-files:
        description: 'JSON array of changed files for targeted linting'
        required: false
        type: string
        default: '[]'

jobs:
  lint:
    name: Lint (${{ inputs.package }})
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get minimum Python version
        id: py-version
        run: |
          MIN_PY=$(echo '${{ inputs.python-versions }}' | jq -r '.[0]')
          echo "version=$MIN_PY" >> $GITHUB_OUTPUT

      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          python-version: ${{ steps.py-version.outputs.version }}

      - name: Install dependencies
        run: uv sync
        working-directory: ${{ inputs.package-path }}

      - name: Filter Python files
        id: filter
        run: |
          FILES='${{ inputs.changed-files }}'
          if [ "$FILES" == "[]" ] || [ -z "$FILES" ]; then
            echo "py_files=${{ inputs.package-path }}" >> $GITHUB_OUTPUT
          else
            PY_FILES=$(echo "$FILES" | jq -r '.[] | select(endswith(".py"))' | tr '\n' ' ')
            if [ -z "$PY_FILES" ]; then
              echo "py_files=" >> $GITHUB_OUTPUT
            else
              echo "py_files=$PY_FILES" >> $GITHUB_OUTPUT
            fi
          fi

      - name: Ruff format check
        id: format
        if: steps.filter.outputs.py_files != ''
        continue-on-error: true
        run: uv run ruff format --check ${{ steps.filter.outputs.py_files }}

      - name: Ruff lint
        id: lint
        if: steps.filter.outputs.py_files != ''
        continue-on-error: true
        run: uv run ruff check ${{ steps.filter.outputs.py_files }}

      - name: Type check
        id: typecheck
        continue-on-error: true
        run: uv run ty check
        working-directory: ${{ inputs.package-path }}

      - name: Check results
        run: |
          failed=false
          if [ "${{ steps.format.outcome }}" == "failure" ]; then
            echo "::error::Ruff format check failed"
            failed=true
          fi
          if [ "${{ steps.lint.outcome }}" == "failure" ]; then
            echo "::error::Ruff lint failed"
            failed=true
          fi
          if [ "${{ steps.typecheck.outcome }}" == "failure" ]; then
            echo "::error::Type check failed"
            failed=true
          fi
          if [ "$failed" == "true" ]; then
            exit 1
          fi

  test:
    name: Test (${{ inputs.package }}, py${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ${{ fromJson(inputs.python-versions) }}
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          python-version: ${{ matrix.python }}

      - name: Install dependencies
        run: uv sync
        working-directory: ${{ inputs.package-path }}

      - name: Run tests
        run: uv run pytest --cov --cov-report=xml
        working-directory: ${{ inputs.package-path }}

      - name: Get minimum Python version
        id: min-py
        run: |
          MIN_PY=$(echo '${{ inputs.python-versions }}' | jq -r '.[0]')
          echo "version=$MIN_PY" >> $GITHUB_OUTPUT

      - name: Upload coverage
        if: matrix.python == steps.min-py.outputs.version
        uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ inputs.package }}
          path: ${{ inputs.package-path }}/coverage.xml
```

**Step 2: Lint the workflow**

Run: `actionlint .github/workflows/_reusable-python-ci.yml`
Expected: No errors

**Step 3: Commit**

```bash
git add .github/workflows/_reusable-python-ci.yml
git commit -m "$(cat <<'EOF'
feat(ci): add reusable Python CI workflow

Adds _reusable-python-ci.yml with:
- lint job: ruff format, ruff check, ty check (single Python version)
- test job: pytest with coverage (matrix of Python versions)

Uses continue-on-error + summary step to show all lint errors at once.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create ci.yml caller workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Create the caller workflow file**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    paths:
      - 'packages/**'
      - 'pyproject.toml'
      - 'uv.lock'
  push:
    branches: [master]
    paths:
      - 'packages/**'
      - 'pyproject.toml'
      - 'uv.lock'

jobs:
  validate-pr:
    name: Validate PR
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Validate PR title
        env:
          PR_TITLE: ${{ github.event.pull_request.title }}
          BASE_REF: ${{ github.event.pull_request.base.ref }}
        run: python .github/scripts/validate.py --pr

  validate-push:
    name: Validate commits
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Validate commits
        run: |
          python .github/scripts/validate.py --commits \
            ${{ github.event.before }} \
            ${{ github.sha }}

  detect:
    name: Detect changes
    needs: [validate-pr, validate-push]
    if: |
      always() &&
      (needs.validate-pr.result == 'success' || needs.validate-pr.result == 'skipped') &&
      (needs.validate-push.result == 'success' || needs.validate-push.result == 'skipped')
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.detect.outputs.matrix }}
      all-packages-matrix: ${{ steps.detect.outputs.all_packages_matrix }}
      has-packages: ${{ steps.detect.outputs.has_packages }}
      tooling-changed: ${{ steps.detect.outputs.tooling_changed }}
      changed-files: ${{ steps.detect.outputs.changed_files }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changes
        id: detect
        run: |
          OUTPUT=$(python .github/scripts/detect_changes.py --ref origin/master..HEAD)
          echo "matrix=$(echo "$OUTPUT" | jq -c '.matrix')" >> $GITHUB_OUTPUT
          echo "all_packages_matrix=$(echo "$OUTPUT" | jq -c '.all_packages_matrix')" >> $GITHUB_OUTPUT
          echo "has_packages=$(echo "$OUTPUT" | jq -r '.has_packages')" >> $GITHUB_OUTPUT
          echo "tooling_changed=$(echo "$OUTPUT" | jq -r '.tooling_changed')" >> $GITHUB_OUTPUT
          echo "changed_files=$(echo "$OUTPUT" | jq -c '.changed_files')" >> $GITHUB_OUTPUT

  ci:
    name: CI
    needs: detect
    if: needs.detect.outputs.has-packages == 'true' || needs.detect.outputs.tooling-changed == 'true'
    strategy:
      fail-fast: false
      matrix: ${{ needs.detect.outputs.tooling-changed == 'true' && fromJson(needs.detect.outputs.all-packages-matrix) || fromJson(needs.detect.outputs.matrix) }}
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      package: ${{ matrix.package }}
      package-path: ${{ matrix.path }}
      python-versions: ${{ toJson(fromJson(format('["{0}"]', matrix.python))) }}
      changed-files: ${{ toJson(fromJson(needs.detect.outputs.changed-files)[matrix.package] || fromJson('[]')) }}
```

**Step 2: Lint the workflow**

Run: `actionlint .github/workflows/ci.yml`
Expected: No errors

**Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
feat(ci): add CI caller workflow

Adds ci.yml that:
- Triggers on PR/push to packages/** or tooling files
- Validates PR title or commit messages
- Detects changed packages via detect_changes.py
- Calls _reusable-python-ci.yml for each package
- Uses all-packages matrix when tooling changed

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Fix matrix structure for reusable workflow

The current matrix structure from detect_changes.py creates one entry per (package, python) combination. But the reusable workflow expects python-versions as a JSON array. We need to restructure the matrix.

**Files:**
- Modify: `.github/scripts/detect_changes.py`
- Modify: `.github/scripts/tests/test_detect_changes.py`

**Step 1: Write failing test for new matrix structure**

```python
# Add to TestDetectChanges class in test_detect_changes.py

    def test_matrix_has_python_versions_array(self, temp_repo: Path) -> None:
        """Matrix entry should have python-versions as array."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert len(result.matrix["include"]) == 1
        entry = result.matrix["include"][0]
        assert entry["package"] == "statuskit"
        assert entry["path"] == "packages/statuskit"
        assert entry["python-versions"] == ["3.11", "3.12"]
        assert "python" not in entry  # Old field should not exist
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py::TestDetectChanges::test_matrix_has_python_versions_array -v`
Expected: FAIL

**Step 3: Update matrix generation in detect_changes**

Replace the matrix building section in detect_changes function:

```python
    # Build matrix for changed packages (one entry per package)
    for pkg_name in result.packages:
        pkg_info = all_projects.get(pkg_name)
        if pkg_info and pkg_info.python_versions:
            result.matrix["include"].append(
                {
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python-versions": pkg_info.python_versions,
                }
            )

    # Build all_packages_matrix (one entry per package)
    for pkg_name, pkg_info in sorted(all_projects.items()):
        if pkg_info.kind == "package" and pkg_info.python_versions:
            result.all_packages_matrix["include"].append(
                {
                    "package": pkg_name,
                    "path": pkg_info.path,
                    "python-versions": pkg_info.python_versions,
                }
            )
```

**Step 4: Fix existing tests that check matrix structure**

Update `test_matrix_generation` test:

```python
    def test_matrix_generation(self, temp_repo: Path) -> None:
        """Should generate CI matrix with Python versions."""
        changed_files = ["packages/statuskit/src/module.py"]
        result = detect_changes(changed_files, repo_root=temp_repo)
        assert len(result.matrix["include"]) == 1
        entry = result.matrix["include"][0]
        assert entry["package"] == "statuskit"
        assert entry["path"] == "packages/statuskit"
        assert entry["python-versions"] == ["3.11", "3.12"]
```

**Step 5: Run all detect_changes tests**

Run: `uv run pytest .github/scripts/tests/test_detect_changes.py -v`
Expected: All PASS

**Step 6: Update ci.yml to use new matrix structure**

The ci.yml matrix now iterates over packages (not package+python combinations). Update the workflow call:

```yaml
  ci:
    name: CI (${{ matrix.package }})
    needs: detect
    if: needs.detect.outputs.has-packages == 'true' || needs.detect.outputs.tooling-changed == 'true'
    strategy:
      fail-fast: false
      matrix: ${{ needs.detect.outputs.tooling-changed == 'true' && fromJson(needs.detect.outputs.all-packages-matrix) || fromJson(needs.detect.outputs.matrix) }}
    uses: ./.github/workflows/_reusable-python-ci.yml
    with:
      package: ${{ matrix.package }}
      package-path: ${{ matrix.path }}
      python-versions: ${{ toJson(matrix.python-versions) }}
      changed-files: ${{ toJson(fromJson(needs.detect.outputs.changed-files)[matrix.package] || fromJson('[]')) }}
```

**Step 7: Lint workflows**

Run: `actionlint .github/workflows/ci.yml`
Expected: No errors

**Step 8: Lint Python files**

Run:
```bash
uv run ruff format .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
uv run ruff check --fix .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py
```
Expected: Files formatted, no unfixable errors

**Step 9: Commit**

```bash
git add .github/scripts/detect_changes.py .github/scripts/tests/test_detect_changes.py .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
fix(ci): restructure matrix to one entry per package

Changes matrix structure from (package, python) combinations to
one entry per package with python-versions array. This matches
the reusable workflow input format.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Test locally with act

**Step 1: Verify act is installed**

Run: `command -v act && echo "act installed" || echo "Install with: brew install act"`
Expected: "act installed"

**Step 2: Create .actrc if not exists**

Check: `cat .actrc 2>/dev/null || echo "Not found"`

If not found, create:
```
-P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest
```

**Step 3: Run act simulation for pull_request**

Run: `act pull_request -W .github/workflows/ci.yml --dryrun`
Expected: Shows job graph without errors

**Step 4: Run full simulation (optional, may take time)**

Run: `act pull_request -W .github/workflows/ci.yml -v`
Expected: Jobs run successfully or expected failures (may need GitHub token for some actions)

---

## Task 6: Validate all workflows with actionlint

**Step 1: Run actionlint on all workflows**

Run: `actionlint .github/workflows/*.yml`
Expected: No errors

**Step 2: Fix any issues found**

If actionlint reports errors, fix them in the relevant workflow file.

**Step 3: Commit fixes if any**

```bash
git add .github/workflows/
git commit -m "$(cat <<'EOF'
fix(ci): resolve actionlint warnings

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final verification

**Step 1: Run all tests**

Run: `uv run pytest .github/scripts/tests/ -v`
Expected: All PASS

**Step 2: Verify workflow files exist and are valid YAML**

Run: `ls -la .github/workflows/ci.yml .github/workflows/_reusable-python-ci.yml`
Expected: Both files exist

**Step 3: Check git status**

Run: `git status`
Expected: Clean working directory or expected uncommitted changes
