# Trajectory

model `deepseek-ai/DeepSeek-V4-Flash-0731` via `tofa`, effort `high`; 77.3 s, 25 steps, 24 tool calls; integrity: **CLEAN**

> _think:_ Let me look at the relevant code for lookup_allowed.

1. `grep`: `{'pattern': 'def lookup_allowed', 'path': 'django/contrib/admin'}`

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

> _think:_ The core of the issue is the loop building relation_parts. When we have a OneToOneField that is a primary key (concrete inheritance marker in Django), the code that checks:

```python
if not prev_field or (
    prev_field.is_relation
    and field not in prev_field.path_infos[-1].target_fields
):
    relation_parts.append(part)
```

The loop traverses `restaurant__place__country`. Let's think:

Start: prev_field=None, model=Waiter.
- part="restaurant", field=Restaurant m2o to Waiter.restaurant. prev_field None -> append "restaurant". field has path_infos. prev_field=Restaurant field, model=Res

3. `grep`: `{'path': 'tests/modeladmin/tests.py', 'pattern': 'lookup_allowed'}`

    Found 6 matches
    
    tests/modeladmin/tests.py
    Line 114:     def test_lookup_allowed_allows_nonexistent_lookup(self):
    Line 116:         A lookup_allowed allows a parameter whose field lookup doesn't exist.
    Line 124:         self.assertTrue(ma.lookup_allowed("name__nonexistent", "test_value"))
    Line 127:     def test_lookup_allowed_onetoone(self):
    Line 150:             ma.lookup_allowed("employee__employeeinfo__description", "test_value"), True
    Line 154:             ma. …

4. `read`: `tests/modeladmin/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/modeladmin/tests.py</path>
    <type>file</type>
    <content>
    100:         self.assertEqual(form._meta.fields, ["name", "bio"])
    101: 
    102:         class InlineBandAdmin(TabularInline):
    103:             model = Concert
    104:             fk_name = "main_band"
    105:             can_delete = False
    106: 
    107:             def get_fieldsets(self, request, obj=None):
    108:                 return [(None, {"fields": ["day", "t …

> _think:_ Now let me understand the current code behavior in detail with a script to reproduce. Let me trace the logic.

The loop for `employee__department__code`:
- prev_field=None, model=EmployeeProfile.
- "employee": EmployeeProfile_.meta.get_field("employee") - this is OneToOneField EmployeeProfile.employee? Actually EmployeeProfile has `employee = OneToOneField`. So field = employee onetoone. prev_NONE -> append "employee". field has path_infos, prev_field=employee, model=Employee.
- "employeeinfo": get_field("employeeinfo") on Employee -> reverse OneToOne EmployeeInfo.employee. prev_field=employee

5. `bash`: `cd /home/presenter/swe/task-c/django && python -c "
import django
django.setup()
from django.contrib import admin
from django.db import models

class Country(models.Model):
    name = models.CharField(max_length=256)
    class Meta:
        app_label='modeladmin2'
class Place(models.Model):
    country = models.ForeignKey(Country, models.CASCADE)
    class Meta:
        app_label='modeladmin2'
cla`

    Traceback (most recent call last):
      File "<string>", line 3, in <module>
      File "/home/presenter/swe/task-c/django/django/__init__.py", line 19, in setup
        configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)
                          ^^^^^^^^^^^^^^^^^^^^^^^
      File "/home/presenter/swe/task-c/django/django/conf/__init__.py", line 84, in __getattr__
        self._setup(name)
      File "/home/presenter/swe/task-c/django/django/conf/__init__.py", line 64, in _setup
      …

6. `bash`: `cd /home/presenter/swe/task-c/django && python -c "
import django
from django.conf import settings
settings.configure(INSTALLED_APPS=['django.contrib.contenttypes','django.contrib.auth'])
django.setup()
from django.contrib import admin, messages
from django.db import models

class Country(models.Model):
    name = models.CharField(max_length=256)
