# Trajectory

model `deepseek-ai/DeepSeek-V4-Flash-0731` via `tofa`, effort `high`; 249.6 s, 21 steps, 24 tool calls; integrity: **CLEAN**

> _think:_ Let me start by understanding the issue. Let me look at the relevant code.

The issue is that `ModelAdmin.lookup_allowed()` incorrectly raises `DisallowedModelAdminLookup` when a foreign key is used as a primary key. The code that checks lookups probably thinks having a FK as primary key is the same as concrete inheritance.

Let me explore the code.

1. `bash`: `cd /home/presenter/swe/task-c/django && git log --oneline -3 && git status`

    04f0b17 Import source snapshot
    On branch main
    nothing to commit, working tree clean

2. `grep`: `{'pattern': 'def lookup_allowed', 'path': 'django/contrib/admin'}`

    Found 1 match
    
    django/contrib/admin/options.py
    Line 439:     def lookup_allowed(self, lookup, value):

3. `read`: `django/contrib/admin/options.py`

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

> _think:_ Now let me understand the logic. The issue is at line 467-470:

```python
if not prev_field or (
    prev_field.is_relation
    and field not in prev_field.path_infos[-1].target_fields
):
    relation_parts.append(part)
```

For `restaurant__place__country`:
- part = 'restaurant': field = Restaurant.restaurant FK. prev_field None, so not prev_field → True, append 'restaurant'. prev_field = restaurant field. model = Restaurant.
- part = 'place': field = Place of Restaurant. Actually getting field 'place' from Restaurant — since Restaurant has OneToOneField place as pk, and place's reverse acces

4. `grep`: `{'path': 'tests/admin_views/test_adminsite.py', 'pattern': 'lookup_allowed'}`

    No matches found

5. `grep`: `{'path': 'tests/modeladmin', 'pattern': 'lookup_allowed'}`

    Found 6 matches
    
    tests/modeladmin/tests.py
    Line 114:     def test_lookup_allowed_allows_nonexistent_lookup(self):
    Line 116:         A lookup_allowed allows a parameter whose field lookup doesn't exist.
    Line 124:         self.assertTrue(ma.lookup_allowed("name__nonexistent", "test_value"))
    Line 127:     def test_lookup_allowed_onetoone(self):
    Line 150:             ma.lookup_allowed("employee__employeeinfo__description", "test_value"), True
    Line 154:             ma. …

6. `read`: `/home/presenter/swe/task-c/django/tests/modeladmin/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/modeladmin/tests.py</path>
    <type>file</type>
    <content>
    95:             def get_fieldsets(self, request, obj=None):
    96:                 return [(None, {"fields": ["name", "bio"]})]
    97: 
    98:         ma = BandAdmin(Band, self.site)
    99:         form = ma.get_form(None)
    100:         self.assertEqual(form._meta.fields, ["name", "bio"])
    101: 
    102:         class InlineBandAdmin(TabularInline):
    103:             mode …

> _think:_ Now let me understand the bug trace precisely. The lookup_allowed on Waiter model with 'restaurant__place__country'.

Trace:
- part='restaurant': field=Waiter.restaurant (FK to Restaurant). prev_field=None → append 'restaurant'. prev_field=restaurant field. model=Restaurant.
- part='place': field=Restaurant._meta.get_field('place') = OneToOneField to Place, primary_key=True. Check condition: `prev_field.is_relation` (True) and `field not in prev_field.path_infos[-1].target_fields`.

restaurant_field.path_infos[-1] is the path info to Restaurant. Its target_fields = Restaurant's primary key fie

7. `bash`: `cd /home/presenter/swe/task-c/django && cat django/__init__.py && git log -1 --format='%H %ci'`

    from django.utils.version import get_version
    
    VERSION = (5, 0, 0, "alpha", 0)
    
    __version__ = get_version(VERSION)
    
    
    def setup(set_prefix=True):
        """
        Configure the settings (this happens as a side effect of accessing the
        first setting), configure logging and populate the app registry.
        Set the thread-local urlresolvers script prefix if `set_prefix` is True.
        """
        from django.apps import apps
        from django.conf import se …

8. `read`: `/home/presenter/swe/task-c/django/tests/modeladmin/tests.py`

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

> _think:_ This is Django 5.0 alpha (circa 2023). So the current source here uses the `path_infos` based logic. The issue described is real in this code, and the project intends me to fix this regression.

Wait, but this bug was reported/fixed in Django ~1.9. Yet this snapshot is based on 5.0 source with bug present. Interesting — the task reverted a fix to reproduce the regression, or this represents a state where the bug exists.

Either way, my job: fix `lookup_allowed` minimally so the regression test passes. Let me apply my fix.

Let me re-examine my proposed fix once more against this 5.0 code. The 

**assistant:** Now I understand the bug. Let me trace through `lookup_allowed('restaurant__place__country')`:

- `part='restaurant'` → appended to `relation_parts`.
- `part='place'` → the field `Restaurant.place` (a OneToOne to `Place`) *is* in `restaurant` FK's `target_fields`, because `place` is `Restaurant`'s primary key. So the condition `field not in prev_field.path_infos[-1].target_fields` is False and **`place` is dropped** from `relation_parts`.
- `part='country'` → appended, giving `relation_parts = ['restaurant', 'country']`.

The valid lookup `restaurant__place__country` never matches, so `DisallowedModelAdminLookup` is raised.

The skip is intended only for *redundant terminal* targets (e.g. `employee__department__id`, where `id` is the plain PK that the FK already reaches). A relational field in `target_fields` (a OneToOne PK that continues traversal) is *not* redundant and must be kept. Let me apply the fix:

9. `edit`: `/home/presenter/swe/task-c/django/django/contrib/admin/options.py`

    The file /home/presenter/swe/task-c/django/django/contrib/admin/options.py has been updated successfully.

**assistant:** Now let me add a regression test:

10. `edit`: `/home/presenter/swe/task-c/django/tests/modeladmin/tests.py`

    The file /home/presenter/swe/task-c/django/tests/modeladmin/tests.py has been updated successfully.

11. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin 2>&1 | tail -20`

    Creating test database for alias 'default'...
    Testing against Django installed in '/home/presenter/swe/task-c/django/django'
    Found 163 test(s).
    System check identified no issues (0 silenced).
    ...................................................................................................................................................................
    ----------------------------------------------------------------------
    Ran 163 tests in 0.134s
    
    OK
    Destroyin …

