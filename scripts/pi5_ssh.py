#!/usr/bin/env python
"""SSH helper: run a command on the Pi5 (192.168.100.51) and print stdout/stderr.
Usage: python pi5_ssh.py '<command>'
"""
import sys, paramiko

HOST = "192.168.100.51"
USER = "ba4b0d"
PASS = "Adadep@1625"

def run(cmd, timeout=60):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=15, look_for_keys=False, allow_agent=False)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        if out: print(out.rstrip())
        if err: print("STDERR:", err.rstrip()[:2000], file=sys.stderr)
        return rc
    finally:
        client.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hostname"
    t = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    sys.exit(run(cmd, timeout=t))