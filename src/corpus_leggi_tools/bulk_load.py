"""Entry point ``corpus-leggi-bulk`` — bulk load iniziale via export asincrono.

Stub: implementazione in arrivo. Il flusso previsto è:
  1. POST /ricerca-asincrona/nuova-ricerca (formato AKN, filtri tipo/anno)
  2. PUT /ricerca-asincrona/conferma-ricerca {token}
  3. polling GET /check-status/{token} fino a 303
  4. download ZIP dall'header x-ipzs-location
  5. unzip → per ogni cartella atto prendi VIGENZA_V{max}.xml
  6. per ogni XML applica la stessa pipeline di sync_delta.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print("corpus-leggi-bulk: not yet implemented", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
