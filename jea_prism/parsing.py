"""
parsing.py — Robust value extraction from pypsrp objects.

Why this module exists
-----------------------
pypsrp deserialises the CLIXML returned by the server into
`GenericComplexObject` instances. When the object is a "decorated"
primitive (a PSObject whose BaseObject is e.g. System.String, but with
extra NoteProperties attached — typical of `Get-Content`, which adds
PSPath/PSParentPath/PSChildName/PSDrive/PSProvider/ReadCount to every
line), the base value does NOT show up in `.to_string` nor in
`.adapted_properties`/`.extended_properties`.

Looking at pypsrp's deserialiser (`serializer.py::_deserialize_dynamic_obj`):
any child tag that isn't `TN`, `Props`, `MS` or `ToString` is dumped
verbatim into `obj.property_sets` (a list). The base primitive (the
`<S>` sibling of `<MS>`) ends up right there. If you never look at
`property_sets`, the data "disappears" even though it arrived on the
wire.

External reference: Ansible's PSRP connector had to solve this exact
same problem by building the string by hand whenever
`GenericComplexObject.to_string is None`. This isn't a bug pypsrp
intends to fix in the library — it's left to the consumer on purpose.
"""
import typing


def _iter_props(props) -> typing.Iterator[typing.Tuple[str, typing.Any]]:
    """Normalise adapted_properties/extended_properties (an OrderedDict
    in modern pypsrp, but defensively handled as a list of objects with
    .name/.value attributes in case of older versions) into (name, value)
    pairs."""
    if not props:
        return
    if isinstance(props, dict):
        for k, v in props.items():
            yield k, v
    else:
        for prop in props:
            yield getattr(prop, "name", "?"), getattr(prop, "value", None)


def extract_value(item) -> str:
    """Extract the "useful" value from an object returned by pypsrp, in
    order: direct primitives -> to_string -> property_sets (FIX) ->
    adapted/extended properties -> .value -> fallback str(item)."""
    if item is None:
        return ""
    if isinstance(item, (str, int, float, bool)):
        return str(item)

    ts = getattr(item, "to_string", None)
    if ts is not None:
        return str(ts)

    # --- FIX: the decorated base primitive (e.g. Get-Content lines)
    # ends up in property_sets, not to_string. Without this, Get-Content
    # over files returns empty strings / metadata only.
    property_sets = getattr(item, "property_sets", None)
    if property_sets:
        for v in property_sets:
            if v is not None and str(v) != "None":
                return str(v)

    for bucket in ("adapted_properties", "extended_properties"):
        for _name, v in _iter_props(getattr(item, bucket, None)):
            if v is not None and str(v) != "None":
                return str(v)

    v = getattr(item, "value", None)
    if v is not None:
        return str(v)

    raw = str(item)
    return "" if raw == "None" else raw


def debug_dump(item, index: int) -> str:
    """Return a readable multi-line dump of an object, for --debug."""
    lines = [
        f"  [DEBUG #{index}]",
        f"    type          : {type(item)}",
        f"    repr          : {repr(item)[:300]}",
        f"    to_string     : {getattr(item, 'to_string', 'N/A')!r}",
        f"    value         : {getattr(item, 'value', 'N/A')!r}",
        f"    property_sets : {getattr(item, 'property_sets', 'N/A')!r}",
    ]
    for bucket in ("adapted_properties", "extended_properties"):
        props = getattr(item, bucket, None)
        pairs = list(_iter_props(props))
        if pairs:
            lines.append(f"    {bucket}:")
            for name, v in pairs:
                lines.append(f"      {name} = {v!r}")
    return "\n".join(lines)


def print_out(output, debug: bool = False) -> None:
    if not output:
        if debug:
            print("  [DEBUG] empty output (0 elements)")
        return

    if debug:
        print(f"  [DEBUG] {len(output)} object(s) received:")

    for i, item in enumerate(output):
        if debug:
            print(debug_dump(item, i))
        print(extract_value(item))
