"""
client.py — WSMan/RunspacePool connection and invocation helpers.

Two execution paths, both independent of the Language Mode because PSRP
operates at the protocol level (it serialises pipelines to CLIXML rather
than evaluating script text client-side):

  run_cmdlet() / run_pipeline()
      Builds the pipeline cmdlet by cmdlet via add_cmdlet/add_parameter/
      add_argument. Works in ANY Language Mode, including NoLanguage, as
      long as the cmdlet is on the JEA configuration's whitelist.

  run_script()
      Sends a raw script block (add_script). Only works if the Language
      Mode allows it (FullLanguage / ConstrainedLanguage). In NoLanguage
      the server returns a parsing error — the caller is expected to
      fall back to run_cmdlet.

Authentication
---------------
Two modes are supported, matching what WSMan accepts:

  Password  (auth="negotiate"/"ntlm"/"basic"/"credssp")
      Standard username + password.

  Kerberos ticket  (auth="kerberos")
      No password is sent. Instead, a credential cache (ccache) file is
      pointed to via the KRB5CCNAME environment variable before opening
      the connection, pypsrp's underlying GSSAPI/SSPI layer will then
      pick up the ticket from that cache. A username is still required
      (used to build the server SPN), but its value is not used to
      authenticate - the ticket is. This mirrors the approach used in
      ad-hoc Kerberos PSRP scripts: set KRB5CCNAME, pass auth="kerberos",
      leave password=None, and optionally set negotiate_delegate=True
      for credential delegation to a second hop.
"""
import os
import shlex
import typing

from pypsrp.powershell import PowerShell, RunspacePool
from pypsrp.wsman import WSMan


def _tokenize(line: str) -> typing.List[str]:
    """Splits a line into tokens, respecting quotes but WITHOUT treating
    backslash as an escape character. shlex.split()'s default POSIX mode
    does treat '\\' as an escape, which silently mangles Windows paths -
    'C:\\users' becomes 'C:users'. Since this client talks to Windows
    almost exclusively, backslashes must stay literal."""
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quotes etc. — fall back to a naive split rather than crash.
        return line.split()


def connect(
    host: str,
    port: int,
    username: str,
    password: typing.Optional[str] = None,
    ssl: bool = False,
    cert_validation: bool = False,
    configuration_name: typing.Optional[str] = None,
    auth: str = "negotiate",
    ccache: typing.Optional[str] = None,
    negotiate_delegate: bool = False,
    nt_hash: typing.Optional[str] = None,   
    lm_hash: typing.Optional[str] = None,   
) -> RunspacePool:
    if ccache:
        os.environ["KRB5CCNAME"] = ccache

    wsman_kwargs: dict = {}
    if auth == "kerberos":
        wsman_kwargs["negotiate_delegate"] = negotiate_delegate

    wsman = WSMan(
        server=host, port=port, username=username, password=password,
        ssl=ssl, cert_validation=cert_validation, auth=auth, **wsman_kwargs,
    )

    # NT hash authentication
    if nt_hash:
        import spnego
        # pypsrp builds the requests.Session + auth object lazily on first
        # send(); force it now so we can swap the credential before any
        # auth handshake happens.
        wsman.transport.session = wsman.transport._build_session()
        wsman.transport.session.auth.username = spnego.NTLMHash(
            username=username, nt_hash=nt_hash, lm_hash=lm_hash,
        )
        wsman.transport.session.auth.password = None

    kw = {"configuration_name": configuration_name} if configuration_name else {}
    pool = RunspacePool(wsman, **kw)
    pool.open()
    return pool


def run_cmdlet(pool: RunspacePool, cmdlet: str, params: typing.Optional[dict] = None):
    ps = PowerShell(pool)
    cmd = ps.add_cmdlet(cmdlet)
    for k, v in (params or {}).items():
        name = k.lstrip("-")
        cmd.add_parameter(name) if v is True else cmd.add_parameter(name, v)
    out = ps.invoke()
    errors = [str(e) for e in ps.streams.error] if ps.had_errors else []
    return out, ps.had_errors, errors


def parse_line(line: str) -> typing.Tuple[typing.Optional[str], dict, list]:
    """Returns (cmdlet, named_params, positional_args)."""
    tokens = _tokenize(line)
    if not tokens:
        return None, {}, []
    cmdlet, params, positional, i = tokens[0], {}, [], 1
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("-"):
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                params[t] = tokens[i + 1]
                i += 2
            else:
                params[t] = True
                i += 1
        else:
            positional.append(t)
            i += 1
    return cmdlet, params, positional


def build_pipeline(pool: RunspacePool, line: str) -> PowerShell:
    """Builds a multi-cmdlet pipeline from 'cmdA -x 1 y | cmdB -z'.

    Each segment is parsed cmdlet by cmdlet. Dashed tokens become named
    parameters; anything else becomes a positional argument via
    add_argument(), which PowerShell's own parameter binder resolves on
    the server side (e.g. the bare path in `Get-ChildItem C:\\users`
    binds to -Path automatically, exactly as it would in a normal
    console). This never goes through a script parser, so it remains
    valid even in NoLanguage."""
    ps = PowerShell(pool)
    for part in [p.strip() for p in line.split("|")]:
        if not part:
            continue
        tokens = _tokenize(part)
        if not tokens:
            continue
        cmd = ps.add_cmdlet(tokens[0])
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t.startswith("-"):
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    cmd.add_parameter(t.lstrip("-"), tokens[i + 1])
                    i += 2
                else:
                    cmd.add_parameter(t.lstrip("-"))
                    i += 1
            else:
                cmd.add_argument(t)  # positional binding, e.g. bare -Path value
                i += 1
    return ps


def run_pipeline(pool: RunspacePool, line: str):
    ps = build_pipeline(pool, line)
    out = ps.invoke()
    errors = [str(e) for e in ps.streams.error] if ps.had_errors else []
    return out, ps.had_errors, errors


def run_script(pool: RunspacePool, script_text: str):
    """Only valid if the Language Mode allows script parsing
    (Full/ConstrainedLanguage). In NoLanguage the server rejects this
    with a parsing error — the caller must fall back."""
    ps = PowerShell(pool)
    ps.add_script(script_text)
    out = ps.invoke()
    errors = [str(e) for e in ps.streams.error] if ps.had_errors else []
    return out, ps.had_errors, errors
