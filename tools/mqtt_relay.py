#!/usr/bin/env python3
"""Transparent MQTT relay for the PETLIBRO Polar (credential capture / protocol logging).

Listens on :1883, forwards every byte to the Petlibro broker and logs the decoded MQTT
packets of both directions to /data/traffic.jsonl. The CONNECT login is written only to
/data/credentials.json (mode 0600), never to the traffic log. Cloud->device publishes whose
payload contains one of DROP_WORDS (default: OTA, UPGRADE, FIRMWARE, FEEDING_PLAN) are
logged but not delivered.
"""
import asyncio
import json
import os
import socket
import time

UPSTREAM_HOST = os.environ.get("UPSTREAM_HOST", "mqtt.us.petlibro.com")
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "1883"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "1883"))
DATA = os.environ.get("DATA_DIR", "/data")
LOG = os.path.join(DATA, "traffic.jsonl")
CRED = os.path.join(DATA, "credentials.json")

TYPES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 8: "SUBSCRIBE",
         9: "SUBACK", 10: "UNSUBSCRIBE", 11: "UNSUBACK", 12: "PINGREQ",
         13: "PINGRESP", 14: "DISCONNECT"}


def log(entry):
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False)[:500], flush=True)


def u16(b, i):
    return (b[i] << 8) | b[i + 1], i + 2


def mqtt_str(b, i):
    n, i = u16(b, i)
    return b[i:i + n].decode("utf-8", "replace"), i + n


def decode(direction, ptype, flags, body, peer):
    name = TYPES.get(ptype, str(ptype))
    entry = {"dir": direction, "peer": peer, "type": name}
    try:
        if ptype == 1:  # CONNECT
            i = 0
            proto, i = mqtt_str(body, i)
            level = body[i]; cflags = body[i + 1]; i += 2
            keepalive, i = u16(body, i)
            client_id, i = mqtt_str(body, i)
            entry.update(proto=proto, level=level, keepalive=keepalive, client_id=client_id)
            if cflags & 0x04:
                wt, i = mqtt_str(body, i)
                wl, i = u16(body, i)
                entry["will_topic"] = wt
                i += wl
            cred = {"client_id": client_id}
            if cflags & 0x80:
                cred["username"], i = mqtt_str(body, i)
                entry["username"] = cred["username"]
            if cflags & 0x40:
                cred["password"], i = mqtt_str(body, i)
                entry["password"] = "<redacted>"
            fd = os.open(CRED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(cred, f)
        elif ptype == 3:  # PUBLISH
            qos = (flags >> 1) & 3
            topic, i = mqtt_str(body, 0)
            if qos:
                _, i = u16(body, i)
            payload = body[i:]
            try:
                entry["payload"] = json.loads(payload.decode("utf-8"))
            except Exception:
                entry["payload_raw"] = payload.decode("utf-8", "replace")
            entry.update(topic=topic, qos=qos, retain=bool(flags & 1))
        elif ptype in (8, 10):  # (UN)SUBSCRIBE
            _, i = u16(body, 0)
            topics = []
            while i < len(body):
                t, i = mqtt_str(body, i)
                if ptype == 8:
                    i += 1
                topics.append(t)
            entry["topics"] = topics
        elif ptype == 2:
            entry["return_code"] = body[1] if len(body) > 1 else None
        elif ptype in (12, 13):
            return  # Ping nicht protokollieren
    except Exception as e:  # Protokoll nie den Datenfluss stoeren lassen
        entry["decode_error"] = repr(e)
    log(entry)


DROP_WORDS = [w for w in os.environ.get("DROP_WORDS", "OTA,UPGRADE,FIRMWARE,FEEDING_PLAN").upper().split(",") if w]


def should_drop(direction, ptype, flags, body):
    """Cloud->Polar: OTA-/Plan-Befehle nur mitschreiben, nicht zustellen."""
    if direction != "cloud->dev" or ptype != 3:
        return False
    try:
        qos = (flags >> 1) & 3
        _, i = mqtt_str(body, 0)
        if qos:
            i += 2
        payload = body[i:].decode("utf-8", "replace").upper()
    except Exception:
        return False
    head = payload[:400]
    return any(w in head for w in DROP_WORDS)


async def pump(reader, writer, direction, peer):
    buf = b""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            buf += data
            out = b""
            while len(buf) >= 2:
                mult, length, i = 1, 0, 1
                while True:
                    if i >= len(buf):
                        length = None
                        break
                    byte = buf[i]
                    length += (byte & 0x7F) * mult
                    mult *= 128
                    i += 1
                    if not byte & 0x80:
                        break
                if length is None or len(buf) < i + length:
                    break
                ptype, flags = buf[0] >> 4, buf[0] & 0x0F
                body = buf[i:i + length]
                drop = should_drop(direction, ptype, flags, body)
                decode(direction + (" DROPPED" if drop else ""), ptype, flags, body, peer)
                if not drop:
                    out += buf[:i + length]
                buf = buf[i + length:]
            if out:
                writer.write(out)
                await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader, client_writer):
    peer = client_writer.get_extra_info("peername")[0]
    log({"dir": "info", "peer": peer, "type": "TCP_OPEN"})
    try:
        up_reader, up_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except Exception as e:
        log({"dir": "info", "peer": peer, "type": "UPSTREAM_ERROR", "error": repr(e)})
        client_writer.close()
        return
    await asyncio.gather(
        pump(client_reader, up_writer, "dev->cloud", peer),
        pump(up_reader, client_writer, "cloud->dev", peer),
    )
    log({"dir": "info", "peer": peer, "type": "TCP_CLOSE"})


async def main():
    os.makedirs(DATA, exist_ok=True)
    server = await asyncio.start_server(handle, "0.0.0.0", LISTEN_PORT)
    sock = server.sockets[0]
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    log({"dir": "info", "type": "START", "upstream": f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"})
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
