"""A small real SMTP server for tests: speaks enough of the protocol (EHLO, STARTTLS, implicit TLS,
AUTH PLAIN, MAIL/RCPT/DATA) to exercise smtplib for real, and records what it was given.

Recipients steer behaviour: `refuse@` gets 550, `defer@` gets 450, `hangup@` drops the connection.
"""

import base64
import datetime
import re
import socket
import ssl
import threading
from dataclasses import dataclass, field

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def make_cert(directory) -> tuple[str, str, str]:
    """Self-signed certificate for localhost. Returns (cert_path, key_path, cert_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path, key_path = str(directory / "cert.pem"), str(directory / "key.pem")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    )
    directory.joinpath("cert.pem").write_bytes(pem)
    directory.joinpath("key.pem").write_bytes(key_pem)
    return cert_path, key_path, pem.decode()


@dataclass
class Received:
    mail_from: str
    rcpt: list[str]
    data: bytes
    tls: bool


@dataclass
class FakeSmtp:
    mode: str = "plain"  # plain | starttls | ssl | no-starttls
    credentials: tuple[str, str] | None = None
    cert: tuple[str, str] | None = None
    port: int = 0
    messages: list[Received] = field(default_factory=list)
    ehlo_names: list[str] = field(default_factory=list)
    auth_attempts: list[tuple[str, str]] = field(default_factory=list)
    plaintext_mail_attempts: int = 0
    silent: bool = False  # accept connections and never speak, to test timeouts
    _sock: socket.socket | None = None

    def start(self) -> "FakeSmtp":
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._sock:
            self._sock.close()

    def _context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*self.cert)
        return ctx

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            if self.silent:
                threading.Event().wait(5)
                return
            tls = False
            if self.mode == "ssl":
                conn = self._context().wrap_socket(conn, server_side=True)
                tls = True
            f = conn.makefile("rwb", buffering=0)

            def say(*lines: str) -> None:
                f.write(("".join(f"{x}\r\n" for x in lines)).encode())

            say("220 fake ESMTP")
            mail_from, rcpt = "", []
            while True:
                line = f.readline().decode(errors="replace").strip()
                if not line:
                    return
                verb = line.split(" ", 1)[0].upper()
                if verb in ("EHLO", "HELO"):
                    self.ehlo_names.append(line.split(" ", 1)[1] if " " in line else "")
                    caps = ["250-fake", "250-8BITMIME"]
                    if self.credentials:
                        caps.append("250-AUTH PLAIN")
                    if self.mode == "starttls" and not tls:
                        caps.append("250-STARTTLS")
                    caps.append("250 SIZE 1000000")
                    say(*caps)
                elif verb == "STARTTLS":
                    say("220 ready")
                    conn = self._context().wrap_socket(conn, server_side=True)
                    f = conn.makefile("rwb", buffering=0)
                    tls = True
                elif verb == "AUTH":
                    blob = (line.split(" ") + ["", "", ""])[2]
                    _, user, password = (base64.b64decode(blob).decode() if blob else "\0\0").split("\0")
                    self.auth_attempts.append((user, password))
                    ok = self.credentials == (user, password)
                    say("235 ok" if ok else "535 5.7.8 authentication failed")
                elif verb == "MAIL":
                    if not tls:
                        self.plaintext_mail_attempts += 1
                    mail_from, rcpt = re.search(r"<([^>]*)>", line).group(1), []
                    say("250 ok")
                elif verb == "RCPT":
                    to = re.search(r"<([^>]*)>", line).group(1)
                    if to.startswith("hangup@"):
                        conn.close()
                        return
                    if to.startswith("refuse@"):
                        say("550 5.1.1 no such user")
                    elif to.startswith("defer@"):
                        say("450 4.2.0 try later")
                    else:
                        rcpt.append(to)
                        say("250 ok")
                elif verb == "DATA":
                    say("354 go")
                    chunks = []
                    while True:
                        row = f.readline()
                        if row in (b".\r\n", b""):
                            break
                        chunks.append(row[1:] if row.startswith(b"..") else row)
                    self.messages.append(Received(mail_from, rcpt, b"".join(chunks), tls))
                    say("250 queued")
                elif verb == "RSET":
                    say("250 ok")
                elif verb == "QUIT":
                    say("221 bye")
                    return
                else:
                    say("502 not implemented")
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
