# Trajectory

model `deepseek-ai/DeepSeek-V4-Flash-0731` via `tofa`, effort `high`; 127.2 s, 10 steps, 9 tool calls; integrity: **CLEAN**

> _think:_ Let me start by exploring the relevant code to understand the issue.

The issue is in `ModelAdmin.lookup_allowed()` in django/contrib/admin/options.py. Let me look at the code.

1. `grep`: `{'pattern': 'lookup_allowed', 'include': '*.py', 'path': 'django/contrib/admin/options.py'}`

    Found 1 match
    
    django/contrib/admin/options.py
    Line 439:     def lookup_allowed(self, lookup, value):

2. `read`: `django/contrib/admin/options.py`

    <path>/home/presenter/swe/task-c/django/django/contrib/admin/options.py</path>
    <type>file</type>
    <content>
    439:     def lookup_allowed(self, lookup, value):
    440:         from django.contrib.admin.filters import SimpleListFilter
    441: 
    442:         model = self.model
    443:         # Check FKey lookups that are allowed, so that popups produced by
    444:         # ForeignKeyRawIdWidget, on the basis of ForeignKey.limit_choices_to,
    445:         # are allowed to work.
 …

> _think:_ Now let me understand the issue. The problem is at lines 467-470:

```python
if not prev_field or (
    prev_field.is_relation
    and field not in prev_field.path_infos[-1].target_fields
):
    relation_parts.append(part)
```

Let me trace through the example:

Model chain: Waiter -> restaurant (FK to Restaurant) -> place (OneToOne primary_key) -> country (FK to Country).

list_filter = ['restaurant__place__country']

lookup = 'restaurant__place__country'

Iteration over parts ['restaurant', 'place', 'country']:
- part='restaurant', field = Waiter.restaurant field (FK to Restaurant). prev_fie

3. `bash`: `cd /home/presenter/swe/task-c/django && git log --oneline -5 && git status`

    04f0b17 Import source snapshot
    On branch main
    nothing to commit, working tree clean

> _think:_ No upstream history useful. Let me look at the existing test file to understand the context and check related tests around lookup_allowed.

4. `grep`: `{'pattern': 'lookup_allowed', 'path': 'tests/modeladmin/tests.py'}`

    Found 6 matches
    
    tests/modeladmin/tests.py
    Line 114:     def test_lookup_allowed_allows_nonexistent_lookup(self):
    Line 116:         A lookup_allowed allows a parameter whose field lookup doesn't exist.
    Line 124:         self.assertTrue(ma.lookup_allowed("name__nonexistent", "test_value"))
    Line 127:     def test_lookup_allowed_onetoone(self):
    Line 150:             ma.lookup_allowed("employee__employeeinfo__description", "test_value"), True
    Line 154:             ma. …

5. `read`: `tests/modeladmin/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/modeladmin/tests.py</path>
    <type>file</type>
    <content>
    110:         ma = InlineBandAdmin(Band, self.site)
    111:         form = ma.get_formset(None).form
    112:         self.assertEqual(form._meta.fields, ["day", "transport"])
    113: 
    114:     def test_lookup_allowed_allows_nonexistent_lookup(self):
    115:         """
    116:         A lookup_allowed allows a parameter whose field lookup doesn't exist.
    117:         (#2112 …

> _think:_ This is the existing `test_lookup_allowed_onetoone` test which was the original fix for this related class of bugs. Now the new failing scenario adds the FK-as-PK aspect.

Let me implement the fix. The change at line 467-470:

```python
if not prev_field or (
    prev_field.is_relation
    and field not in prev_field.path_infos[-1].target_fields
):
    relation_parts.append(part)
```

The fix should handle the case where `field` is itself a relation. Since if field is a relation pointing to another model, further traversal goes to that model, so it's not the "value found from local model".

Wa

**assistant:** I can see the bug. Let me trace through the failing test. In `lookup_allowed`, the condition at lines 467-470 skips appending a part when that part's field is already the target field (e.g. the pk) of the previous relation — the idea being that `restaurant__place__country`'s value would already be reachable. But when the target field is *itself* a relation (a OneToOne used as primary key), skipping it loses a genuine relational traversal into another model.

Let me apply the fix:

6. `edit`: `django/contrib/admin/options.py`

    The file /home/presenter/swe/task-c/django/django/contrib/admin/options.py has been updated successfully.

**assistant:** Now let me add a regression test matching the issue description:

7. `edit`: `tests/modeladmin/tests.py`

    The file /home/presenter/swe/task-c/django/tests/modeladmin/tests.py has been updated successfully.

8. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin 2>&1 | tail -20`

    Creating test database for alias 'default'...
    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 163 test(s).
    System check identified no issues (0 silenced).
    ...................................................................................................................................................................
    ----------------------------------------------------------------------
    Ran 163 tests in 0.112s
    
    OK
    Destroyin …

**assistant:** All 163 tests pass, including the new regression test. Let me verify the fix once more:

9. `read`: `django/contrib/admin/options.py`

    <path>/home/presenter/swe/task-c/django/django/contrib/admin/options.py</path>
    <type>file</type>
    <content>
    464:             # It is allowed to filter on values that would be found from local
    465:             # model anyways. For example, if you filter on employee__department__id,
    466:             # then the id value would be found already from employee__department_id.
    467:             if not prev_field or (
    468:                 prev_field.is_relation
    469:          …

**assistant:** ## Root cause

In `ModelAdmin.lookup_allowed()` (`django/contrib/admin/options.py`), the loop that decides which parts of a lookup form a real relational path has a "redundancy" shortcut. The comment explains it: a filter like `employee__department__id` is redundant since the value is already reachable as `employee__department_id`. So when the current `field` is already one of the previous relation's `target_fields` (i.e. its foreign/primary key), that part is **skipped** from `relation_parts`.

The problem: when that target field is *itself a relation* — here `Restaurant.place` is a `OneToOneField` used as the primary key — the code wrongly treats `restaurant__place__country` as equivalent to filtering `restaurant__country` directly (which doesn't even exist). Because `place` is `Restaurant`'s pk, it lands in `prev_field.path_infos[-1].target_fields`, so `place` was dropped from `relation_parts`, leaving just `restaurant`, which isn't in `list_filter` → `DisallowedModelAdminLookup`.

## The change

In `django/contrib/admin/options.py`, the skip condition now also requires that the field not be a relation:

```python
if not prev_field or (
    prev_field.is_relation
    and (field.is_relation or field not in prev_field.path_infos[-1].target_fields)
):
    relation_parts.append(part)
```

If `field` is itself a relation, it is not just a redundant plain key value — traversing it leads into a *different* model, so it must be kept in `relation_parts`. Plain pk/id target fields (non-relation) still short-circuit exactly as before, preserving the existing redundancy optimization (verified by `test_lookup_allowed_onetoone`).

## Regression test

Added `test_lookup_allowed_foreign_primary` in `tests/modeladmin/tests.py`, matching the issue's reproduction — a chain `Waiter → Restaurant (FK) → Place (OneToOne pk) → Country (FK)`. All 163 modeladmin tests pass.

