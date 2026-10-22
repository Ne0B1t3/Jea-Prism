"""
enum_cmdlets.py — Enumerate the JEA whitelist (Get-Command) and dump help
for custom cmdlets/functions, usually the juiciest attack surface on a
misconfigured JEA endpoint (custom logic = custom bugs).
"""
from . import client
from .parsing import extract_value, print_out


def enumerate_commands(pool, debug: bool = False):
    print("\n[*] Cmdlets available on this JEA configuration:")
    out, had_errors, errors = client.run_cmdlet(pool, "Get-Command")
    if had_errors:
        for e in errors:
            print(f"  [!] {e}")
    if not out:
        print("    [ ] No response.")
        return []

    custom = []
    print(f"    {'Name':<45} {'Type'}")
    print(f"    {'-'*45} {'-'*10}")
    for item in out:
        name = extract_value(getattr(item, "Name", None) or item)
        ctype = extract_value(getattr(item, "CommandType", ""))
        print(f"    {name:<45} {ctype}")
        if ctype in ("Function", "Script"):
            custom.append(name)

    if custom:
        print(f"\n  [!!!] Custom commands (bespoke attack surface): {custom}")
        for c in custom:
            print(f"\n  --- Get-Help {c} ---")
            help_out, _, _ = client.run_cmdlet(pool, "Get-Help", {"-Name": c})
            print_out(help_out, debug=debug)

    return custom
