# jea-prism

WinRM/PSRP client for assessing **JEA (Just Enough Administration)** endpoints
across all three Language Modes (`FullLanguage`, `ConstrainedLanguage`,
`NoLanguage`), built for authorised red team / CTF work (HTB Pro Labs,
VulnLab, in-house labs).

Unlike existing JEA clients that assume `ConstrainedLanguage`, `jea-prism`
detects the endpoint's Language Mode and adapts its execution backend
automatically, supports both password and Kerberos ticket authentication,
and fixes a `pypsrp` deserialisation issue that causes cmdlets like
`Get-Content` to return empty or metadata-only output.

## Why this exists

While working a JEA endpoint in `NoLanguage`, `Get-Content` over files kept
returning objects with no readable content, just metadata (`PSPath`,
`PSChildName`, `ReadCount`...). The server wasn't at fault: `pypsrp`
deserialises "decorated" primitives (a PSObject with ETS NoteProperties
attached, exactly what `Get-Content` returns per line) and dumps the base
value into an attribute (`property_sets`) that most clients never read. The
data arrives on the wire but gets lost client-side during parsing. See
[`docs/property_sets_bug.md`](docs/property_sets_bug.md) for the full
write-up with references to pypsrp's source.

## Why some objects print wrong (e.g. Get-Process shows `System.Diagnostics.Process (wsmprovhost)`)

This is a different symptom of the same root cause as the `property_sets`
issue above: **remote PSRP objects are not the same thing as local
PowerShell objects.**

When you run a cmdlet locally, PowerShell's formatting subsystem knows the
object's real .NET type and has a matching view definition
(`format.ps1xml`) that tells it how to render that type as a table or list, that's why `Get-Process` draws a nice table with Name, CPU, Id, etc.

When a cmdlet runs on a **remote** PSRP session, the server serialises the
result object to CLIXML and sends it over the wire. What comes back is not
the original object, it's a `Deserialized.<Type>` on PowerShell's own
side, or a `GenericComplexObject` once `pypsrp` parses it on ours. This is
just a snapshot of the object's properties: no methods, no attached
`format.ps1xml` view, and the "extended" properties often live in a
separate dictionary (`extended_properties`) rather than as first-class
attributes.

That's why `jea-prism` prints something like
`System.Diagnostics.Process (wsmprovhost)` instead of a formatted process
table: `extract_value()` falls back to Python's `str(item)` because it
doesn't know this particular `GenericComplexObject` "represents" a
process, there's no view registered for it, and no generic one exists.

### What it would take to fix properly

To reconstruct output exactly like local PowerShell for every cmdlet, each
object *type* would need its own handler that knows which properties to
pull out and how to lay them out, essentially reimplementing a slice of
PowerShell's own formatting engine, cmdlet by cmdlet. That's a lot of
surface area for a CTF/assessment tool, and not usually worth it.

### The practical shortcut: ? / --debug

Instead of reconstructing formatting per cmdlet, `jea-prism` gives you the
raw deserialised data whenever the default one-line-per-object output
isn't enough. Prefix any command with `?` (or pass `--debug` for the whole
session) and you get the full dump: every property, in every bucket
(`property_sets`, `adapted_properties`, `extended_properties`), exactly as
it came off the wire:

```bash
JEA> ? Get-Content C:\users\admin.aws\credentials
[DEBUG] 3 object(s) received:
[DEBUG #0]
...
    property_sets : ['[default]']
    extended_properties:
        PSPath = 'C:\users\admin\.aws\credentials'
...
[DEBUG #1]
...
```

## Installation

```bash
git clone https://github.com/Ne0b1t3/jea-prism
cd jea-prism
pip install -r requirements.txt
pip install -e .
```

## Usage

```bash
# Interactive shell (enumerates cmdlets, detects Language Mode, opens the REPL)
jea-prism connect 10.10.10.10 -u administrator

# A single command
jea-prism run 10.10.10.10 -u administrator "Get-Content -Path C:\Users\admin\file.txt"

# Enumeration only (Get-Command + Get-Help for custom cmdlets)
jea-prism enum 10.10.10.10 -u administrator --debug
```

The password can be passed with `-p`, left in `$JEA_PRISM_PASSWORD`, or if
neither is given, is prompted for interactively (never ends up in shell
history or `ps aux`).

### Kerberos ticket authentication

If you already hold a TGT/TGS for the target (e.g. via `impacket-getTGT`,
Rubeus, or any tool that produces a `.ccache`), you can authenticate with
the ticket instead of a password:

```bash
jea-prism connect 10.10.10.10 -u 'pepe@dc01.lab.local' \
    --auth kerberos \
    --ccache /home/users/pepe.ccache \
    --configuration-name restricted
```

`--username` is still required even with a ticket, pypsrp needs it to build
the server SPN, but its value isn't used for authentication; the ticket is.
Add `--negotiate-delegate` if you need credential delegation to a second hop.

## How the execution backend is chosen

| Language Mode | Backend | What it means for you |
|---|---|---|
| `FullLanguage` | `add_script` (raw script) | You can write near-normal PowerShell |
| `ConstrainedLanguage` | `add_script`, with automatic fallback to a cmdlet pipeline if the server rejects something | The server telling you what's restricted is itself useful signal for the assessment |
| `NoLanguage` | Cmdlet-by-cmdlet pipeline (`add_cmdlet`/`add_parameter`/`add_argument`) | Script parsing is never attempted; PSRP operates at the protocol level, so the cmdlet whitelist stays the only real barrier |

**Worth knowing for ConstrainedLanguage:** a short `Get-Command` whitelist
does not by itself mean external binaries are blocked. The cmdlet whitelist
and `VisibleExternalCommands` are separate controls, `&{whoami}` (or any
other `.exe`) can still work even when only a handful of cmdlets are listed.
Always test it explicitly rather than assuming the whitelist is the whole
story.

Inside the shell, `:mode` shows the detected mode and `:mode nolanguage`
(or `full` / `constrained`) forces it manually, useful for comparing
behaviour, or when auto-detection is inconclusive.

## Shell commands

```bash
exit / quit                        leave the shell
? <command>                        force debug output (--debug) for that one line only
:mode                              show the detected Language Mode
:mode <full|constrained|nolang>    force the backend manually
cmdA | cmdB                        multi-cmdlet pipeline, never goes through a script parser
```

### A note on argument syntax

Both named and positional arguments work, and they bind on the server side
exactly as they would in a normal console:

```bash
Get-ChildItem -Path C:\users
Get-ChildItem C:\users          # same thing — positional binding to -Path
Get-Content -Path 'C:\Users\admin\file.txt'
```

Backslashes in paths are preserved as-is, the tokenizer deliberately does
not treat `\` as an escape character (Python's `shlex.split()` does by
default, which silently turns `C:\users` into `C:users`; this client
disables that behaviour since it talks to Windows almost exclusively).

## Disclaimer

Offensive assessment tool for use in **authorised** environments (your own
labs, CTFs, engagements with explicit authorisation). The author is not
responsible for misuse.

## Credits

- [`pypsrp`](https://github.com/jborean93/pypsrp) — underlying PSRP/WinRM library.
- Inspired by the limitations observed in existing JEA clients such as
  [`evil-jea`](https://github.com/sashathomas/evil-jea), which covers
  Language Mode bypasses via `call`/`function` well but not the decorated
  object deserialisation issue documented here.