> _think:_ All tests pass. Let me also run the admin_views/filters tests to be safe.

**assistant:** All 163 modeladmin tests pass. Let me run the broader admin-related test suites to check nothing else regressed:

12. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 admin_views admin_filters 2>&1 | tail -15`

    ...........................................................................................................................................................................................F........................................................................................................................................................................................................................................................................................sss.ssssssssssssssssssssssssssss …

> _think:_ A test failure. `test_disallowed_filtering` in admin_views/tests.py. This test expects that a disallowed lookup produces a 400. Let me inspect it.

13. `read`: `/home/presenter/swe/task-c/django/tests/admin_views/tests.py`

    <path>/home/presenter/swe/task-c/django/tests/admin_views/tests.py</path>
    <type>file</type>
    <content>
    1075:         # need to allow them in list_filter or date_hierarchy.
    1076:         response = self.client.get(
    1077:             "%s?age__gt=30" % reverse("admin:admin_views_person_changelist")
    1078:         )
    1079:         self.assertEqual(response.status_code, 200)
    1080: 
    1081:         e1 = Employee.objects.create(
    1082:             name="Anonymous", gen …

> _think:_ This is the concrete-inheritance case! `employee__person_ptr__exact` where `person_ptr` is a OneToOne that is the PK of Employee (concrete inheritance from Person). Here the pk is a FK (OneToOne to Person) used for concrete inheritance.

Wait — this is exactly the case where the OneToOne pk IS the concrete inheritance parent. Let me trace `employee__person_ptr__exact` on WorkHour model.

WorkHour has FK employee to Employee. Employee inherits from Person (concrete inheritance), so Employee.person_ptr is OneToOne to Person, pk.

- part='employee': FK to Employee, append. relation_parts=['employ

14. `grep`: `{'path': '/home/presenter/swe/task-c/django/tests/admin_views', 'pattern': 'class WorkHourAdmin|list_filter'}`

    Found 29 matches
    
    tests/admin_views/tests.py
    Line 1063:         # Filters are allowed if explicitly included in list_filter
    Line 1075:         # need to allow them in list_filter or date_hierarchy.
    Line 7800:             if "_changelist_filters" in parsed_qs:
    Line 7801:                 changelist_filters = parsed_qs["_changelist_filters"]
    Line 7802:                 parsed_filters = dict(parse_qsl(changelist_filters))
    Line 7803:                 parsed_qs["_changeli …

15. `read`: `/home/presenter/swe/task-c/django/tests/admin_views/admin.py`

    <path>/home/presenter/swe/task-c/django/tests/admin_views/admin.py</path>
    <type>file</type>
    <content>
    679: class WorkHourAdmin(admin.ModelAdmin):
    680:     list_display = ("datum", "employee")
    681:     list_filter = ("employee",)
    682:     show_facets = admin.ShowFacets.ALWAYS
    683: 
    684: 
    685: class FoodDeliveryAdmin(admin.ModelAdmin):
    686:     list_display = ("reference", "driver", "restaurant")
    687:     list_editable = ("driver", "restaurant")
    688: …

> _think:_ So WorkHourAdmin list_filter = ("employee",). The URL is `employee__person_ptr__exact=<pk>`. 

Trace `employee__person_ptr__exact` on WorkHour:
- part='employee': append. prev=employee FK to Employee. model=Employee.
- part='person_ptr': Employee.person_ptr, OneToOne to Person, is relational, IS the pk. 
  - ORIGINAL: `field not in target_fields`? person_ptr IS in employee.target_fields (Employee.pk). So False → skip. relation_parts=['employee'].
  - MY FIX: field.is_relation True → append. relation_parts=['employee','person_ptr'].
- part='exact': get_field('exact') → FieldDoesNotExist → break

**assistant:** The broader regression is revealing: my simple fix broke the *concrete inheritance* case (`employee__person_ptr__exact`) where that OneToOne-PK *is* the parent link and should be dropped as redundant. The key difference from the bug's `restaurant__place` is that the PK-as-one-to-one is a genuinely related (non-parent) object in the bug, but a `parent_link` in the inheritance case. Let me confirm `parent_link` distinguishes them:

16. `bash`: `cd /home/presenter/swe/task-c/django && python -c "
import django; 
from django.conf import settings;
settings.configure(INSTALLED_APPS=['django.contrib.contenttypes','django.contrib.auth'], DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}})
django.setup()
from django.db import models
class Country(models.Model):
    name=models.CharField(max_length=256)