class Place(models.Model):
    country = models.For`

    Traceback (most recent call last):
      File "<string>", line 9, in <module>
      File "/home/presenter/swe/task-c/django/django/db/models/base.py", line 134, in __new__
        raise RuntimeError(
    RuntimeError: Model class __main__.Country doesn't declare an explicit app_label and isn't in an application in INSTALLED_APPS.

> _think:_ Let me just run the actual test in tests/ to see behavior. Instead, let me reproduce with the test harness. Or add app_label. Let me use the app label trick within settings.configure with INSTALLED_APPS including the app. Simpler: run via the test runner by invoking the test from the issue. Let me just create a quick test addition? No, let me reproduce by using the existing test infrastructure. Better to just run the exact failing test.

Let me write a temp test file. Actually simpler - let me reproduce using django's test runner with a temporary settings including an app. Let me just use the 

7. `bash`: `cd /home/presenter/swe/task-c/django && mkdir -p /tmp/repro && cp -r tests/admin_ordering /tmp/ 2>/dev/null; cat > /tmp/repro.py <<'EOF'
import django
from django.conf import settings
import os
os.environ['DJANGO_SETTINGS_MODULE']='test_sqlite'
EOF
echo done`

    done

> _think:_ Let me just run the failing test via the test runner by temporarily adding it. Actually, let me reproduce by running a minimal test under runtests. The cleanest: temporarily append the failing test into tests/modeladmin/tests.py, run it, then remove after. But I'm going to add it as a regression test anyway. Let me first confirm the failure by running the exact test before making changes.

Let me add the regression test and run it to confirm failure.

**assistant:** Let me confirm the failure by adding the regression test and running it.

8. `read`: `tests/modeladmin/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/modeladmin/tests.py</path>
    <type>file</type>
    <content>
    1: from datetime import date
    2: 
    3: from django import forms
    4: from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
    5: from django.contrib.admin.options import (
    6:     HORIZONTAL,
    7:     VERTICAL,
    8:     ModelAdmin,
    9:     TabularInline,
    10:     get_content_type_for_model,
    11: )
    12: from django.contrib.admin.sites i …

9. `edit`: `tests/modeladmin/tests.py`

    The file /home/presenter/swe/task-c/django/tests/modeladmin/tests.py has been updated successfully.

> _think:_ Oops, I put the test in the wrong place - it needs to be inside the class, but I placed it at module level (before `def test_field_arguments` which is a method). Let me check the context. Actually `def test_field_arguments(self):` is a method of a class. My inserted code starts with `@isolate_apps(...)` at the same indentation as the method - it's inside whatever class contains test_field_arguments. Good, but the `@isolate_apps` decorator is at 4-space indent matching the method. Should be fine since the method is in a class. Let me verify the surrounding class.

10. `read`: `tests/modeladmin/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/modeladmin/tests.py</path>
    <type>file</type>
    <content>
    168:         class Waiter(models.Model):
    169:             restaurant = models.ForeignKey(Restaurant, models.CASCADE)
    170: 
    171:         class WaiterAdmin(ModelAdmin):
    172:             list_filter = [
    173:                 "restaurant__place__country",
    174:             ]
    175: 
    176:         ma = WaiterAdmin(Waiter, self.site)
    177:         self.assertIs …

11. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin.tests.AdminMethodTests.test_lookup_allowed_foreign_primary 2>&1 | tail -30`

    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 1 test(s).
    System check identified no issues (0 silenced).
    E
    ======================================================================
    ERROR: AdminMethodTests (unittest.loader._FailedTest.AdminMethodTests)
    ----------------------------------------------------------------------
    AttributeError: module 'modeladmin.tests' has no attribute 'AdminMethodTests'
    
    -------------------------- …

12. `grep`: `{'path': 'tests/modeladmin/tests.py', 'pattern': '^class .*\\(ModelAdminTestCase\\)|^class .*='}`

    No matches found

