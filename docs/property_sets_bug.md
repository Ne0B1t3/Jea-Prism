# The `property_sets` issue in pypsrp

## Symptom

Against a JEA endpoint in `NoLanguage`, running `Get-Content` over a file
returned, per line, a `GenericComplexObject` whose `to_string` was `None`
and whose `extended_properties` only held PowerShell metadata (`PSPath`,
`PSParentPath`, `PSChildName`, `PSDrive`, `PSProvider`, `ReadCount`) — no
actual content.

## Why it happens

`Get-Content` decorates each returned line with a `PSObject` that attaches
those NoteProperties to the `BaseObject` (the real string). In CLIXML, that
serialises roughly as:

```xml
<Obj RefId="0">
  <TN><T>System.String</T>...</TN>
  <MS>
    <S N="PSPath">C:\...</S>
    <S N="PSChildName">credentials</S>
    ...
  </MS>
  <S>the actual line content</S>  <!-- loose primitive -->
</Obj>
```

In `pypsrp/serializer.py`, `_deserialize_dynamic_obj` iterates the `<Obj>`'s
children and classifies them like this:

```python
for obj_property in element:
    if obj_property.tag == "TN":
        ...
    elif obj_property.tag == "Props":
        ...
    elif obj_property.tag == "MS":
        for extended_property in obj_property:
            key = extended_property.attrib["N"]
            value = self.deserialize(extended_property, clear=False)
            obj.extended_properties[key] = value
    elif obj_property.tag == "ToString":
        value = self.deserialize(obj_property, clear=False)
        obj.to_string = value
    else:
        value = self.deserialize(obj_property, clear=False)
        obj.property_sets.append(value)   # <-- here
```

The `<S>` primitive sibling of `<MS>` isn't `TN`/`Props`/`MS`/`ToString`, so
it falls into the `else` branch and gets appended to `obj.property_sets` — a
list that most consuming code (including this project's original client, in
its first iteration) never looks at.

## Why this isn't a pypsrp bug to fix upstream

It's the expected behaviour of the generic deserialiser: when it doesn't
know what a decorated primitive represents, it stashes it in a list rather
than assuming it's "the value". Reconstructing the useful value is left to
the consumer.

Confirmation that this is a known pattern: Ansible's **PSRP connector**
solved this exact same case in its own client layer, building the string by
hand whenever `GenericComplexObject.to_string is None`, rather than patching
`pypsrp` itself (see the `psrp - fix unicode handling in Python 2` PR in the
Ansible repository, which discusses `GenericComplexObject` and `to_string`).

## The fix

In `jea_prism/parsing.py`, `extract_value()` checks `property_sets` as a
value source **before** falling back to `adapted_properties`/
`extended_properties`:

```python
property_sets = getattr(item, "property_sets", None)
if property_sets:
    for v in property_sets:
        if v is not None and str(v) != "None":
            return str(v)
```

With this, any decorated primitive (not just `Get-Content` — any cmdlet
returning objects with ETS NoteProperties attached) is extracted correctly.

## How to diagnose this yourself elsewhere

1. Run the suspect cmdlet with `--debug` (or `?cmdlet` in the shell).
2. If `to_string` comes back `None` and the properties only show metadata,
   suspect `property_sets`.
3. To confirm at the protocol level: `pip install pypsrp` locally and read
   `_deserialize_dynamic_obj` in `serializer.py` — that's the function that
   decides where each child tag of the `<Obj>` ends up.