class Place(m`

    [stderr]
    Traceback (most recent call last):
      File "<string>", line 7, in <module>
      File "/home/presenter/swe/task-c/django/django/db/models/base.py", line 134, in __new__
        raise RuntimeError(
    RuntimeError: Model class __main__.Country doesn't declare an explicit app_label and isn't in an application in INSTALLED_APPS.
    [exit code: 1]

17. `grep`: `{'path': '/home/presenter/swe/task-c/django/tests/admin_views/models.py', 'pattern': 'class Person|class Employee|class WorkHour'}`

    Found 4 matches
    
    tests/admin_views/models.py
    Line 254: class Person(models.Model):
    Line 268: class Persona(models.Model):
    Line 656: class Employee(Person):
    Line 663: class WorkHour(models.Model):

18. `bash`: `cd /home/presenter/swe/task-c/django && python -c "
import django
from django.conf import settings
settings.configure(INSTALLED_APPS=['django.contrib.contenttypes','django.contrib.auth'], DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}, DEFAULT_AUTO_FIELD='django.db.models.AutoField')
django.setup()
from django.db import models
class MetaApp: app_label='t'
class Cou`

    place parent_link: None is_relation True
    person_ptr parent_link: None is_relation True

> _think:_ Hmm, `parent_link` is None/not set in this way. Both are None. Wait, getattr returned None meaning attribute exists with value None or doesn't exist. Let me check differently — maybe parent_link is a property or set only for actual inheritance detection. Let me check the actual person_ptr field object. Actually both returned None. So `parent_link` is not the right discriminator here.

Hmm. Let me reconsider. Administrators... maybe parent_link is True but stored differently. Let me check `Employee._meta.get_field('person_ptr')` attributes fully. Actually let me check `_meta.pk` and whether per

19. `bash`: `cd /home/presenter/swe/task-c/django && python -c "
import django
from django.conf import settings
settings.configure(INSTALLED_APPS=['django.contrib.contenttypes','django.contrib.auth'], DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}, DEFAULT_AUTO_FIELD='django.db.models.AutoField')
django.setup()
from django.db import models
class MetaApp: app_label='t'
class Cou`

    place attrs: pk True parent_link N/A remote_field.model <class '__main__.Place'>
    person_ptr attrs: pk True parent_link N/A remote_field.model <class '__main__.Person'>
    Employee parent list: [<class '__main__.Person'>]
    Restaurant parent list: []
    person_ptr.related Model: <class '__main__.Person'> its pk t.Person.id id
    place.related Model: <class '__main__.Place'> its pk id

> _think:_ `parent_link` attr is N/A (doesn't exist on the field). Interesting. So parent_link isn't directly available on the field in Django 5.

The distinguishing feature: `Employee._meta.get_parent_list()` contains Person (concrete parent), so person_ptr is a real parent. Restaurant's parent list is empty.

How to check per-field whether it's a concrete-inheritance parent link? The field's related model being in `model._meta.get_parent_list()`? Model here (the model we navigate to) is Restaurant/Employee. We have `prev_field` whose related model is Restaurant (Employee). And `field` = place/person_pt

**assistant:** `parent_link` isn't populated on the field. The real signal is concrete inheritance: `Employee` **is a subclass** of `Person`, but `Restaurant` is **not** a subclass of `Place`. So a relational target-field should only be dropped when the FK's target model is a subclass of the traversed-to model (a concrete-parent link) — not when it's just a foreign key used as a PK. Let me refine the fix:

20. `read`: `/home/presenter/swe/task-c/django/django/contrib/admin/options.py`

    <path>/home/presenter/swe/task-c/django/django/contrib/admin/options.py</path>
    <type>file</type>
    <content>
    462:                 # later.
    463:                 break
    464:             # It is allowed to filter on values that would be found from local
    465:             # model anyways. For example, if you filter on employee__department__id,
    466:             # then the id value would be found already from employee__department_id.
    467:             if not prev_field or (
 …

21. `edit`: `/home/presenter/swe/task-c/django/django/contrib/admin/options.py`

    The file /home/presenter/swe/task-c/django/django/contrib/admin/options.py has been updated successfully.

22. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 modeladmin admin_filters admin_views 2>&1 | tail -8`

    System check identified no issues (1 silenced).
    ................................................................................................................................................................................................................................................................................................................................................................................................................................................................ …