13. `grep`: `{'path': 'tests/modeladmin/tests.py', 'pattern': '^class'}`

    Found 4 matches
    
    tests/modeladmin/tests.py
    Line 28: class MockRequest:
    Line 32: class MockSuperUser:
    Line 41: class ModelAdminTests(TestCase):
    Line 832: class ModelAdminPermissionTests(SimpleTestCase):

14. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin.tests.ModelAdminTests.test_lookup_allowed_foreign_primary 2>&1 | tail -30`

    Creating test database for alias 'default'...
    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 1 test(s).
    System check identified no issues (0 silenced).
    F
    ======================================================================
    FAIL: test_lookup_allowed_foreign_primary (modeladmin.tests.ModelAdminTests.test_lookup_allowed_foreign_primary)
    ----------------------------------------------------------------------
    Traceback (most recen …

> _think:_ So it returns False in current version (not raising, but allowed=False which then causes the Filter to reject). Actually the final lookup_allowed returns `not {...}.isdisjoint(valid_lookups)`. relation_parts=["restaurant"], so it checks `restaurant` and `restaurant+part`. part is the last part (`country`). relation_parts + [part] = ["restaurant","country"]. join -> "restaurant__country". valid_lookups contains "restaurant__place__country". Neither matches -> returns False. So DisallowedModelAdminLookup raised by caller. Right.

So relation_parts=["restaurant"] because "place" and "country" got

**assistant:** The bug reproduces. Now I understand the root cause.

In the loop that builds `relation_parts`, Django drops a lookup part whenever it equals a target field of the previous relation — this is meant to collapse `employee__department__id` to `employee__department` (the id is just the leaf value). But this drop also fires for **relational** target fields. When a OneToOneField is used as a primary key, the target field of `restaurant` *is* `place` (a relation), so `place__country` gets dropped and the path is wrongly collapsed to `restaurant`, which no longer matches `restaurant__place__country` in `list_filter`.

The fix: only drop the trailing part when it is a non-relational leaf field (like a plain `id`), and keep genuine relational paths.

15. `edit`: `django/contrib/admin/options.py`

    The file /home/presenter/swe/task-c/django/django/contrib/admin/options.py has been updated successfully.

16. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin.tests.ModelAdminTests.test_lookup_allowed_foreign_primary modeladmin.tests.ModelAdminTests.test_lookup_allowed_onetoone modeladmin.tests.ModelAdminTests.test_lookup_allowed_allows_nonexistent_lookup 2>&1 | tail -12`

    Creating test database for alias 'default'...
    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 3 test(s).
    System check identified no issues (0 silenced).
    ...
    ----------------------------------------------------------------------
    Ran 3 tests in 0.005s
    
    OK
    Destroying test database for alias 'default'...

**assistant:** Now let me run the broader modeladmin test suite to make sure nothing else regressed, plus the filter tests that exercise lookup logic.

17. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 admin_filters modeladmin 2>&1 | tail -15`

    Creating test database for alias 'default'...
    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 218 test(s).
    System check identified no issues (0 silenced).
    ..........................................................................................................................................................................................................................
    --------------------------------------------------------------------- …

**assistant:** All 218 tests pass. Let me review the final change.

18. `read`: `django/contrib/admin/options.py`

    <path>/home/presenter/swe/task-c/django/django/contrib/admin/options.py</path>
    <type>file</type>
    <content>
    464:             # It is allowed to filter on values that would be found from local
    465:             # model anyways. For example, if you filter on employee__department__id,
    466:             # then the id value would be found already from employee__department_id.
    467:             if not prev_field or (
    468:                 prev_field.is_relation
    469:          …

> _think:_ The line is a bit long (>88 chars). Let me check line length. Line 469 is quite long. Let me reformat.

**assistant:** Let me wrap the long line to match Django style (max 88 chars).

19. `edit`: `django/contrib/admin/options.py`

    The file /home/presenter/swe/task-c/django/django/contrib/admin/options.py has been updated successfully.

20. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin.tests.ModelAdminTests 2>&1 | tail -8`

    Found 31 test(s).
    System check identified no issues (0 silenced).
    ...............................
    ----------------------------------------------------------------------
    Ran 31 tests in 0.066s
    
    OK
    Destroying test database for alias 'default'...

