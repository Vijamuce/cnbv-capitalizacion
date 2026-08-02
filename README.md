# Capitalización de las instituciones financieras en México

Página que muestra el Índice/Nivel de Capitalización (ICAP/NICAP) de instituciones financieras mexicanas, con datos oficiales de la CNBV (Comisión Nacional Bancaria y de Valores):

- **Bancos** (banca múltiple) — ICAP por institución
- **SOFIPOS** (sociedades financieras populares) — NICAP por institución
- **SOCAPs** (cooperativas de ahorro y préstamo) — NICAP por institución
- **Casas de bolsa** — solo ICAP agregado del sistema (la CNBV publica el desglose por institución como imagen, no como texto extraíble)
- **Fintech** (IFPE/IFC) — la CNBV no publica un índice de capitalización recurrente por institución; se muestra el último reporte agregado conocido y se revisa cada semana por si publican algo nuevo

Publicada vía GitHub Pages en `https://<usuario>.github.io/cnbv-capitalizacion/`.

## Cómo se mantiene actualizada

`.github/workflows/weekly-update.yml` corre cada lunes 8:00 a.m. (hora de Monterrey) — y también se puede disparar a mano desde la pestaña *Actions* (`workflow_dispatch`). Ejecuta `scripts/update.py`, que:

1. Lee la fecha "cifras al" que ya está guardada en cada `docs/data/*.json`.
2. Prueba si la CNBV publicó el boletín del mes siguiente para cada sector (bancos y casas de bolsa vía `gob.mx/cnbv/prensa`, SOFIPOS/SOCAPs vía `portafolioinfo.cnbv.gob.mx`).
3. Si encuentra un boletín nuevo, descarga el PDF, lo convierte con `pdftotext -layout` y actualiza el JSON correspondiente.
4. Si algo cambió, hace commit y push directo a `main`; el segundo job del workflow republica GitHub Pages.
5. La mayoría de las semanas no habrá nada que hacer — la CNBV publica cifras mensuales, con varias semanas de rezago. Eso es normal, no un error.

Nota técnica: `portafolioinfo.cnbv.gob.mx` tiene un certificado TLS con cadena incompleta, así que esa parte del script desactiva la verificación de certificado específicamente para ese dominio (es contenido público de gob.mx, no hay credenciales de por medio).

## Estructura

```
docs/
  index.html          # página estática, sin build step — hace fetch() de docs/data/*.json
  data/*.json          # los datos en sí; esto es lo único que toca el workflow semanal
scripts/update.py      # el scraper/parser
.github/workflows/weekly-update.yml
```

## Correrlo a mano

```bash
pip install -r requirements.txt  # no hay dependencias externas, solo stdlib + pdftotext del sistema
sudo apt install poppler-utils   # o pacman -S poppler en Arch/CachyOS
python3 scripts/update.py
```

## Fuera de alcance

No incluye per-institución de casas de bolsa (imagen, no texto) ni fintechs (sin boletín recurrente por institución). Si la CNBV cambia esto en el futuro, `scripts/update.py` tendría que actualizarse para reflejarlo.
