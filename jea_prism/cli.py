"""
cli.py - Entry point. No hardcoded credentials: everything comes from
arguments, environment, a Kerberos ticket cache, or an interactive
prompt as a last resort.
"""
import argparse
import getpass
import os
import sys

from . import client
from .enum_cmdlets import enumerate_commands
from .parsing import print_out
from .shell import interactive_shell


def _common_args(p: argparse.ArgumentParser):
    p.add_argument("host")
    p.add_argument("-u", "--username", required=True,
                    help="Required even with --auth kerberos: used to build the server SPN.")
    p.add_argument(
        "-p", "--password",
        help="If omitted, falls back to $JEA_PRISM_PASSWORD, then an interactive "
             "prompt, unless --auth kerberos is set, in which case no password "
             "is needed at all.",
    )
    p.add_argument("--port", type=int, default=5985)
    p.add_argument("--ssl", action="store_true")
    p.add_argument("--no-cert-validation", action="store_true", default=True)
    p.add_argument("--configuration-name", default=None,
                    help="JEA endpoint name, as shown by Get-PSSessionConfiguration -ConfigurationName.")
    p.add_argument(
        "--auth", default="negotiate",
        choices=["negotiate", "ntlm", "kerberos", "basic", "credssp"],
        help="Authentication protocol. Use 'kerberos' with --ccache for ticket-based auth.",
    )
    p.add_argument(
        "--ccache",
        help="Path to a Kerberos credential cache (ccache) file, e.g. a ticket "
             "obtained via impacket/getTGT or Rubeus. Sets KRB5CCNAME before "
             "connecting. Only meaningful with --auth kerberos.",
    )
    p.add_argument(
        "--negotiate-delegate", action="store_true",
        help="Delegate the Kerberos ticket to a second hop (credential delegation). "
             "Only meaningful with --auth kerberos.",
    )
    p.add_argument("--debug", action="store_true")


def _resolve_password(args) -> str:
    if args.password:
        return args.password
    env_pw = os.environ.get("JEA_PRISM_PASSWORD")
    if env_pw:
        return env_pw
    if args.auth == "kerberos":
        # Ticket-based auth: no password needed, the ccache does the work.
        return None
    return getpass.getpass(f"Password for {args.username}: ")


def main():
    parser = argparse.ArgumentParser(
        prog="jea-prism",
        description="WinRM/PSRP client for assessing JEA endpoints in any Language Mode.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_connect = sub.add_parser(
        "connect",
        help="Open an interactive shell against the endpoint.",
        description="Open an interactive shell against the endpoint.",
        epilog=(
            "Interactive commands:\n"
            "  ?cmd              Dump every property of the result (debug one-off).\n"
            "  :mode             Show current Language Mode.\n"
            "  :mode <mode>      Force a mode: full, constrained, or nolang.\n"
            "  :help             Show this help again inside the shell.\n"
            "\n"
            "Note: remote objects aren't reformatted like local PowerShell (no format.ps1xml). A bare type name like 'System.Diagnostics.Process (name)' is normal; use '?cmd' to see its properties"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common_args(p_connect)

    p_run = sub.add_parser(
        "run",
        help="Run a single command/pipeline and exit.",
        description="Run a single command/pipeline against the endpoint and exit.",
        epilog=(
            "Examples:\n"
            '  jea-prism run <host> -u <user> -p <pass> "Get-Process"\n'
            '  jea-prism run <host> -u <user> -p <pass> "Get-Process | Select-Object -First 5"\n'
            "\n"
            "Only whitelisted cmdlets of the JEA configuration can be used."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common_args(p_run)
    p_run.add_argument("line", help='Command or pipeline, e.g. "Get-Content -Path C:\\file.txt"')

    p_enum = sub.add_parser(
        "enum",
        help="Only enumerate available cmdlets and dump Get-Help for custom ones.",
        description="Enumerate the cmdlets exposed by the JEA configuration and dump Get-Help for custom ones.",
        epilog=(
            "Useful to map the attack surface of an endpoint before trying to abuse allowed cmdlets or parameters."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common_args(p_enum)

    args = parser.parse_args()
    password = _resolve_password(args)

    print(f"[*] Connecting to {args.host}:{args.port} as '{args.username}' (auth={args.auth})...")
    try:
        pool = client.connect(
            host=args.host,
            port=args.port,
            username=args.username,
            password=password,
            ssl=args.ssl,
            cert_validation=not args.no_cert_validation,
            configuration_name=args.configuration_name,
            auth=args.auth,
            ccache=args.ccache,
            negotiate_delegate=args.negotiate_delegate,
        )
    except Exception as exc:
        sys.exit(f"[!] Connection error: {exc}")

    print("[+] Connected.")
    try:
        if args.command == "enum":
            enumerate_commands(pool, debug=args.debug)
        elif args.command == "run":
            out, had_errors, errors = client.run_pipeline(pool, args.line)
            if had_errors:
                for e in errors:
                    print(f"  [!] {e}")
            print_out(out, debug=args.debug)
        elif args.command == "connect":
            enumerate_commands(pool, debug=args.debug)
            interactive_shell(pool, debug=args.debug)
    finally:
        pool.close()
        print("[*] Closed.")


if __name__ == "__main__":
    main()