> _think:_ All pass. Let me also run a broader set of admin tests to be safe (admin_registration, admin_default_site, admin_checks, etc.). Actually let me just run all admin-related test directories. Let me run the whole `admin_` suite.

Let me run admin_default_site, admin_registration, admin_ordering, admin_views etc. Actually let me just run a subset focusing on lookup and changelist. Let me run admin_changelist and admin_views plus modeladmin. Already did modeladmin, admin_views, admin_filters.

Let me also run the broader `admin_` tests quickly.

**assistant:** All 667 pass. Let me run the remaining admin test apps to be thorough:

23. `bash`: `cd /home/presenter/swe/task-c/django/tests && python runtests.py --settings=test_sqlite --parallel 1 admin_changelist admin_widgets admin_ordering 2>&1 | tail -6`

    .............................................................................................................ssssssss...........................ss........sssssss..ssssss.......
    ----------------------------------------------------------------------
    Ran 176 tests in 1.621s
    
    OK (skipped=23)
    Destroying test database for alias 'default'...

> _think:_ All pass. Let me view the final diff.

24. `bash`: `cd /home/presenter/swe/task-c/django && git diff`

    diff --git a/django/contrib/admin/options.py b/django/contrib/admin/options.py
    index 5240b07..df9ea2c 100644
    --- a/django/contrib/admin/options.py
    +++ b/django/contrib/admin/options.py
    @@ -464,9 +464,19 @@ class BaseModelAdmin(metaclass=forms.MediaDefiningClass):
                 # It is allowed to filter on values that would be found from local
                 # model anyways. For example, if you filter on employee__department__id,
                 # then the id value would be  …

**assistant:** All tests pass (667 in the primary suites, plus 176 in additional admin apps). Here's a summary.

## Root cause

In `BaseModelAdmin.lookup_allowed()` (`django/contrib/admin/options.py`), the loop builds `relation_parts` — the list of relation hops — but skips appending any field that is a target field of the previous FK:

```python
if not prev_field or (
    prev_field.is_relation
    and field not in prev_field.path_infos[-1].target_fields
):
    relation_parts.append(part)
```

The idea: `employee__department__id` is redundant with `employee__department_id` because `id` is the plain PK the FK already reaches, so the `id` hop can be dropped. The problem is this drop is applied indiscriminately when a **relational** field is a target field — which happens whenever a FK points at a model whose primary key is itself a relation.

For `restaurant__place__country`:
- `restaurant` FK → `Restaurant`, whose PK is the `place` OneToOne to `Place`.
- Because `place` is `Restaurant`'s PK, it's in the FK's `target_fields`, so the code drops `place`.
- That leaves `relation_parts = ['restaurant', 'country']`, producing `restaurant__country`, which isn't in `list_filter` (`restaurant__place__country`) → `DisallowedModelAdminLookup` is raised.

The admin wrongly treats any FK-as-PK as concrete inheritance, where the parent-link PK genuinely is redundant.

## The fix

The drop should only happen when the relational target field is a genuine concrete-inheritance parent link — i.e. when the FK's target model *is a subclass of* the model being traversed to (`issubclass(...)`, e.g. `Employee` → `Person`). A OneToOne that is `primary_key=True` but points at an unrelated model (`Restaurant` → `Place`) must be kept, because the following lookups (`country`) are only reachable through it:

```python
if not prev_field or (
    prev_field.is_relation
    and (
        field not in prev_field.path_infos[-1].target_fields
        or field.is_relation
        and not issubclass(prev_field.related_model, field.related_model)
    )
):
    relation_parts.append(part)
```

This keeps the existing drop behaviour for plain PK lookups and for concrete-inheritance parent links (so `employee__person_ptr__exact` still resolves to the `employee` filter), while preserving foreign-key-as-primary-key hops in the lookup path.

I added a regression test `test_lookup_allowed_foreign_primary` in `tests/modeladmin/tests.py` exactly as described in the issue.

