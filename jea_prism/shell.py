"""
shell.py — Interactive REPL against the JEA runspace.

Execution backend by Language Mode:

  FullLanguage / ConstrainedLanguage
      Each line is sent as-is as a script block (run_script). You can
      write PowerShell almost normally: variables, pipes, operators.
      In ConstrainedLanguage the server itself will reject whatever is
      restricted (disallowed .NET types, etc.) — that rejection is
      itself useful signal for the assessment, no need to simulate it
      here.

      Caveat worth knowing: a short `Get-Command` whitelist does NOT by
      itself mean arbitrary external binaries are blocked. The cmdlet
      whitelist and VisibleExternalCommands are separate controls, so
      `&{whoami}` (or any other external .exe) can still work in
      ConstrainedLanguage even when only a handful of cmdlets are
      listed — worth testing explicitly rather than assuming.

  NoLanguage
      Each line is parsed by hand (client.build_pipeline) and sent as a
      cmdlet pipeline via add_cmdlet/add_parameter/add_argument. Script
      blocks (`&{...}`) are never attempted and will not work here —
      the server rejects script parsing outright. Only whitelisted
      cmdlets (and pipelines of them) are reachable.

Special shell commands (not sent to the server):
  exit / quit          leave the shell
  ?<line>               force debug output for that one line only
  :mode                 show the detected Language Mode
  :mode full|constrained|nolanguage
                        manually override the backend (useful if
                        auto-detection is wrong, or to compare behaviour)
"""
from . import client
from .modes import LanguageMode, detect_language_mode
from .parsing import print_out


_MODE_ALIASES = {
    "full": LanguageMode.FULL,
    "fulllanguage": LanguageMode.FULL,
    "constrained": LanguageMode.CONSTRAINED,
    "constrainedlanguage": LanguageMode.CONSTRAINED,
    "nolanguage": LanguageMode.NOLANGUAGE,
    "nolang": LanguageMode.NOLANGUAGE,
}

_SCRIPT_CAPABLE = (LanguageMode.FULL, LanguageMode.CONSTRAINED)

_MODE_NOTES = {
    LanguageMode.FULL: "No restrictions — script blocks, variables and pipes all work normally.",
    LanguageMode.CONSTRAINED: (
        "Script blocks allowed. Note: a short cmdlet whitelist doesn't imply "
        "external commands are blocked too — try `&{whoami}` or similar, it may still work (VisibleExternalCommands is a separate control)."
    ),
    LanguageMode.NOLANGUAGE: (
        "Script blocks are rejected by the server — only whitelisted cmdlets "
        "work, alone or piped together. `&{...}` will not work here."
    ),
    LanguageMode.UNKNOWN: "Detection inconclusive — defaulting to the cmdlet-only backend to stay safe.",
}


def _run_script_for_detection(pool, script_text):
    return client.run_script(pool, script_text)


def interactive_shell(pool, debug: bool = False):
    mode = detect_language_mode(pool, _run_script_for_detection)
    print(f"[*] Language Mode: {mode.value}")
    print(f"[*] {_MODE_NOTES.get(mode, '')}")
    print(f"[*] JEA-prism{'  [DEBUG]' if debug else ''}")
    print("     ?cmd = dump properties  |  :mode <full|constrained|nolang>\n")

    
    while True:
        try:
            line = input("JEA> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            break

        if line.lower() == ":mode":
            print(f"  Current mode: {mode.value}")
            continue
        if line.lower().startswith(":mode "):
            arg = line.split(None, 1)[1].strip().lower()
            if arg in _MODE_ALIASES:
                mode = _MODE_ALIASES[arg]
                print(f"  Mode forced to: {mode.value}")
            else:
                print(f"  Unknown mode. Options: {list(_MODE_ALIASES)}")
            continue

        force_debug = line.startswith("?")
        if force_debug:
            line = line[1:].strip()

        try:
            if mode in _SCRIPT_CAPABLE:
                out, had_errors, errors = client.run_script(pool, line)
                if had_errors and any(
                    "language mode" in e.lower() or "cannot be run" in e.lower() for e in errors
                ):
                    print("  [!] Script rejected by the server (Language Mode). "
                          "Retrying as a cmdlet pipeline...")
                    out, had_errors, errors = client.run_pipeline(pool, line)
            else:
                out, had_errors, errors = client.run_pipeline(pool, line)
        except Exception as exc:
            print(f"  [!] Local exception: {exc}")
            continue

        if had_errors:
            for e in errors:
                print(f"  [!] {e}")

        print_out(out, debug=(debug or force_debug))
