# ClipSync - cliente PC

Cliente Python que conversa via BLE com o firmware ClipSync rodando num
ESP32 + ILI9341 + XPT2046. Quando o usuario toca **PC + ENVIAR** no display
do ESP32, este cliente le a clipboard local e a manda; quando o celular
envia uma clipboard, o ESP32 encaminha para ca e este cliente cola na
clipboard local.

O firmware do ESP32 vive em outro repo:
`C:\Users\lordk\OneDrive\Documentos\Documentos\PlatformIO\Projects\BLE Task Board\`

## Setup

Windows:

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python clipsync_pc.py

Linux:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    # Dependencia do pyperclip:
    sudo apt install xclip          # X11
    sudo apt install wl-clipboard   # Wayland
    python clipsync_pc.py

macOS:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python clipsync_pc.py

> **Atencao macOS:** o backend BLE da Apple negocia MTU em ~185 bytes.
> Sem chunking no firmware, textos > ~180 bytes serao truncados
> silenciosamente.

## Como funciona

1. Procura device BLE com nome `ClipSync` (BleakScanner por nome).
2. Conecta e inscreve em duas characteristics:
   - `cmd` (NOTIFY, UUID terminado em `...d5f`): byte 0x01 = "PC, envie
     sua clipboard agora".
   - `to_pc` (NOTIFY, UUID terminado em `...d62`): bytes do payload
     que veio do celular.
3. Em `cmd == 0x01`: chama `pyperclip.paste()`, codifica UTF-8, faz
   `write_gatt_char(from_pc, ...)`. O ESP32 relaya para `to_mobile`.
4. Em `to_pc`: decodifica UTF-8, chama `pyperclip.copy(text)`.
5. Reconecta automaticamente se o ESP32 cair / sair de alcance.

Codigos do `cmd` definidos no firmware (`src/main.cpp` la):

| Byte | Significado |
|------|-------------|
| 0x01 | "PC, envie sua clipboard"   |
| 0x02 | "Celular, envie sua clipboard" (ignorado por este cliente) |

## TODO

Quando o item de "historico de clipboard" do roadmap entrar (ver
`CLAUDE.md` do firmware, secao "Backlog / TODOs de produto"):

- Manter lista circular dos N ultimos items copiados (hook em mudancas
  de clipboard).
- Responder a novo comando `CMD_REQ_PC_LIST` enviando a lista.
- Aguardar `CMD_PICK_INDEX` do ESP32 e enviar o item escolhido.
