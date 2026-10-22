"""
modes.py — Detection of the Language Mode in use on the JEA/PSRP session.

PowerShell supports four Language Modes, from most to least permissive:
  FullLanguage        -> no restrictions, full scripting
  ConstrainedLanguage -> scripting allowed, .NET types/methods restricted
  RestrictedLanguage  -> almost no scripting at all (rare in JEA)
  NoLanguage          -> zero script parsing; only direct invocation of
                          whitelisted cmdlets (the "hard" JEA setup)

Note on ConstrainedLanguage in practice: the cmdlet whitelist shown by
`Get-Command` is NOT the same control as `VisibleExternalCommands`. A JEA
endpoint can restrict the cmdlet list while leaving external commands
reachable via a script block (e.g. `&{whoami}`), because that's governed
by a separate setting. Don't assume a short `Get-Command` list means
script-block invocation of arbitrary binaries is blocked too — test it.
"""
import enum


class LanguageMode(str, enum.Enum):
    FULL = "FullLanguage"
    CONSTRAINED = "ConstrainedLanguage"
    RESTRICTED = "RestrictedLanguage"
    NOLANGUAGE = "NoLanguage"
    UNKNOWN = "Unknown"


def detect_language_mode(pool, run_script_fn) -> "LanguageMode":
    """
    Attempts to read $ExecutionContext.SessionState.LanguageMode via a
    script block. If the server rejects the script (NoLanguage won't
    even parse the expression), NoLanguage is assumed by elimination.

    run_script_fn: callable(pool, script_text) -> (output_list, had_errors, error_strs)
    """
    try:
        out, had_errors, errors = run_script_fn(
            pool, "$ExecutionContext.SessionState.LanguageMode"
        )
    except Exception:
        return LanguageMode.NOLANGUAGE

    if had_errors:
        joined = " ".join(errors).lower()
        if "language mode" in joined or "cannot be run" in joined or "is not supported" in joined:
            return LanguageMode.NOLANGUAGE
    if out:
        val = str(out[0]).strip()
        for mode in LanguageMode:
            if mode.value == val:
                return mode

    return LanguageMode.NOLANGUAGE if not out else LanguageMode.UNKNOWN