> _think:_ All pass. Let me review the final diff.

21. `bash`: `cd /home/presenter/swe/task-c/django && git diff`

    diff --git a/django/contrib/admin/options.py b/django/contrib/admin/options.py
    index 5240b07..fd97d2d 100644
    --- a/django/contrib/admin/options.py
    +++ b/django/contrib/admin/options.py
    @@ -466,7 +466,10 @@ class BaseModelAdmin(metaclass=forms.MediaDefiningClass):
                 # then the id value would be found already from employee__department_id.
                 if not prev_field or (
                     prev_field.is_relation
    -                and field not in prev_fie …

> _think:_ The test file has a long line at the assertIs. Let me check line length. `self.assertIs(ma.lookup_allowed("restaurant__place__country", "test_value"), True)` - let me count roughly. It's about 87 chars. Let me check with the style. Actually let me format it to be safe.

22. `bash`: `cd /home/presenter/swe/task-c/django && awk 'length>88{print FILENAME": "FNR" len="length": "$0}' tests/modeladmin/tests.py django/contrib/admin/options.py | head`

    tests/modeladmin/tests.py: 177 len=90:         self.assertIs(ma.lookup_allowed("restaurant__place__country", "test_value"), True)
    django/contrib/admin/options.py: 332 len=94:                 "Hold down “Control”, or “Command” on a Mac, to select more than one."
    django/contrib/admin/options.py: 1407 len=89:                     "The {name} “{obj}” was added successfully. You may add another "
    django/contrib/admin/options.py: 1484 len=91:                     "The {name} “{obj}” was adde …

**assistant:** The other long lines are pre-existing (in string literals). Let me fix only my new test line.

23. `edit`: `tests/modeladmin/tests.py`

    The file /home/presenter/swe/task-c/django/tests/modeladmin/tests.py has been updated successfully.

24. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin.tests.ModelAdminTests.test_lookup_allowed_foreign_primary 2>&1 | tail -6`

    .
    ----------------------------------------------------------------------
    Ran 1 test in 0.003s
    
    OK
    Destroying test database for alias 'default'...

**assistant:** Done. Here's a summary of the change.

## Root cause

In `ModelAdmin.lookup_allowed()` (`django/contrib/admin/options.py`), the loop that builds `relation_parts` drops a lookup part whenever it matches one of the target fields of the previous relation. That logic exists to collapse harmless leaf lookups — e.g. `employee__department__id` collapses to `employee__department`, since the `id` value is already reachable via `employee__department_id`.

The bug is that this drop was applied to **any** target field, including **relational** ones. When a `OneToOneField` is used as a model's primary key, the target field of a relation to that model is itself a relation. In the example:
- `restaurant` (FK → `Restaurant`) has target field `place` (Restaurant's PK, a `OneToOneField`),
- so the loop dropped `place` … and then `country` (which is `Place`'s PK), 
- collapsing `restaurant__place__country` to just `restaurant`, which doesn't match `restaurant__place__country` in `list_filter`, so the lookup returned `False` (→ `DisallowedModelAdminLookup` by the caller).

## Fix

Only drop the trailing part when the target field is a non-relational leaf value (like a plain `id`); genuine relational path segments must always be kept:

```python
if not prev_field or (
    prev_field.is_relation
    and (
        field.is_relation
        or field not in prev_field.path_infos[-1].target_fields
    )
):
    relation_parts.append(part)
```

This preserves the existing `__id`-style collapsing while no longer mistaking a FK-as-PK for concrete inheritance.

## Test

Added `test_lookup_allowed_foreign_primary` to `tests/modeladmin/tests.py` reproducing the issue scenario, which failed before the fix and now passes. The full `modeladmin` and `admin_filters` suites (218 tests) pass.

