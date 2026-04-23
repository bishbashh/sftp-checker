#!/usr/bin/env python3
"""
SFTP Checker - Connect via proxy and list directories.
Mirrors the FileZilla "Generic proxy" + "SFTP site" setup.

Steps:
  1. Try direct SFTP connection (no proxy)
  2. If direct fails → try via proxy
  3. List directories on success

Requirements:
    pip install paramiko PySocks

Usage (interactive):
    python sftp_checker.py

Usage (non-interactive / Routines / CLI):
    python sftp_checker.py \
        --proxy-host 195.28.181.203 --proxy-port 6128 \
        --proxy-user southsurf     --proxy-pass SECRET \
        --proxy-type http \
        --sftp-host 85.159.209.22  --sftp-port 8022 \
        --sftp-user jbbqujnx       --sftp-pass SECRET

Or via environment variables:
    PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, PROXY_TYPE
    SFTP_HOST,  SFTP_PORT,  SFTP_USER,  SFTP_PASS
"""

import argparse
import getpass
import os
import socket
import sys

try:
    import paramiko
except ImportError:
    sys.exit("Missing dependency: pip install paramiko")

try:
    import socks
except ImportError:
    sys.exit("Missing dependency: pip install PySocks")

# ── proxy type map ────────────────────────────────────────────────────────────
PROXY_TYPE_MAP = {
    "http":   ("HTTP/1.1 CONNECT", socks.HTTP),
    "socks4": ("SOCKS 4",          socks.SOCKS4),
    "socks5": ("SOCKS 5",          socks.SOCKS5),
    "1":      ("HTTP/1.1 CONNECT", socks.HTTP),
    "2":      ("SOCKS 4",          socks.SOCKS4),
    "3":      ("SOCKS 5",          socks.SOCKS5),
}

# ─────────────────────────────────────────────────────────────────────────────

def section(title: str):
    print()
    print(f"─── {title} " + "─" * max(0, 50 - len(title)))

def inp(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {label}{suffix}: ").strip()
    return val if val else default

def secret_inp(label: str) -> str:
    return getpass.getpass(f"  {label}: ")

# ─────────────────────────────────────────────────────────────────────────────

def try_sftp_direct(sftp_host, sftp_port, sftp_user, sftp_pass, timeout=10):
    """Attempt a direct SFTP connection (no proxy). Returns (success, entries|None)."""
    print(f"  [..] Trying direct connection to {sftp_host}:{sftp_port}...", end=" ", flush=True)
    try:
        raw_sock = socket.create_connection((sftp_host, sftp_port), timeout=timeout)
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"FAIL ({e})")
        return False, None

    transport = paramiko.Transport(raw_sock)
    transport.banner_timeout = timeout
    transport.auth_timeout   = timeout
    try:
        transport.connect(username=sftp_user, password=sftp_pass)
    except (paramiko.AuthenticationException, paramiko.SSHException) as e:
        print(f"FAIL ({e})")
        raw_sock.close()
        return False, None

    print("OK  ✓  (no proxy needed!)")
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        entries = sftp.listdir_attr(".")
    finally:
        sftp.close()
        transport.close()
    return True, entries


def try_sftp_via_proxy(
    proxy_label, proxy_type,
    proxy_host, proxy_port, proxy_user, proxy_pass,
    sftp_host,  sftp_port,  sftp_user,  sftp_pass,
    timeout=20,
):
    """Attempt SFTP connection through proxy. Returns (success, entries|None)."""
    print(f"  [..] Opening proxy tunnel [{proxy_label}] {proxy_host}:{proxy_port}...",
          end=" ", flush=True)
    sock = socks.socksocket()
    sock.set_proxy(proxy_type, proxy_host, proxy_port, True,
                   proxy_user or None, proxy_pass or None)
    sock.settimeout(timeout)
    try:
        sock.connect((sftp_host, sftp_port))
    except socks.ProxyConnectionError as e:
        print(f"FAIL (cannot reach proxy: {e})")
        return False, None
    except socks.GeneralProxyError as e:
        print(f"FAIL (proxy rejected: {e})")
        return False, None
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"FAIL (socket: {e})")
        return False, None
    print("OK")

    print("  [..] SSH handshake...", end=" ", flush=True)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = timeout
    transport.auth_timeout   = timeout
    try:
        transport.connect(username=sftp_user, password=sftp_pass)
    except paramiko.AuthenticationException:
        print("FAIL (wrong username or password)")
        transport.close()
        return False, None
    except paramiko.SSHException as e:
        print(f"FAIL (SSH: {e})")
        transport.close()
        return False, None
    print("OK")

    print("  [..] Opening SFTP channel...", end=" ", flush=True)
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("OK")
    try:
        entries = sftp.listdir_attr(".")
    finally:
        sftp.close()
        transport.close()
    return True, entries


