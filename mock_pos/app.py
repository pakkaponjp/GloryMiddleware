import json, socket

HOST, PORT = "0.0.0.0", 9001

def handle_line(line: str) -> dict:
    try:
        req = json.loads(line)
    except Exception:
        return {"status": "error", "description": "invalid json"}

    # You can branch by message_type if your payload includes it.
    # For now, always ACK/OK.
    if req.get("message_type") == "heartbeat":
        return {"status": "acknowledged"}
    return {"status": "OK", "description": "Deposit Success"}

with socket.create_server((HOST, PORT), reuse_port=True) as srv:
    print(f"POS TCP MOCK listening on {HOST}:{PORT}")
    while True:
        conn, addr = srv.accept()
        with conn:
            buf = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    line, _ = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    print("RX:", text)
                    resp = handle_line(text)
                    out = (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
                    conn.sendall(out)
                    print("TX:", resp)
                    break

