"""
ClipSync - cliente PC (Python + bleak).

Conecta no ESP32 ClipSync via BLE e atua como relay da clipboard local:

  - Recebe NOTIFY em `cmd` -> se o byte for CMD_REQ_PC (0x01), le a
    clipboard atual e WRITE em `from_pc`. O firmware faz o relay para
    o celular via `to_mobile`.
  - Recebe NOTIFY em `to_pc` -> grava o payload na clipboard local
    (clipboard veio do celular, encaminhada pelo ESP32).

TODO futuro (registrado em CLAUDE.md): manter historico dos N ultimos
itens de clipboard e responder a um CMD_REQ_PC_LIST com a lista, pra
que o display permita escolher qual item enviar.
"""

import asyncio
import sys
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
except ImportError:
    sys.stderr.write("erro: bleak nao instalado. Rode 'pip install -r requirements.txt'\n")
    sys.exit(1)

try:
    import pyperclip
except ImportError:
    sys.stderr.write("erro: pyperclip nao instalado. Rode 'pip install -r requirements.txt'\n")
    sys.exit(1)


# UUIDs - devem bater com src/main.cpp do firmware
SERVICE_UUID  = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e"
CHAR_CMD      = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5f"
CHAR_FROM_PC  = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d60"
CHAR_TO_PC    = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d62"

DEVICE_NAME = "ClipSync"

# Codigos do byte unico em `cmd` (definidos no firmware como CMD_REQ_*)
CMD_REQ_PC     = 0x01  # "PC, envie sua clipboard"
CMD_REQ_MOBILE = 0x02  # ignorado pelo PC (e pro celular)

# Limite seguro do payload BLE (MTU 517 - overhead ATT ~3-5).
# macOS negocia MTU ~185 -> ~180 bytes uteis. Sem chunking, payloads
# maiores sao truncados silenciosamente no firmware. Item 4 do CLAUDE.md.
MAX_PAYLOAD_BYTES = 500


def log(msg: str) -> None:
    print(msg, flush=True)


def read_clipboard() -> bytes:
    try:
        text = pyperclip.paste() or ""
    except Exception as e:
        log(f"[clip] erro lendo clipboard: {e}")
        return b""
    data = text.encode("utf-8", errors="replace")
    if len(data) > MAX_PAYLOAD_BYTES:
        log(f"[clip] payload {len(data)} bytes > {MAX_PAYLOAD_BYTES} - truncando "
            f"(o firmware ainda nao tem chunking)")
        data = data[:MAX_PAYLOAD_BYTES]
    return data


def write_clipboard(data: bytes) -> None:
    try:
        text = data.decode("utf-8", errors="replace")
        pyperclip.copy(text)
        log(f"[clip] copiado para clipboard local: {len(data)} bytes")
    except Exception as e:
        log(f"[clip] erro escrevendo clipboard: {e}")


async def run_session(device: BLEDevice) -> None:
    log(f"[ble] conectando em {device.name} ({device.address})...")
    async with BleakClient(device) as client:
        log("[ble] conectado")

        # Callback de cmd: e chamada na thread/loop do bleak; precisa ser async
        # para conseguir await write_gatt_char.
        async def on_cmd(_sender, data: bytearray) -> None:
            if not data:
                return
            code = data[0]
            log(f"[ble] cmd recebido: 0x{code:02x}")
            if code == CMD_REQ_PC:
                payload = read_clipboard()
                if not payload:
                    log("[clip] clipboard vazia, nada a enviar")
                    return
                try:
                    await client.write_gatt_char(CHAR_FROM_PC, payload, response=False)
                    log(f"[ble] enviado {len(payload)} bytes em from_pc")
                except Exception as e:
                    log(f"[ble] erro no write: {e}")

        def on_to_pc(_sender, data: bytearray) -> None:
            if not data:
                return
            write_clipboard(bytes(data))

        await client.start_notify(CHAR_CMD,   on_cmd)
        await client.start_notify(CHAR_TO_PC, on_to_pc)
        log("[ble] inscrito em cmd e to_pc. Aguardando eventos. (Ctrl+C para sair)")

        # Loop ate o ESP32 desconectar (ou o usuario interromper)
        while client.is_connected:
            await asyncio.sleep(1)
        log("[ble] desconectado pelo peer")


async def find_device(timeout: float = 10.0) -> Optional[BLEDevice]:
    # Procurar por SERVICE UUID e nao por nome - o nome pode nao caber no
    # adv packet (max 31 bytes) dependendo da config do firmware NimBLE.
    # O service UUID e sempre anunciado.
    log(f"[ble] procurando service {SERVICE_UUID} por {timeout:.0f}s...")

    target = SERVICE_UUID.lower()

    def match_by_service(_dev: BLEDevice, adv) -> bool:
        for u in (adv.service_uuids or []):
            if u.lower() == target:
                return True
        # Fallback: tenta tambem pelo nome, caso esteja exposto.
        if (adv.local_name or _dev.name or "") == DEVICE_NAME:
            return True
        return False

    return await BleakScanner.find_device_by_filter(match_by_service, timeout=timeout)


async def main_loop() -> None:
    backoff = 2.0
    while True:
        device = await find_device(timeout=10.0)
        if device is None:
            log(f"[ble] nao encontrado, tentando de novo em {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)
            continue
        backoff = 2.0
        try:
            await run_session(device)
        except Exception as e:
            log(f"[ble] sessao caiu: {e}")
        log("[ble] retomando em 2s...")
        await asyncio.sleep(2.0)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log("\n[ble] encerrando")