def print_listing(entries, method: str):
    section(f"Remote directory listing  (via {method})")
    print()
    if not entries:
        print("  (empty directory)")
        return
    entries.sort(key=lambda e: (not bool(e.st_mode and e.st_mode & 0o40000),
                                e.filename.lower()))
    col_w = max(len(e.filename) for e in entries) + 2
    print(f"  {'TYPE':<5}  {'SIZE':>12}  {'NAME'}")
    print(f"  {'─'*5}  {'─'*12}  {'─'*col_w}")
    for e in entries:
        is_dir = bool(e.st_mode and e.st_mode & 0o40000)
        ftype  = "DIR"  if is_dir else "FILE"
        sz     = "-"   if is_dir else f"{e.st_size:,}"
        print(f"  {ftype:<5}  {sz:>12}  {e.filename}")

# ─────────────────────────────────────────────────────────────────────────────

def gather_interactive():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║          SFTP Checker  (FileZilla style)         ║")
    print("╚══════════════════════════════════════════════════╝")

    # ── SFTP credentials first ────────────────────────────────────────────────
    section("SFTP Site  (New Site → SFTP – SSH File Transfer Protocol)")
    sftp_host = inp("Host")
    sftp_port = int(inp("Port", "22"))
    sftp_user = inp("User")
    sftp_pass = secret_inp("Password")

    # ── Ask about proxy ───────────────────────────────────────────────────────
    print()
    use_proxy = input("  Do you want to use a proxy? (y/n) [n]: ").strip().lower()
    use_proxy = use_proxy in ("y", "yes")

    ptype_key  = None
    proxy_host = None
    proxy_port = 0
    proxy_user = ""
    proxy_pass = ""

    if use_proxy:
        section("Generic Proxy  (Connection → Generic proxy)")
        print()
        print("    Type of generic proxy:")
        print("      1. HTTP/1.1 CONNECT")
        print("      2. SOCKS 4")
        print("      3. SOCKS 5")
        print()
        ptype_key  = inp("Proxy type", "1")
        proxy_host = inp("Proxy host")
        proxy_port = int(inp("Proxy port", "8080"))
        proxy_user = inp("Proxy user (leave blank if none)")
        proxy_pass = secret_inp("Proxy password") if proxy_user else ""

    return ptype_key, proxy_host, proxy_port, proxy_user, proxy_pass, \
           sftp_host, sftp_port, sftp_user, sftp_pass, use_proxy

# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Check SFTP (tries direct first, then proxy) and list directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--proxy-host", default=os.getenv("PROXY_HOST"))
    parser.add_argument("--proxy-port", type=int, default=int(os.getenv("PROXY_PORT", "0") or 0))
    parser.add_argument("--proxy-user", default=os.getenv("PROXY_USER", ""))
    parser.add_argument("--proxy-pass", default=os.getenv("PROXY_PASS", ""))
    parser.add_argument("--proxy-type", default=os.getenv("PROXY_TYPE", "http"),
                        choices=["http", "socks4", "socks5"])
    parser.add_argument("--sftp-host", default=os.getenv("SFTP_HOST"))
    parser.add_argument("--sftp-port", type=int, default=int(os.getenv("SFTP_PORT", "22") or 22))
    parser.add_argument("--sftp-user", default=os.getenv("SFTP_USER"))
    parser.add_argument("--sftp-pass", default=os.getenv("SFTP_PASS"))

    args = parser.parse_args()

    non_interactive = all([args.proxy_host, args.proxy_port,
                           args.sftp_host, args.sftp_user, args.sftp_pass])

    if non_interactive:
        ptype_key  = args.proxy_type
        proxy_host = args.proxy_host
        proxy_port = args.proxy_port
        proxy_user = args.proxy_user
        proxy_pass = args.proxy_pass
        sftp_host  = args.sftp_host
        sftp_port  = args.sftp_port
        sftp_user  = args.sftp_user
        sftp_pass  = args.sftp_pass
        use_proxy  = bool(proxy_host and proxy_port)
    else:
        (ptype_key, proxy_host, proxy_port, proxy_user, proxy_pass,
         sftp_host, sftp_port, sftp_user, sftp_pass, use_proxy) = gather_interactive()

    if use_proxy:
        if ptype_key not in PROXY_TYPE_MAP:
            sys.exit(f"[ERROR] Unknown proxy type: {ptype_key}")
        proxy_label, proxy_type = PROXY_TYPE_MAP[ptype_key]

        # ── Connect via proxy ─────────────────────────────────────────────────
        section("Connecting via Proxy")
        print()
        ok, entries = try_sftp_via_proxy(
            proxy_label, proxy_type,
            proxy_host, proxy_port, proxy_user, proxy_pass,
            sftp_host,  sftp_port,  sftp_user,  sftp_pass,
        )
    else:
        # ── Connect direct ────────────────────────────────────────────────────
        section("Connecting Direct (no proxy)")
        print()
        ok, entries = try_sftp_direct(sftp_host, sftp_port, sftp_user, sftp_pass)

    if ok:
        print_listing(entries, "proxy" if use_proxy else "direct")
        print()
        print("  [SUCCESS] Done.")
    else:
        print()
        print("  [FAIL] Connection failed.")

    if not non_interactive:
        print()
        input("Press Enter to exit...")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
