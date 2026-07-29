# Codebase Audit: Proposed Maintenance Tasks

This audit identifies four small, independently actionable maintenance tasks.
The tasks are ordered by category rather than priority; the connector bug should
be addressed first because it can prevent schema requests from completing.

## 1. Typo: use the correct article before “UPSERT”

**Scope:** `pipeline/bigquery_loader.py`

Change “an UPSERT” to “an upsert” only if the word is pronounced with an initial
vowel sound in the project's style, or, preferably, change it to “a BigQuery
upsert”. The current module docstring reads “an UPSERT”, although “upsert” is
normally pronounced with an initial consonant sound (“up…”), so the article is a
grammatical typo.

**Acceptance criteria:**

- The module description uses “a BigQuery upsert” (or equivalent grammatical
  wording).
- The edit does not claim that the implementation uses `MERGE` unless the loader
  is also changed as described in task 3.

## 2. Bug: remove the recursive/colliding connector schema functions

**Scope:** `connector/Code.js`, `connector/schema.js`

Rename the schema builder in `schema.js` to a private, unambiguous name such as
`buildSchema_`, and have both the public `getSchema(request)` handler and
`getData(request)` call it. At present, both files declare a global function
named `getSchema`, while `Code.js` also implements `getSchema_` by calling
`getSchema()`. Apps Script combines project files into one global namespace, so
the duplicate declaration is ambiguous and can make the helper call the public
handler recursively instead of returning a `Fields` object.

**Acceptance criteria:**

- Exactly one public `getSchema(request)` function remains.
- The schema builder has a distinct name and always returns a `Fields` object.
- `getSchema(request)` returns `{schema: ...}` and `getData(request)` can filter
  the built schema without recursion.

## 3. Documentation discrepancy: describe the loader's real append/deduplicate strategy

**Scope:** `pipeline/bigquery_loader.py`

Update the module and class documentation and the inline load comment to match
the implementation. The documentation currently promises an “UPSERT (MERGE)”
and says matching rows are updated, but the code appends incoming rows and then
runs `CREATE OR REPLACE TABLE` with `ROW_NUMBER()`. No BigQuery `MERGE` statement
is executed, and `ORDER BY (SELECT NULL)` does not guarantee that the newly
appended version wins. Either document those actual semantics and limitations,
or implement a staging-table `MERGE` before retaining the stronger claim.

**Acceptance criteria:**

- Every loader comment and docstring accurately names the strategy actually
  used by the code.
- If update/upsert semantics remain documented, a deterministic implementation
  ensures that incoming rows replace existing rows with the same key.
- The merge-key documentation notes that platform tables lacking all three keys
  are partitioned by only the keys present, matching `_deduplicate`.

## 4. Test improvement: add an executable connector schema regression test

**Scope:** new tests for `connector/Code.js` and `connector/schema.js`

Add a JavaScript test harness (with mocked `DataStudioApp` fields) that loads
both Apps Script files into one shared context, as Apps Script does. Assert that
calling the public schema handler terminates, returns an object containing a
schema array, and exposes required shared fields such as `date`, `platform`, and
`campaign_id`. Also exercise the schema path used by `getData` so a duplicate
global name or accidental recursion fails locally rather than after deployment.

There is currently no test directory or test dependency in the repository, and
`python -m compileall` only checks Python syntax; it cannot detect JavaScript
global-name collisions or validate the connector contract.

**Acceptance criteria:**

- A documented test command runs in CI and locally without Apps Script network
  access.
- The test evaluates both connector files in one shared global context.
- The test fails against the current duplicate/recursive schema implementation
  and passes after task 2 is completed.
- At least the required shared field IDs and the public response shape are
  asserted, rather than relying only on a snapshot.
